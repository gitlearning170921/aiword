from __future__ import annotations

import csv
import io
from pathlib import Path

from .. import LiteratureRecord


def _split_authors(raw: str) -> str:
    parts = [x.strip() for x in (raw or "").replace(";", ",").split(",") if x.strip()]
    return ", ".join(parts)


def _parse_ris_text(content: str, source_name: str) -> list[LiteratureRecord]:
    records: list[LiteratureRecord] = []
    current: dict[str, list[str]] = {}

    def flush_one() -> None:
        if not current:
            return
        title = " ".join(current.get("TI", []) or current.get("T1", []))
        authors = ", ".join(current.get("AU", []))
        year = ""
        for key in ("PY", "Y1", "DA"):
            if current.get(key):
                year = current[key][0]
                break
        journal = " ".join(current.get("JO", []) or current.get("T2", []) or current.get("JF", []))
        volume = (current.get("VL") or [""])[0]
        issue = (current.get("IS") or [""])[0]
        pages = (current.get("SP") or [""])[0]
        end_page = (current.get("EP") or [""])[0]
        vip = ""
        if volume and issue and pages:
            vip = f"{volume}({issue}):{pages}{('-' + end_page) if end_page else ''}"
        elif volume and pages:
            vip = f"{volume}:{pages}{('-' + end_page) if end_page else ''}"
        doi = (current.get("DO") or [""])[0]
        url = (current.get("UR") or [""])[0]

        records.append(
            {
                "source": source_name,
                "title": title.strip(),
                "authors": authors.strip(),
                "year": year.strip(),
                "journal": journal.strip(),
                "volume_issue_pages": vip.strip(),
                "doi": doi.strip(),
                "pmid": "",
                "source_url": url.strip(),
            }
        )

    for line in content.splitlines():
        s = line.rstrip("\n")
        if not s.strip():
            continue
        if s.startswith("ER"):
            flush_one()
            current = {}
            continue
        if "  -" not in s:
            continue
        key, value = s.split("  -", 1)
        k = key.strip().upper()
        v = value.strip()
        current.setdefault(k, []).append(v)
    flush_one()
    return records


def parse_csv_bytes(file_bytes: bytes, source_name: str) -> list[LiteratureRecord]:
    txt = file_bytes.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(txt))
    out: list[LiteratureRecord] = []
    for row in reader:
        lower = {str(k or "").strip().lower(): str(v or "").strip() for k, v in row.items()}
        title = lower.get("title") or lower.get("article title") or lower.get("document title") or ""
        authors = lower.get("authors") or lower.get("author") or lower.get("creators") or ""
        journal = lower.get("journal") or lower.get("source title") or lower.get("publication") or ""
        year = lower.get("year") or lower.get("publication year") or lower.get("date") or ""
        doi = lower.get("doi") or lower.get("document object identifier (doi)") or ""
        pmid = lower.get("pmid") or lower.get("pubmed id") or ""
        vip = lower.get("volume_issue_pages") or lower.get("volume/issue/pages") or lower.get("pages") or ""
        url = lower.get("url") or lower.get("link") or ""
        if not title:
            continue
        out.append(
            {
                "source": source_name,
                "title": title,
                "authors": _split_authors(authors),
                "year": year,
                "journal": journal,
                "volume_issue_pages": vip,
                "doi": doi,
                "pmid": pmid,
                "source_url": url,
            }
        )
    return out


def parse_import_file(file_name: str, file_bytes: bytes, source_name: str) -> list[LiteratureRecord]:
    ext = Path(file_name).suffix.lower()
    if ext == ".ris":
        txt = file_bytes.decode("utf-8-sig", errors="ignore")
        return _parse_ris_text(txt, source_name=source_name)
    if ext == ".csv":
        return parse_csv_bytes(file_bytes, source_name=source_name)
    raise ValueError("仅支持 RIS 或 CSV 文件导入")
