from __future__ import annotations

import html
import random
import re
import time
from urllib.parse import quote_plus

from .. import LiteratureRecord
from ..http_client import literature_get


_ENTRY_RE = re.compile(r'<div class="gs_r gs_or gs_scl"[^>]*>(.*?)</div>\s*</div>', re.S)
_TITLE_RE = re.compile(r'<h3 class="gs_rt"[^>]*>(.*?)</h3>', re.S)
_LINK_RE = re.compile(r'<a href="([^"]+)"', re.S)
_META_RE = re.compile(r'<div class="gs_a"[^>]*>(.*?)</div>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_YEAR_RE = re.compile(r"(19|20)\d{2}")


def _clean_html_text(value: str) -> str:
    text = _TAG_RE.sub(" ", value or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_authors_year(meta: str) -> tuple[str, str]:
    plain = _clean_html_text(meta)
    year = ""
    m = _YEAR_RE.search(plain)
    if m:
        year = m.group(0)
    author_part = plain.split("-")[0].strip() if "-" in plain else plain
    return author_part, year


def _extract_journal(meta: str) -> str:
    plain = _clean_html_text(meta)
    parts = [p.strip() for p in plain.split("-") if p.strip()]
    if len(parts) >= 2:
        return parts[1]
    return ""


def _parse_entries(html_text: str, max_results: int) -> list[LiteratureRecord]:
    records: list[LiteratureRecord] = []
    for block in _ENTRY_RE.findall(html_text):
        tmatch = _TITLE_RE.search(block)
        if not tmatch:
            continue
        title_html = tmatch.group(1)
        lmatch = _LINK_RE.search(title_html)
        title = _clean_html_text(title_html)
        meta_match = _META_RE.search(block)
        meta = meta_match.group(1) if meta_match else ""
        authors, year = _extract_authors_year(meta)
        rec: LiteratureRecord = {
            "source": "scholar",
            "title": title,
            "authors": authors,
            "year": year,
            "journal": _extract_journal(meta),
            "volume_issue_pages": "",
            "doi": "",
            "pmid": "",
            "source_url": html.unescape(lmatch.group(1)).strip() if lmatch else "",
        }
        records.append(rec)
        if len(records) >= max_results:
            break
    return records


def search_scholar(
    *,
    query: str,
    start_year: int | None = None,
    end_year: int | None = None,
    max_results: int = 30,
    timeout_seconds: int = 25,
    request_interval_seconds: float = 1.2,
) -> list[LiteratureRecord]:
    q = (query or "").strip()
    if not q:
        return []

    count = max(1, min(20, int(max_results)))
    url = (
        "https://scholar.google.com/scholar?"
        f"q={quote_plus(q)}&hl=en&as_sdt=0,5&num={count}"
    )
    if start_year:
        url += f"&as_ylo={int(start_year)}"
    if end_year:
        url += f"&as_yhi={int(end_year)}"

    # Scholar 封控严格，保留轻量限速与抖动，减少短时连续请求被拦截概率。
    time.sleep(max(0.1, request_interval_seconds + random.uniform(0.0, 0.5)))
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    # 禁用系统坏代理（常见 Clash ProxyError/SSLEOF），优先直连
    resp = literature_get(url, headers=headers, timeout=timeout_seconds)
    html_text = resp.text or ""
    if "captcha" in html_text.lower() or "please show you're not a robot" in html_text.lower():
        raise RuntimeError(
            "Google Scholar 返回人机验证页，当前 IP 可能被限流；请稍后重试、降低频率，或改用 RIS/CSV 导入。"
        )
    records = _parse_entries(html_text, max_results=count)
    if not records and html_text.strip():
        # 页面结构变更或空结果：给可读提示，避免静默 0 条
        if "gs_r" not in html_text and "gs_rt" not in html_text:
            raise RuntimeError(
                "Google Scholar 页面未能解析到结果（可能被拦截或页面结构变化）。请改用导入或稍后重试。"
            )
    return records
