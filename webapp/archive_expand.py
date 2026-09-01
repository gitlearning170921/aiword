# -*- coding: utf-8 -*-
"""解压训练/审核用压缩包，与 aicheckword ``extract_archive`` / ``_open_zip_with_encoding`` 对齐。

仅展开一层压缩包（包内若再套 zip 会再展开一层），取出可审核/训练文档。
中文 Windows 压缩包按 gbk/utf-8 尝试文件名编码；解压失败不再静默成空列表。
"""
from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path
from typing import Iterable, Optional

_DOC_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".txt",
    ".md",
    ".xlsx",
    ".xls",
    ".ppt",
    ".pptx",
}

_TRANSLATION_SUFFIXES = {".docx", ".txt", ".xlsx"}
_ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".gz", ".rar", ".7z")
_DEPRECATED = "废弃"


class ArchiveExpandError(ValueError):
    """压缩包无法展开为文档时抛出，供路由转成用户可读错误。"""


def expand_translation_blobs(
    items: Iterable[tuple[str, bytes]],
) -> list[tuple[str, bytes]]:
    """翻译上传：zip/tar 解压后仅保留 .docx/.txt/.xlsx。"""
    flat = expand_upload_blobs(items)
    return [(n, b) for n, b in flat if Path(n).suffix.lower() in _TRANSLATION_SUFFIXES]


def is_archive_name(name: str) -> bool:
    lower = str(name or "").strip().lower()
    return lower.endswith(_ARCHIVE_SUFFIXES)


def _allowed_suffix(name: str) -> bool:
    return Path(name or "").suffix.lower() in _DOC_SUFFIXES


def _is_skipped_inner_path(path_in_archive: str) -> bool:
    s = str(path_in_archive or "").replace("\\", "/")
    base = Path(s).name
    if not base or base.startswith("."):
        return True
    if base.startswith("._"):
        return True
    low = s.lower()
    if "/__macosx/" in f"/{low}/" or low.startswith("__macosx/") or "/__macosx" in low:
        return True
    if _DEPRECATED in s or _DEPRECATED in base:
        return True
    return False


def flatten_upload_file_storage(files) -> list[tuple[str, bytes]]:
    """Flask FileStorage 列表 → 扁平 (文件名, bytes)；zip/tar 自动解压。"""
    raw: list[tuple[str, bytes]] = []
    empty_names: list[str] = []
    for f in files or []:
        name = str(getattr(f, "filename", None) or "upload.bin").strip() or "upload.bin"
        try:
            data = f.read()
        except Exception as e:
            raise ArchiveExpandError(f"读取上传文件失败：{name}（{e}）") from e
        if not data:
            empty_names.append(name)
            continue
        raw.append((name, data))
    if not raw:
        if empty_names:
            raise ArchiveExpandError(
                "上传文件为空：" + "、".join(empty_names[:8]) + "。请重新选择压缩包后再提交。"
            )
        return []
    return expand_upload_blobs(raw)


def expand_upload_blobs(
    items: Iterable[tuple[str, bytes]],
    *,
    _nested: bool = False,
) -> list[tuple[str, bytes]]:
    """(filename, raw) -> 扁平文件列表；zip/tar 自动解压（默认再展开一层内嵌压缩包）。"""
    out: list[tuple[str, bytes]] = []
    errors: list[str] = []
    archive_tried = False
    for filename, raw in items:
        if not raw:
            continue
        name = str(filename or "upload.bin")
        lower = name.lower()
        if lower.endswith(".7z") or raw[:2] == b"7z":
            errors.append(f"{name}：暂不支持 7z，请改为 zip/tar 后上传")
            continue
        if lower.endswith(".rar"):
            errors.append(f"{name}：请将 rar 改为 zip 后上传")
            continue
        treat_as_zip = lower.endswith(".zip") or (
            not _allowed_suffix(name) and _looks_like_zip_archive(raw)
        )
        if treat_as_zip:
            archive_tried = True
            try:
                inner = _expand_zip(raw, name)
            except ArchiveExpandError as e:
                errors.append(str(e))
                continue
            if not inner:
                errors.append(_empty_archive_hint(name, raw))
                continue
            if not _nested:
                inner = _expand_nested_archives(inner)
            out.extend(inner)
            continue
        if lower.endswith((".tar", ".tar.gz", ".tgz")):
            archive_tried = True
            try:
                inner = _expand_tar(raw, name)
            except ArchiveExpandError as e:
                errors.append(str(e))
                continue
            if not inner:
                errors.append(_empty_archive_hint(name, raw))
                continue
            if not _nested:
                inner = _expand_nested_archives(inner)
            out.extend(inner)
            continue
        if _allowed_suffix(name):
            out.append((name, raw))
    if out:
        return out
    if errors:
        raise ArchiveExpandError("；".join(errors[:5]))
    if archive_tried:
        raise ArchiveExpandError(
            "压缩包内未找到可审核文件。支持 .pdf / .doc / .docx / .xlsx / .xls / .txt / .md。"
        )
    return out


