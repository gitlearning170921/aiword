from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus


_YEAR_RE = re.compile(r"(19|20)\d{2}")
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)


def _build_url(
    *,
    query: str,
    hl: str,
    start: int,
    page_size: int,
    start_year: int | None,
    end_year: int | None,
    sort_by: str,
) -> str:
    url = (
        "https://scholar.google.com/scholar?"
        f"q={quote_plus(query)}&hl={quote_plus(hl)}&as_sdt=0,5"
        f"&num={int(page_size)}&start={max(0, int(start))}"
    )
    if start_year:
        url += f"&as_ylo={int(start_year)}"
    if end_year:
        url += f"&as_yhi={int(end_year)}"
    if sort_by == "date":
        url += "&scisbd=1"
    return url


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _parse_meta(meta: str) -> tuple[str, str, str]:
    """
    粗解析 Scholar 的 gs_a 字段:
    'A Author, B Author - Journal Name, 2021 - publisher'
    """
    text = _clean_text(meta)
    if not text:
        return "", "", ""
    parts = [p.strip() for p in text.split(" - ") if p.strip()]
    left = parts[0] if parts else ""
    right = parts[1] if len(parts) > 1 else ""
    year = ""
    m = _YEAR_RE.search(text)
    if m:
        year = m.group(0)
    journal = right
    if right:
        # 去掉年份后缀，保留期刊主体
        journal = re.sub(r"[,，]?\s*(19|20)\d{2}.*$", "", right).strip(" ,;")
    return left, journal, year


def _extract_doi(*values: str) -> str:
    joined = " ".join(v for v in values if v)
    m = _DOI_RE.search(joined)
    return m.group(0) if m else ""


@dataclass
class CaptureConfig:
    query: str
    output_prefix: Path
    max_results: int
    page_size: int
    start_year: int | None
    end_year: int | None
    hl: str
    sort_by: str
    proxy: str
    slow_mo_ms: int
    wait_after_page_s: float
    headed: bool


def _parse_args() -> CaptureConfig:
    parser = argparse.ArgumentParser(
        description=(
            "用真实浏览器自动翻页抓取 Google Scholar 结果并导出 CSV/JSON。"
            "该脚本不走项目后端爬虫链路，适合排查代理/IP 导致的抓取不稳定。"
        )
    )
    parser.add_argument("--query", required=True, help="检索式")
    parser.add_argument("--output-prefix", default="scholar_capture", help="输出文件前缀")
    parser.add_argument("--max-results", type=int, default=200, help="最大抓取条数")
    parser.add_argument("--page-size", type=int, default=10, choices=[10, 20], help="每页条数")
    parser.add_argument("--start-year", type=int, default=0)
    parser.add_argument("--end-year", type=int, default=0)
    parser.add_argument("--hl", default="zh-CN")
    parser.add_argument("--sort-by", default="relevance", choices=["relevance", "date"])
    parser.add_argument("--proxy", default="", help="代理，如 http://127.0.0.1:7897")
    parser.add_argument("--slow-mo-ms", type=int, default=300)
    parser.add_argument("--wait-after-page-s", type=float, default=6.0)
    parser.add_argument(
        "--headless",
        action="store_true",
        help="无头模式（不推荐，遇验证码无法手动通过）",
    )
    ns = parser.parse_args()
    return CaptureConfig(
        query=(ns.query or "").strip(),
        output_prefix=Path(ns.output_prefix),
        max_results=max(1, min(1000, int(ns.max_results or 200))),
        page_size=int(ns.page_size or 10),
        start_year=int(ns.start_year) if int(ns.start_year or 0) > 0 else None,
        end_year=int(ns.end_year) if int(ns.end_year or 0) > 0 else None,
        hl=(ns.hl or "zh-CN").strip() or "zh-CN",
        sort_by=(ns.sort_by or "relevance").strip().lower(),
        proxy=(ns.proxy or "").strip(),
        slow_mo_ms=max(0, int(ns.slow_mo_ms or 0)),
        wait_after_page_s=max(0.0, float(ns.wait_after_page_s or 0.0)),
        headed=not bool(ns.headless),
    )


def _require_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "缺少 playwright 依赖。请先执行:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        ) from exc
    return sync_playwright


def _collect_cards(page: Any) -> list[dict[str, Any]]:
    return page.evaluate(
        """() => {
          const cards = Array.from(document.querySelectorAll('.gs_or'));
          return cards.map((c, i) => {
            const t = c.querySelector('.gs_rt');
            const a = t ? t.querySelector('a') : null;
            const title = t ? (t.textContent || '').replace(/^\\s*\\[[^\\]]+\\]\\s*/, '').trim() : '';
            const link = a ? (a.href || '').trim() : '';
            const meta = (c.querySelector('.gs_a')?.textContent || '').trim();
            const snippet = (c.querySelector('.gs_rs')?.textContent || '').trim();
            return { rank_in_page: i + 1, title, source_url: link, meta, snippet };
          });
        }"""
    )


