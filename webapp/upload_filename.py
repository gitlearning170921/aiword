# -*- coding: utf-8 -*-
"""上传文件名：secure_filename 会剥掉中文导致只剩扩展名字符，需补回后缀。"""
from __future__ import annotations

from pathlib import Path

from werkzeug.utils import secure_filename


def normalized_upload_extension(original: str) -> str:
    """识别 .tar.gz / .tgz 等复合后缀。"""
    lower = (original or "").strip().lower()
    for compound in (".tar.gz", ".tgz"):
        if lower.endswith(compound):
            return compound
    return Path(original).suffix.lower()


def preserved_secure_filename(original: str, *, default_stem: str = "file") -> str:
    """保留扩展名的安全文件名（中文名落盘为 file.zip / file.docx 等）。"""
    original = (original or "").strip()
    if not original:
        return default_stem
    ext = normalized_upload_extension(original)
    safe = secure_filename(original)
    if not safe:
        return f"{default_stem}{ext}" if ext else default_stem
    if ext and safe.lower().endswith(ext):
        return safe
    if ext:
        stem = Path(safe).stem
        ext_body = ext.lstrip(".").lower()
        if not stem or stem.lower() == ext_body:
            return f"{default_stem}{ext}"
        return f"{stem}{ext}"
    return safe
