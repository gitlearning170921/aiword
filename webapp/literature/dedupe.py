from __future__ import annotations

import re
from typing import Iterable

from . import LiteratureRecord
from .normalize import normalize_record, normalize_text


def _title_key(title: str) -> str:
    t = normalize_text(title).lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", t)


def _first_author(authors: str) -> str:
    text = normalize_text(authors)
    if not text:
        return ""
    return normalize_text(text.split(",")[0]).lower()


def dedupe_records(records: Iterable[LiteratureRecord]) -> list[LiteratureRecord]:
    """按来源内去重（模板按 Database 分列，跨库同文可并存）。"""
    by_doi: dict[tuple[str, str], LiteratureRecord] = {}
    by_pmid: dict[tuple[str, str], LiteratureRecord] = {}
    by_url: dict[tuple[str, str], LiteratureRecord] = {}
    by_title: dict[tuple[str, str], LiteratureRecord] = {}
    output: list[LiteratureRecord] = []

    for raw in records:
        rec = normalize_record(raw)
        title = rec.get("title") or ""
        if not title:
            continue

        source = normalize_text(rec.get("source")).lower() or "unknown"
        doi = normalize_text(rec.get("doi")).lower()
        pmid = normalize_text(rec.get("pmid"))
        url = normalize_text(rec.get("source_url")).lower()
        tkey = _title_key(title)

        if doi and (source, doi) in by_doi:
            continue
        if pmid and (source, pmid) in by_pmid:
            continue
        if url and (source, url) in by_url:
            continue
        if tkey and (source, tkey) in by_title:
            continue

        output.append(rec)
        if doi:
            by_doi[(source, doi)] = rec
        if pmid:
            by_pmid[(source, pmid)] = rec
        if url:
            by_url[(source, url)] = rec
        if tkey:
            by_title[(source, tkey)] = rec

    return output
