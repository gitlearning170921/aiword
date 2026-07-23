from __future__ import annotations

from typing import Any, TypedDict


class LiteratureRecord(TypedDict, total=False):
    source: str
    title: str
    abstract: str
    authors: str
    year: str
    pub_date: str
    journal: str
    volume_issue_pages: str
    doi: str
    pmid: str
    source_url: str
    source_info: str
    citation: str
    database: str
    # 人工标记（相互独立）：选用 / 重复 / 无法获取全文
    selected: bool
    duplicate: bool
    no_fulltext: bool


class LiteratureSearchResult(TypedDict, total=False):
    source: str
    records: list[LiteratureRecord]
    error: str
    elapsed_ms: int
    totalFound: int
    fetched: int


JSONDict = dict[str, Any]
