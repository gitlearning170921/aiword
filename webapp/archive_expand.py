# -*- coding: utf-8 -*-
"""解压训练/审核用压缩包，与 aicheckword Streamlit _expand_uploads 行为对齐（仅取可训练扩展名）。"""
from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path
from typing import Iterable

_TRAIN_SUFFIXES = {
    ".pdf", ".doc", ".docx", ".txt", ".md", ".xlsx", ".xls", ".ppt", ".pptx",
}

_TRANSLATION_SUFFIXES = {".docx", ".txt", ".xlsx"}


def expand_translation_blobs(
    items: Iterable[tuple[str, bytes]],
) -> list[tuple[str, bytes]]:
    """翻译上传：zip/tar 解压后仅保留 .docx/.txt/.xlsx。"""
    flat = expand_upload_blobs(items)
    return [(n, b) for n, b in flat if Path(n).suffix.lower() in _TRANSLATION_SUFFIXES]


def _allowed_suffix(name: str) -> bool:
    return Path(name or "").suffix.lower() in _TRAIN_SUFFIXES


def flatten_upload_file_storage(files) -> list[tuple[str, bytes]]:
    """Flask FileStorage 列表 → 扁平 (文件名, bytes)；zip/tar 自动解压一层。"""
    raw: list[tuple[str, bytes]] = []
    for f in files or []:
        name = str(getattr(f, "filename", None) or "upload.bin").strip() or "upload.bin"
        try:
            data = f.read()
        except Exception:
            continue
        if data:
            raw.append((name, data))
    return expand_upload_blobs(raw)


def expand_upload_blobs(
    items: Iterable[tuple[str, bytes]],
) -> list[tuple[str, bytes]]:
    """(filename, raw) -> 扁平文件列表；zip/tar 自动解压一层。"""
    out: list[tuple[str, bytes]] = []
    for filename, raw in items:
        if not raw:
            continue
        name = str(filename or "upload.bin")
        lower = name.lower()
        if lower.endswith(".zip"):
            out.extend(_expand_zip(raw, name))
            continue
        if lower.endswith((".tar", ".tar.gz", ".tgz")):
            out.extend(_expand_tar(raw, name))
            continue
        if _allowed_suffix(name):
            out.append((name, raw))
    return out


def _expand_zip(raw: bytes, archive_name: str) -> list[tuple[str, bytes]]:
    result: list[tuple[str, bytes]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                inner = Path(info.filename).name
                if not _allowed_suffix(inner):
                    continue
                data = zf.read(info)
                if data:
                    result.append((f"{Path(archive_name).stem}/{inner}", data))
    except Exception:
        pass
    return result


def _expand_tar(raw: bytes, archive_name: str) -> list[tuple[str, bytes]]:
    result: list[tuple[str, bytes]] = []
    mode = "r:gz" if archive_name.lower().endswith((".gz", ".tgz")) else "r:"
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode=mode) as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                inner = Path(member.name).name
                if not _allowed_suffix(inner):
                    continue
                extracted = tf.extractfile(member)
                if extracted is None:
                    continue
                data = extracted.read()
                if data:
                    result.append((f"{Path(archive_name).stem}/{inner}", data))
    except Exception:
        pass
    return result