def _has_robot_block(page: Any) -> bool:
    text = (page.content() or "").lower()
    return ("unusual traffic" in text) or ("not a robot" in text) or ("/sorry/" in text)


def _dump_output(prefix: Path, records: list[dict[str, Any]]) -> tuple[Path, Path]:
    ts = time.strftime("%Y%m%d_%H%M%S")
    json_path = prefix.with_name(f"{prefix.name}_{ts}.json")
    csv_path = prefix.with_name(f"{prefix.name}_{ts}.csv")
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = [
        "source",
        "title",
        "authors",
        "journal",
        "year",
        "doi",
        "pmid",
        "source_url",
        "meta",
        "snippet",
        "rank",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for rec in records:
            w.writerow({k: rec.get(k, "") for k in fields})
    return json_path, csv_path


def main() -> int:
    cfg = _parse_args()
    if not cfg.query:
        print("query 不能为空", file=sys.stderr)
        return 2
    sync_playwright = _require_playwright()
    start = 0
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    first_url = _build_url(
        query=cfg.query,
        hl=cfg.hl,
        start=start,
        page_size=cfg.page_size,
        start_year=cfg.start_year,
        end_year=cfg.end_year,
        sort_by=cfg.sort_by,
    )
    print(f"[INFO] 打开: {first_url}")
    print("[INFO] 若出现验证码，请在浏览器里手工完成后回到终端按 Enter 继续。")
    with sync_playwright() as p:
        launch_kw: dict[str, Any] = {
            "headless": not cfg.headed,
            "slow_mo": cfg.slow_mo_ms,
        }
        if cfg.proxy:
            launch_kw["proxy"] = {"server": cfg.proxy}
        browser = p.chromium.launch(**launch_kw)
        context = browser.new_context(locale=cfg.hl)
        page = context.new_page()
        page.goto(first_url, wait_until="domcontentloaded", timeout=120000)
        if _has_robot_block(page):
            input("[ACTION] 检测到验证码/流量异常页，完成验证后按 Enter 继续...")
        while len(output) < cfg.max_results:
            page.wait_for_timeout(int((cfg.wait_after_page_s + random.uniform(0.5, 2.5)) * 1000))
            cards = _collect_cards(page)
            if not cards:
                print("[WARN] 当前页没有解析到结果卡片，停止。")
                break
            gain = 0
            for row in cards:
                title = _clean_text(str(row.get("title") or ""))
                link = _clean_text(str(row.get("source_url") or "")).lower()
                key = link or re.sub(r"\W+", "", title.lower())
                if not key or key in seen:
                    continue
                seen.add(key)
                meta = _clean_text(str(row.get("meta") or ""))
                authors, journal, year = _parse_meta(meta)
                snippet = _clean_text(str(row.get("snippet") or ""))
                doi = _extract_doi(title, meta, snippet, link)
                output.append(
                    {
                        "source": "scholar",
                        "title": title,
                        "authors": authors,
                        "journal": journal,
                        "year": year,
                        "doi": doi,
                        "pmid": "",
                        "source_url": link,
                        "meta": meta,
                        "snippet": snippet,
                        "rank": len(output) + 1,
                    }
                )
                gain += 1
                if len(output) >= cfg.max_results:
                    break
            print(f"[INFO] 已抓 {len(output)} 条，本页新增 {gain} 条")
            if len(output) >= cfg.max_results:
                break
            next_btn = page.locator(
                "a[aria-label='Next'], a[aria-label='下一页'], td a span.gs_ico_nav_next"
            ).first
            if next_btn.count() < 1:
                print("[INFO] 未找到下一页，停止。")
                break
            try:
                # 优先点击父级可点击 a，兼容图标 span
                clickable = (
                    next_btn.locator("xpath=ancestor::a[1]").first
                    if next_btn.evaluate("el => el.tagName.toLowerCase()") == "span"
                    else next_btn
                )
                clickable.click(timeout=10000)
            except Exception:
                print("[WARN] 点击下一页失败，停止。")
                break
            if _has_robot_block(page):
                input("[ACTION] 翻页后出现验证码，完成验证后按 Enter 继续...")
        context.close()
        browser.close()
    out_json, out_csv = _dump_output(cfg.output_prefix, output)
    print(f"[DONE] 共抓取 {len(output)} 条")
    print(f"[DONE] JSON: {out_json}")
    print(f"[DONE] CSV : {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
