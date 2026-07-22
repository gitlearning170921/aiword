from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook

from . import LiteratureRecord
from .normalize import build_citation, normalize_text, source_display_label


EXPORT_HEADERS = (
    "Database",
    "Item",
    "Literature",
    "Link",
    "Title",
    "Authors",
    "Journal",
    "Year",
    "DOI/PMID",
    "Source",
)


def _id_column(record: LiteratureRecord) -> str:
    doi = normalize_text(record.get("doi"))
    pmid = normalize_text(record.get("pmid"))
    if doi and pmid:
        return f"{doi} / PMID:{pmid}"
    if doi:
        return doi
    if pmid:
        return f"PMID:{pmid}"
    return ""


def export_records_to_excel(records: list[LiteratureRecord]) -> tuple[bytes, str]:
    wb = Workbook()
    ws = wb.active
    ws.title = "literature"
    ws.append(list(EXPORT_HEADERS))

    counters: dict[str, int] = {}
    for rec in records:
        # database 已是展示标签（normalize_record 生成，如 Google/PUBMED），
        # 不要再套一层 source_display_label，否则 Google→GOOGLE 与列表不一致
        db = normalize_text(rec.get("database")) or source_display_label(rec.get("source"))
        counters[db] = counters.get(db, 0) + 1
        citation = str(rec.get("citation") or "").strip() or build_citation(rec)
        ws.append(
            [
                db,
                f"[{counters[db]}]",
                citation,
                normalize_text(rec.get("source_url")),
                normalize_text(rec.get("title")),
                normalize_text(rec.get("authors")),
                normalize_text(rec.get("journal")),
                normalize_text(rec.get("year")),
                _id_column(rec),
                normalize_text(rec.get("source")),
            ]
        )

    ws.freeze_panes = "A2"
    widths = {
        "A": 12,
        "B": 8,
        "C": 70,
        "D": 40,
        "E": 40,
        "F": 28,
        "G": 22,
        "H": 10,
        "I": 26,
        "J": 12,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return buf.getvalue(), f"Clinical_Literature_Search_Result_{ts}.xlsx"
