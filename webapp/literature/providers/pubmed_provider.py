from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from .. import LiteratureRecord
from ..http_client import literature_get


PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _build_term(query: str, start_year: int | None, end_year: int | None) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    if start_year and end_year:
        return f"({q}) AND ({start_year}:{end_year}[dp])"
    if start_year:
        return f"({q}) AND ({start_year}:3000[dp])"
    if end_year:
        return f"({q}) AND (1900:{end_year}[dp])"
    return q


def _extract_text(elem: ET.Element | None, path: str) -> str:
    if elem is None:
        return ""
    hit = elem.find(path)
    if hit is None or hit.text is None:
        return ""
    return hit.text.strip()


def _extract_authors(citation: ET.Element) -> str:
    names: list[str] = []
    for author in citation.findall("./AuthorList/Author"):
        collective = _extract_text(author, "./CollectiveName")
        if collective:
            names.append(collective)
            continue
        last = _extract_text(author, "./LastName")
        fore = _extract_text(author, "./ForeName")
        if last and fore:
            names.append(f"{last} {fore}")
        elif last:
            names.append(last)
    return ", ".join(names)


def _extract_year(article: ET.Element) -> str:
    for path in (
        "./MedlineCitation/Article/Journal/JournalIssue/PubDate/Year",
        "./MedlineCitation/DateCompleted/Year",
        "./MedlineCitation/DateRevised/Year",
    ):
        value = _extract_text(article, path)
        if value:
            return value
    medline_date = _extract_text(article, "./MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate")
    if medline_date:
        for token in medline_date.split():
            if token.isdigit() and len(token) == 4:
                return token
    return ""


def _extract_volume_issue_pages(article: ET.Element) -> str:
    issue = article.find("./MedlineCitation/Article/Journal/JournalIssue")
    if issue is None:
        return ""
    volume = _extract_text(issue, "./Volume")
    number = _extract_text(issue, "./Issue")
    pages = _extract_text(article, "./MedlineCitation/Article/Pagination/MedlinePgn")
    if volume and number and pages:
        return f"{volume}({number}):{pages}"
    if volume and pages:
        return f"{volume}:{pages}"
    return pages or volume or number


def _extract_doi(article: ET.Element) -> str:
    for node in article.findall("./PubmedData/ArticleIdList/ArticleId"):
        if (node.attrib.get("IdType") or "").lower() == "doi" and node.text:
            return node.text.strip()
    return ""


def search_pubmed(
    *,
    query: str,
    start_year: int | None = None,
    end_year: int | None = None,
    max_results: int = 50,
    timeout_seconds: int = 25,
) -> list[LiteratureRecord]:
    term = _build_term(query, start_year, end_year)
    if not term:
        return []

    params: dict[str, Any] = {
        "db": "pubmed",
        "retmode": "json",
        "retmax": max(1, min(200, int(max_results))),
        "term": term,
    }
    search_resp = literature_get(
        f"{PUBMED_BASE}/esearch.fcgi",
        params=params,
        timeout=timeout_seconds,
    )
    payload = search_resp.json()
    id_list = (((payload or {}).get("esearchresult") or {}).get("idlist") or [])
    ids = [str(x).strip() for x in id_list if str(x).strip()]
    if not ids:
        return []

    fetch_resp = literature_get(
        f"{PUBMED_BASE}/efetch.fcgi",
        params={"db": "pubmed", "retmode": "xml", "id": ",".join(ids)},
        timeout=timeout_seconds,
    )
    root = ET.fromstring(fetch_resp.text)

    records: list[LiteratureRecord] = []
    for article in root.findall("./PubmedArticle"):
        title = _extract_text(article, "./MedlineCitation/Article/ArticleTitle")
        journal = _extract_text(article, "./MedlineCitation/Article/Journal/Title")
        pmid = _extract_text(article, "./MedlineCitation/PMID")
        record: LiteratureRecord = {
            "source": "pubmed",
            "title": title,
            "authors": _extract_authors(article.find("./MedlineCitation/Article") or ET.Element("Article")),
            "year": _extract_year(article),
            "journal": journal,
            "volume_issue_pages": _extract_volume_issue_pages(article),
            "doi": _extract_doi(article),
            "pmid": pmid,
            "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        }
        records.append(record)
    return records
