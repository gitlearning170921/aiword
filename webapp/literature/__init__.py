from __future__ import annotations

from typing import Any, TypedDict


class LiteratureRecord(TypedDict, total=False):
    source: str
    title: str
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


class LiteratureSearchResult(TypedDict, total=False):
    source: str
    records: list[LiteratureRecord]
    error: str
    elapsed_ms: int
    totalFound: int
    fetched: int


JSONDict = dict[str, Any]
