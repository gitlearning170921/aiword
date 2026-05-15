# -*- coding: utf-8 -*-
"""页面 1 任务模板上传：支持 .zip / .tar / .tar.gz / .tgz（及可选 .rar），与 aicheckword 解压展开逻辑对齐。

压缩包内须至少包含一个 ``.docx``；多文件时优先匹配「文件名称」字段对应的文件名/主名，否则取路径排序后的第一个。
解压后的模板字节写入 ``template_file_blob``（仍为 OOXML），占位符解析沿用 ``doc_service.extract_placeholders_from_bytes``。
"""

from __future__ import annotations

import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import List

from .doc_service import extract_placeholders, extract_placeholders_from_bytes

_DEPRECATED = "废弃"


def _is_deprecated_path(path_or_name: str) -> bool:
    return _DEPRECATED in str(path_or_name)


def is_task_template_archive(path: Path) -> bool:
    p = Path(path)
    n = p.name.lower()
    if n.endswith(".tar.gz") or n.endswith(".tgz"):
        return True
    return p.suffix.lower() in (".zip", ".tar", ".gz", ".rar")


def _open_zip_with_encoding(archive_path: Path) -> zipfile.ZipFile:
    """与 aicheckword ``document_loader._open_zip_with_encoding`` 一致：兼容中文文件名。"""
    try:
        _ = zipfile.ZipFile(archive_path, "r", metadata_encoding="utf-8")
        _.close()
    except TypeError:
        return zipfile.ZipFile(archive_path, "r")
    for enc in ("gbk", "utf-8", "cp437"):
        try:
            zf = zipfile.ZipFile(archive_path, "r", metadata_encoding=enc)
            names = zf.namelist()
            if names and any("\ufffd" in n for n in names):
                zf.close()
                continue
            return zf
        except (ValueError, UnicodeDecodeError):
            continue
    return zipfile.ZipFile(archive_path, "r", metadata_encoding="utf-8")


def _resolved_under_root(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _collect_docx_from_dir(root: Path) -> List[Path]:
    out: List[Path] = []
    for fp in root.rglob("*"):
        if not fp.is_file() or fp.suffix.lower() != ".docx":
            continue
        if _is_deprecated_path(str(fp)) or _is_deprecated_path(fp.name):
            continue
        if not _resolved_under_root(root, fp):
            continue
        out.append(fp)
    return out


def _extract_archive_to_temp(archive_path: Path, temp_dir: Path) -> List[Path]:
    """解压到 ``temp_dir``，返回其中所有 .docx 路径（不含子包）。"""
    ap = Path(archive_path)
    doc_files: List[Path] = []

    if ap.suffix.lower() == ".zip":
        zf = _open_zip_with_encoding(ap)
        try:
            for name in zf.namelist():
                if name.endswith("/") or "/__MACOSX" in name:
                    continue
                base = Path(name).name
                if not base or base.startswith("."):
                    continue
                if Path(name).suffix.lower() != ".docx":
                    continue
                zf.extract(name, str(temp_dir))
                extracted = temp_dir / name
                if extracted.is_file() and _resolved_under_root(temp_dir, extracted):
                    if not _is_deprecated_path(name):
                        doc_files.append(extracted)
        finally:
            zf.close()
        return doc_files

    if ap.name.lower().endswith((".tar.gz", ".tgz")) or ap.suffix.lower() in (".tar", ".gz"):
        with tarfile.open(ap, "r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                name = member.name
                if "/__MACOSX" in name or name.startswith("."):
                    continue
                if not name.lower().endswith(".docx"):
                    continue
                tf.extract(member, str(temp_dir))
                extracted = temp_dir / member.name
                if extracted.is_file() and _resolved_under_root(temp_dir, extracted):
                    if not _is_deprecated_path(member.name):
                        doc_files.append(extracted)
        return doc_files

    if ap.suffix.lower() == ".rar":
        try:
            import rarfile
        except ImportError as e:
            raise ValueError(
                "解压 .rar 需安装 rarfile（pip install rarfile）且系统配置 UnRAR；"
                "也可改为 .zip / .tar.gz 后上传。"
            ) from e
        with rarfile.RarFile(ap) as rf:
            for name in rf.namelist():
                if name.endswith("/") or "/__MACOSX" in name or not name.strip():
                    continue
                base = Path(name).name
                if not base or base.startswith("."):
                    continue
                if not name.lower().endswith(".docx"):
                    continue
                rf.extract(name, str(temp_dir))
                extracted = temp_dir / name
                if extracted.is_file() and _resolved_under_root(temp_dir, extracted):
                    if not _is_deprecated_path(name):
                        doc_files.append(extracted)
        return doc_files

    raise ValueError(f"不支持的压缩格式: {ap.suffix or ap.name}")


def _pick_docx(docx_paths: List[Path], file_name_hint: str) -> Path:
    if not docx_paths:
        raise ValueError(
            "压缩包内未找到 .docx 模板。"
            "当前任务占位符解析与生成仅支持 OOXML Word（.docx），与 aicheckword 侧常用约定一致。"
        )
    hint = (file_name_hint or "").strip().lower()
    hint_stem = Path(hint).stem.lower() if hint else ""
    ordered = sorted(docx_paths, key=lambda p: str(p).lower())
    if hint_stem:
        for p in ordered:
            if p.stem.lower() == hint_stem or p.name.lower() == hint:
                return p
    return ordered[0]


def resolve_task_template_from_saved_path(saved_path: Path, *, file_name_hint: str) -> tuple[bytes, list]:
    """从已落盘的单次上传文件解析出模板字节与占位符列表。"""
    p = Path(saved_path)
    if not p.is_file():
        raise FileNotFoundError(str(p))

    if is_task_template_archive(p):
        tmp = tempfile.mkdtemp(prefix="aiword_task_tpl_")
        try:
            tdir = Path(tmp)
            docx_list = _extract_archive_to_temp(p, tdir)
            if not docx_list:
                docx_list = _collect_docx_from_dir(tdir)
            chosen = _pick_docx(docx_list, file_name_hint)
            blob = chosen.read_bytes()
            ph = extract_placeholders_from_bytes(blob)
            return blob, ph
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    placeholders = extract_placeholders(str(p))
    blob = p.read_bytes()
    return blob, placeholders