def _expand_nested_archives(items: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """包内若还有 zip/tar，再展开一层，避免「外层空、文档全在内层压缩包」。"""
    out: list[tuple[str, bytes]] = []
    for name, blob in items:
        if is_archive_name(name) or (not _allowed_suffix(name) and _looks_like_zip_archive(blob)):
            out.extend(expand_upload_blobs([(name, blob)], _nested=True))
        else:
            out.append((name, blob))
    return out


def _looks_like_zip_archive(raw: bytes) -> bool:
    if not raw or raw[:2] != b"PK":
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return False
    if any(
        n == "[Content_Types].xml" or n.endswith("/[Content_Types].xml") for n in names
    ):
        return False
    return True


def _empty_archive_hint(archive_name: str, raw: bytes) -> str:
    listed = _peek_archive_names(raw, archive_name)
    extra = ""
    if listed:
        extra = " 包内条目：" + "、".join(listed[:12])
        if len(listed) > 12:
            extra += "…"
    return (
        f"压缩包「{archive_name}」内没有可审核文档（支持 pdf/doc/docx/xlsx/xls/txt/md）。"
        f"{extra}"
        " 请不要只打包图片、仅子压缩包（已尝试展开一层）或空文件夹。"
    )


def _peek_archive_names(raw: bytes, archive_name: str) -> list[str]:
    lower = archive_name.lower()
    names: list[str] = []
    try:
        if lower.endswith(".zip") or raw[:2] == b"PK":
            zf = _open_zip_bytes(raw)
            try:
                names = [n for n in zf.namelist() if n and not n.endswith("/")][:20]
            finally:
                zf.close()
        elif lower.endswith((".tar", ".tar.gz", ".tgz")):
            mode = "r:gz" if lower.endswith((".gz", ".tgz")) else "r:"
            with tarfile.open(fileobj=io.BytesIO(raw), mode=mode) as tf:
                names = [m.name for m in tf.getmembers() if m.isfile()][:20]
    except Exception:
        return []
    return names


def _decode_zip_member_name(info: zipfile.ZipInfo) -> str:
    raw_name = info.filename or ""
    if info.flag_bits & 0x800:
        return raw_name
    try:
        return raw_name.encode("cp437").decode("gbk")
    except (UnicodeDecodeError, UnicodeEncodeError, LookupError):
        return raw_name


def _open_zip_bytes(raw: bytes) -> zipfile.ZipFile:
    bio = io.BytesIO(raw)
    try:
        _ = zipfile.ZipFile(bio, "r", metadata_encoding="utf-8")
        _.close()
    except TypeError:
        return zipfile.ZipFile(io.BytesIO(raw), "r")
    bio.seek(0)
    last_err: Optional[BaseException] = None
    for enc in ("gbk", "utf-8", "cp437"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw), "r", metadata_encoding=enc)
            names = zf.namelist()
            if names and any("\ufffd" in n for n in names):
                zf.close()
                continue
            return zf
        except (ValueError, UnicodeDecodeError, zipfile.BadZipFile) as e:
            last_err = e
            continue
    if last_err:
        raise ArchiveExpandError(f"无法打开 zip（{last_err}）") from last_err
    return zipfile.ZipFile(io.BytesIO(raw), "r")


def _expand_zip(raw: bytes, archive_name: str) -> list[tuple[str, bytes]]:
    if raw[:3] == b"7z\xbc":
        raise ArchiveExpandError(f"{archive_name} 实际是 7z，请改为 zip 后上传")
    try:
        zf = _open_zip_bytes(raw)
    except zipfile.BadZipFile as e:
        raise ArchiveExpandError(f"压缩包「{archive_name}」不是有效 zip：{e}") from e
    result: list[tuple[str, bytes]] = []
    try:
        file_infos = [i for i in zf.infolist() if not i.is_dir()]
        if file_infos and all(i.flag_bits & 0x1 for i in file_infos):
            raise ArchiveExpandError(f"压缩包「{archive_name}」已加密，请解除密码后再上传")
        for info in zf.infolist():
            if info.is_dir():
                continue
            inner_path = _decode_zip_member_name(info)
            if _is_skipped_inner_path(inner_path):
                continue
            inner = Path(inner_path.replace("\\", "/")).name
            if not _allowed_suffix(inner) and not is_archive_name(inner):
                continue
            if info.flag_bits & 0x1:
                raise ArchiveExpandError(f"压缩包「{archive_name}」含加密文件，请解除密码后再上传")
            data = zf.read(info)
            if not data:
                continue
            rel = f"{Path(archive_name).stem}/{inner}"
            result.append((rel, data))
    finally:
        zf.close()
    return result


def _expand_tar(raw: bytes, archive_name: str) -> list[tuple[str, bytes]]:
    mode = "r:gz" if archive_name.lower().endswith((".gz", ".tgz")) else "r:"
    result: list[tuple[str, bytes]] = []
    try:
        tf = tarfile.open(fileobj=io.BytesIO(raw), mode=mode)
    except tarfile.TarError as e:
        raise ArchiveExpandError(f"压缩包「{archive_name}」不是有效 tar：{e}") from e
    try:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            if _is_skipped_inner_path(member.name):
                continue
            inner = Path(member.name).name
            if not _allowed_suffix(inner) and not is_archive_name(inner):
                continue
            extracted = tf.extractfile(member)
            if extracted is None:
                continue
            data = extracted.read()
            if not data:
                continue
            result.append((f"{Path(archive_name).stem}/{inner}", data))
    finally:
        tf.close()
    return result
