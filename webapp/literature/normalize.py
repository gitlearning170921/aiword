from __future__ import annotations

import html
import re
from typing import Iterable

from . import LiteratureRecord


_MULTISPACE_RE = re.compile(r"\s+")
# 剥掉 Scholar 等来源残留的 HTML（含损坏闭合标签如 </SPAN中>）
_HTML_TAG_RE = re.compile(r"<[^<>]*>", re.I)
# 剥掉标签剥离后仍残留的 style/font-variant 噪声
_STYLE_NOISE_RE = re.compile(
    r"""(?ix)
    style\s*=\s*["'“”][^"'“”]*["'“”]
    | font-variant\s*[：:]\s*small-?caps
    """
)
_DOI_RE = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)


SOURCE_LABELS = {
    "pubmed": "PUBMED",
    "scholar": "Google",
    "embase": "EMBASE",
    "cochrane": "Cochrane",
}


def normalize_text(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    # 全角尖括号统一成半角，避免 ＜span＞ 剥不掉
    text = text.replace("＜", "<").replace("＞", ">")
    # 先实体解码再剥标签：文献 citation 常存成 &lt;span...&gt;OSA&lt;/span&gt;，
    # 只剥原始 <tag> 清不掉；再剥一轮以防双重转义。
    for _ in range(3):
        try:
            text = html.unescape(text)
        except Exception:
            pass
        text = text.replace("＜", "<").replace("＞", ">")
        if "<" in text:
            text = _HTML_TAG_RE.sub(" ", text)
        else:
            break
    # 再清一层残留 style / font-variant 噪声（标签损坏时常见）
    text = _STYLE_NOISE_RE.sub(" ", text)
    # 解码失败的替换字符统一成省略号，避免展示/导出出现「Journal of Medical ��」
    if "\ufffd" in text:
        text = re.sub(r"\ufffd+", "…", text)
    return _MULTISPACE_RE.sub(" ", text).strip()


def normalize_authors(authors: str | Iterable[str] | None) -> str:
    if authors is None:
        return ""
    if isinstance(authors, str):
        text = normalize_text(authors)
        text = text.replace(";", ",")
        return normalize_text(text)
    parts = [normalize_text(p) for p in authors if normalize_text(p)]
    return ", ".join(parts)


def normalize_year(value: str | int | None) -> str:
    raw = normalize_text(str(value or ""))
    if not raw:
        return ""
    m = re.search(r"(19|20)\d{2}", raw)
    if m:
        return m.group(0)
    return raw[:16]


def normalize_doi(value: str | None) -> str:
    raw = normalize_text(value)
    if not raw:
        return ""
    m = _DOI_RE.search(raw)
    if not m:
        return raw.lower()
    return m.group(1).rstrip(".;,)").lower()


def normalize_title(value: str | None) -> str:
    title = normalize_text(value)
    if not title:
        return ""
    title = title.strip(" .;")
    return title


def source_display_label(source: str | None) -> str:
    key = normalize_text(source).lower()
    return SOURCE_LABELS.get(key, key.upper() or "UNKNOWN")


def build_source_info(record: LiteratureRecord) -> str:
    journal = normalize_text(record.get("journal"))
    year = normalize_year(record.get("year"))
    vip = normalize_text(record.get("volume_issue_pages"))
    source = normalize_text(record.get("source")).lower() or "unknown"
    doi = normalize_doi(record.get("doi"))

    parts: list[str] = []
    if journal:
        parts.append(journal)
    if year:
        parts.append(year)
    if vip:
        parts.append(vip)
    if parts:
        if doi:
            return f'{"; ".join(parts)}; doi:{doi}'
        return "; ".join(parts)

    if year:
        return f"{source}; {year}"
    return source


def build_citation(record: LiteratureRecord) -> str:
    """对齐 Clinical Literature Search Result.docx 的 Literature 列（Vancouver 风格）。"""
    authors = normalize_authors(record.get("authors"))
    title = normalize_title(record.get("title"))
    journal = normalize_text(record.get("journal"))
    pub_date = normalize_text(record.get("pub_date")) or normalize_year(record.get("year"))
    vip = normalize_text(record.get("volume_issue_pages"))
    doi = normalize_doi(record.get("doi"))
    source = normalize_text(record.get("source")).lower()

    # Embase / Cochrane 导入常见为多行摘要式，优先保留已有 citation
    existing = normalize_text(record.get("citation"))
    if existing and source in ("embase", "cochrane"):
        return existing

    if source == "scholar":
        # 字段已补全时用 Vancouver；仍截断时退回多行摘要
        if journal and not ("…" in journal or "..." in journal):
            head = ""
            if authors and title:
                head = f"{authors}. {title}."
            elif title:
                head = f"{title}."
            mid_parts: list[str] = [journal]
            if pub_date and vip:
                mid_parts.append(f"{pub_date};{vip}")
            elif pub_date:
                mid_parts.append(pub_date)
            mid = ". ".join(mid_parts)
            if mid and not mid.endswith("."):
                mid += "."
            citation = " ".join(x for x in (head, mid) if x).strip()
            if doi:
                if citation and not citation.endswith("."):
                    citation += "."
                citation = f"{citation} doi: {doi}.".strip()
            return citation
        lines: list[str] = []
        if title:
            lines.append(title)
        if authors:
            lines.append(f"by {authors}")
        meta_bits = [x for x in (journal, pub_date) if x]
        if meta_bits:
            lines.append(", ".join(meta_bits))
        if doi:
            lines.append(f"doi: {doi}")
        return "\n".join(lines).strip()

    # PubMed / 默认：Authors. Title. Journal. Date;vip. doi: xx.
    head = ""
    if authors and title:
        head = f"{authors}. {title}."
    elif title:
        head = f"{title}."
    elif authors:
        head = f"{authors}."

    mid_parts: list[str] = []
    if journal:
        mid_parts.append(journal)
    if pub_date and vip:
        mid_parts.append(f"{pub_date};{vip}")
    elif pub_date:
        mid_parts.append(pub_date)
    elif vip:
        mid_parts.append(vip)
    mid = ". ".join(mid_parts)
    if mid and not mid.endswith("."):
        mid += "."

    chunks = [c for c in (head, mid) if c]
    citation = " ".join(chunks).strip()
    if doi:
        if citation and not citation.endswith("."):
            citation += "."
        citation = f"{citation} doi: {doi}.".strip()
    return citation


def _as_bool_mark(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value or "").strip().lower()
    return s in ("1", "true", "yes", "y", "是", "选用", "重复")


def normalize_record(record: LiteratureRecord) -> LiteratureRecord:
    normalized: LiteratureRecord = {
        "source": normalize_text(record.get("source")).lower(),
        "title": normalize_title(record.get("title")),
        # 摘要字段：优先 abstract，兼容外部源常见的 snippet 命名
        "abstract": normalize_text(record.get("abstract") or record.get("snippet")),
        "authors": normalize_authors(record.get("authors")),
        "year": normalize_year(record.get("year")),
        "pub_date": normalize_text(record.get("pub_date")),
        "journal": normalize_text(record.get("journal")),
        "volume_issue_pages": normalize_text(record.get("volume_issue_pages")),
        "doi": normalize_doi(record.get("doi")),
        "pmid": normalize_text(record.get("pmid")),
        "source_url": normalize_text(record.get("source_url")),
        # 人工标记：选用 / 重复 / 无法获取全文（独立字段，归一化时保留）
        "selected": _as_bool_mark(record.get("selected")),
        "duplicate": _as_bool_mark(record.get("duplicate")),
        "no_fulltext": _as_bool_mark(record.get("no_fulltext")),
    }
    if not normalized["pub_date"] and normalized["year"]:
        normalized["pub_date"] = normalized["year"]
    normalized["source_info"] = build_source_info(normalized)
    # 传入原始 citation，供 Embase/Cochrane 保留；build_citation 内部会再 normalize_text 清洗
    normalized["citation"] = build_citation(
        {**normalized, "citation": record.get("citation") or ""}
    )
    # 导出/展示最终再洗一遍，避免旧 citation 里残留 HTML
    normalized["citation"] = normalize_text(normalized.get("citation"))
    normalized["database"] = source_display_label(normalized.get("source"))
    return normalized
