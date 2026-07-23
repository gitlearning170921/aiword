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
    "Volume/Issue/Pages",
    "DOI/PMID",
    "Source",
    "选用",
    "重复",
    "无法获取全文",
    "Note",
)


def _vip_note(record: LiteratureRecord) -> str:
    """备注：卷期页缺失、无链接等提示。"""
    notes: list[str] = []
    src = normalize_text(record.get("source")).lower()
    if src in ("scholar", "pubmed") and not normalize_text(record.get("volume_issue_pages")):
        notes.append("卷期页缺失，建议核对原文后手动补充")
    if not normalize_text(record.get("source_url")):
        notes.append("无链接地址")
    return "；".join(notes)


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
        # 强制重建引用并清洗 HTML，避免导出 Literature/Title 残留 span 标签
        citation = normalize_text(build_citation(rec)) or normalize_text(rec.get("citation"))
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
                normalize_text(rec.get("volume_issue_pages")),
                _id_column(rec),
                normalize_text(rec.get("source")),
                "是" if rec.get("selected") else "",
                "是" if rec.get("duplicate") else "",
                "是" if rec.get("no_fulltext") else "",
                _vip_note(rec),
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
        "I": 18,
        "J": 26,
        "K": 12,
        "L": 8,
        "M": 8,
        "N": 12,
        "O": 26,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return buf.getvalue(), f"Clinical_Literature_Search_Result_{ts}.xlsx"
