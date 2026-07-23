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


def record_identity_keys(rec: LiteratureRecord) -> list[tuple[str, str, str]]:
    """用于匹配同一文献的身份键列表（按优先级：doi → pmid → url → title）。"""
    source = normalize_text(rec.get("source")).lower() or "unknown"
    keys: list[tuple[str, str, str]] = []
    doi = normalize_text(rec.get("doi")).lower()
    pmid = normalize_text(rec.get("pmid"))
    url = normalize_text(rec.get("source_url")).lower()
    tkey = _title_key(rec.get("title") or "")
    if doi:
        keys.append((source, "doi", doi))
    if pmid:
        keys.append((source, "pmid", pmid))
    if url:
        keys.append((source, "url", url))
    if tkey:
        keys.append((source, "title", tkey))
    return keys


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


_MARK_FIELDS = ("selected", "duplicate", "no_fulltext")


def merge_import_update(
    prior: list[LiteratureRecord],
    incoming: list[LiteratureRecord],
) -> tuple[list[LiteratureRecord], dict[str, int]]:
    """重新导入更新：尽量保持旧序号位置，匹配条目原地更新并保留人工标记。

    策略：
    - 先对 incoming 去重；
    - 按 prior 原顺序遍历：命中则用新内容替换并保留 selected/duplicate/no_fulltext，占位序号不变；
    - prior 中未命中的保留原位（序号不前移）；
    - incoming 中全新条目追加到末尾。
    """
    new_list = dedupe_records(incoming)
    # key -> (index_in_new_list, rec)
    index_by_key: dict[tuple[str, str, str], int] = {}
    for i, rec in enumerate(new_list):
        for k in record_identity_keys(rec):
            # 先到先得：同一批内同键只对应一条
            if k not in index_by_key:
                index_by_key[k] = i

    used: set[int] = set()
    merged: list[LiteratureRecord] = []
    updated = 0
    kept = 0

    for old in prior or []:
        old_n = normalize_record(old) if isinstance(old, dict) else old
        hit_i: int | None = None
        for k in record_identity_keys(old_n):
            if k in index_by_key:
                hit_i = index_by_key[k]
                break
        if hit_i is None or hit_i in used:
            merged.append(old_n)
            kept += 1
            continue
        used.add(hit_i)
        fresh = dict(new_list[hit_i])
        # 保留人工标记（选用/重复/无法获取全文）
        for mf in _MARK_FIELDS:
            if old_n.get(mf):
                fresh[mf] = True
        merged.append(normalize_record(fresh))
        updated += 1

    added = 0
    for i, rec in enumerate(new_list):
        if i in used:
            continue
        merged.append(rec)
        added += 1

    return merged, {
        "updated": updated,
        "kept": kept,
        "added": added,
        "incoming": len(new_list),
        "total": len(merged),
    }