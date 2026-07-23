from __future__ import annotations

import argparse
import csv
import inspect
import json
import os
import random
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.remote.remote_connection import RemoteConnection
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService

_YEAR_RE = re.compile(r"(19|20)\d{2}")
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)


def _build_url(
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
        journal = re.sub(r"[,，]?\s*(19|20)\d{2}.*$", "", right).strip(" ,;")
    return left, journal, year


def _extract_doi(*values: str) -> str:
    joined = " ".join(v for v in values if v)
    m = _DOI_RE.search(joined)
    return m.group(0) if m else ""


def _robot_block(page_source: str) -> bool:
    t = (page_source or "").lower()
    return ("unusual traffic" in t) or ("not a robot" in t) or ("/sorry/" in t)


def _browser_error_page(page_source: str) -> bool:
    t = (page_source or "").lower()
    return ("err_" in t) or ("this page isn" in t and "working" in t) or ("cannot reach this page" in t)


def _start_from_url(url: str) -> int:
    try:
        q = parse_qs(urlparse(url).query)
        return max(0, int((q.get("start") or ["0"])[0]))
    except Exception:
        return 0


def _goto_with_retry(driver: webdriver.Remote, wait: WebDriverWait, url: str, retries: int = 2) -> bool:
    for i in range(retries + 1):
        try:
            driver.get(url)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gs_r, .gs_or, #gs_ab")))
            return True
        except Exception:
            if i >= retries:
                return False
            time.sleep(2.0 + i * 2.0)
    return False


def _collect_cards(driver: webdriver.Remote) -> list[dict]:
    cards = driver.find_elements(By.CSS_SELECTOR, ".gs_or, .gs_r")
    out: list[dict] = []
    for i, c in enumerate(cards, start=1):
        title = ""
        link = ""
        meta = ""
        snippet = ""
        try:
            rt = c.find_element(By.CSS_SELECTOR, ".gs_rt")
            title = _clean_text(rt.text)
            title = re.sub(r"^\[[^\]]+\]\s*", "", title).strip()
            try:
                a = rt.find_element(By.TAG_NAME, "a")
                link = _clean_text(a.get_attribute("href") or "")
            except NoSuchElementException:
                link = ""
        except NoSuchElementException:
            pass
        try:
            meta = _clean_text(c.find_element(By.CSS_SELECTOR, ".gs_a").text)
        except NoSuchElementException:
            meta = ""
        try:
            snippet = _clean_text(c.find_element(By.CSS_SELECTOR, ".gs_rs").text)
        except NoSuchElementException:
            snippet = ""
        out.append(
            {
                "rank_in_page": i,
                "title": title,
                "source_url": link,
                "meta": meta,
                "snippet": snippet,
            }
        )
    return out


def _dump(prefix: Path, rows: list[dict]) -> tuple[Path, Path]:
    ts = time.strftime("%Y%m%d_%H%M%S")
    json_path = prefix.with_name(f"{prefix.name}_{ts}.json")
    csv_path = prefix.with_name(f"{prefix.name}_{ts}.csv")
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
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
        for rec in rows:
            w.writerow({k: rec.get(k, "") for k in fields})
    return json_path, csv_path


def _detect_edge_binary() -> str:
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return ""


def _build_driver(browser: str, proxy: str, headless: bool, driver_path: str) -> webdriver.Remote:
    if browser == "edge":
        edge_args: list[str] = []
        if headless:
            edge_args.append("--headless=new")
        edge_args.append("--disable-blink-features=AutomationControlled")
        edge_args.append("--lang=zh-CN")
        if proxy:
            edge_args.append(f"--proxy-server={proxy}")
        edge_driver = (driver_path or "").strip() or "msedgedriver"
        if (driver_path or "").strip() and not os.path.exists(edge_driver):
            raise FileNotFoundError(f"未找到 EdgeDriver: {edge_driver}")

        # Selenium 4+: 原生 Edge(service, options)
        try:
            edge_sig = inspect.signature(webdriver.Edge)
            if "service" in edge_sig.parameters:
                opts = EdgeOptions()
                if hasattr(opts, "add_argument"):
                    for a in edge_args:
                        opts.add_argument(a)
                else:
                    opts.set_capability("ms:edgeOptions", {"args": edge_args})
                service = EdgeService(executable_path=edge_driver)
                return webdriver.Edge(service=service, options=opts)
        except Exception:
            pass

        # Selenium 3.x 回退：优先使用旧版 webdriver.Edge(executable_path, capabilities)
        # 并显式传 ms:edgeOptions，避免 "No matching capabilities found"。
        edge_caps = {
            "browserName": "MicrosoftEdge",
            "ms:edgeOptions": {"args": edge_args},
        }
        try:
            return webdriver.Edge(executable_path=edge_driver, capabilities=edge_caps)
        except TypeError:
            # 极老接口兼容（位置参数）
            return webdriver.Edge(edge_driver, edge_caps)
        except Exception:
            # 最后兜底：走 Chrome 协议 + Edge binary
            copt = ChromeOptions()
            for a in edge_args:
                copt.add_argument(a)
            edge_bin = _detect_edge_binary()
            if edge_bin:
                copt.binary_location = edge_bin
            caps = copt.to_capabilities()
            caps["browserName"] = "MicrosoftEdge"
            caps["ms:edgeOptions"] = {"args": edge_args}
            try:
                return webdriver.Chrome(
                    executable_path=edge_driver,
                    options=copt,
                    desired_capabilities=caps,
                )
            except TypeError:
                return webdriver.Chrome(
                    executable_path=edge_driver,
                    chrome_options=copt,
                    desired_capabilities=caps,
                )

    opts = ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=zh-CN")
    if proxy:
        opts.add_argument(f"--proxy-server={proxy}")
    chrome_driver = (driver_path or "").strip() or "chromedriver"
    if (driver_path or "").strip() and not os.path.exists(chrome_driver):
        raise FileNotFoundError(f"未找到 ChromeDriver: {chrome_driver}")
    try:
        return webdriver.Chrome(executable_path=chrome_driver, options=opts)
    except TypeError:
        return webdriver.Chrome(executable_path=chrome_driver, chrome_options=opts)


def main() -> int:
    ap = argparse.ArgumentParser(description="Selenium 浏览器自动抓取 Google Scholar 并导出 CSV/JSON")
    ap.add_argument("--query", required=True)
    ap.add_argument("--output-prefix", default="scholar_capture")
    ap.add_argument("--max-results", type=int, default=200)
    ap.add_argument("--page-size", type=int, default=10, choices=[10, 20])
    ap.add_argument("--start-year", type=int, default=0)
    ap.add_argument("--end-year", type=int, default=0)
    ap.add_argument("--hl", default="zh-CN")
    ap.add_argument("--sort-by", default="relevance", choices=["relevance", "date"])
    ap.add_argument("--proxy", default="")
    ap.add_argument("--browser", default="edge", choices=["edge", "chrome"])
    ap.add_argument("--driver-path", default="", help="msedgedriver/chromedriver 本地路径（可选）")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--wait-after-page-s", type=float, default=6.0)
    ns = ap.parse_args()

    query = (ns.query or "").strip()
    if not query:
        print("query 不能为空", file=sys.stderr)
        return 2

    driver = None
    try:
        # 兼容 selenium 3.141 + urllib3 2.x：不给默认 sentinel timeout，避免连接报错
        try:
            RemoteConnection.set_timeout(60)
        except Exception:
            pass
        driver = _build_driver(
            browser=ns.browser,
            proxy=(ns.proxy or "").strip(),
            headless=bool(ns.headless),
            driver_path=(ns.driver_path or "").strip(),
        )
        driver.set_page_load_timeout(120)
        wait = WebDriverWait(driver, 30)
        start = 0
        target = max(1, min(1000, int(ns.max_results or 200)))
        page_size = int(ns.page_size or 10)
        sy = int(ns.start_year) if int(ns.start_year or 0) > 0 else None
        ey = int(ns.end_year) if int(ns.end_year or 0) > 0 else None
        url = _build_url(query, ns.hl, start, page_size, sy, ey, ns.sort_by)
        print(f"[INFO] 打开: {url}")
        if not _goto_with_retry(driver, wait, url, retries=2):
            print("[ERROR] 首页加载失败，请检查代理/节点连通性。", file=sys.stderr)
            return 1
        if _robot_block(driver.page_source):
            input("[ACTION] 检测到验证码/流量异常，手工完成后按 Enter 继续...")

        seen: set[str] = set()
        rows: list[dict] = []
        no_gain_pages = 0
        current_start = 0
        while len(rows) < target:
            time.sleep(float(ns.wait_after_page_s) + random.uniform(0.5, 2.0))
            cards = _collect_cards(driver)
            current_start = _start_from_url(driver.current_url)
            print(f"[DEBUG] 当前 URL: {driver.current_url}")
            print(f"[DEBUG] 本页解析到卡片: {len(cards)}")
            if not cards:
                if _browser_error_page(driver.page_source):
                    fallback = _build_url(query, ns.hl, current_start, page_size, sy, ey, ns.sort_by)
                    print(f"[WARN] 检测到页面错误，重试当前页: {fallback}")
                    if _goto_with_retry(driver, wait, fallback, retries=2):
                        continue
                print("[WARN] 本页没有解析到结果，停止。")
                break
            gain = 0
            for c in cards:
                title = _clean_text(c.get("title", ""))
                link = _clean_text(c.get("source_url", "")).lower()
                key = link or re.sub(r"\W+", "", title.lower())
                if not key or key in seen:
                    continue
                seen.add(key)
                meta = _clean_text(c.get("meta", ""))
                snippet = _clean_text(c.get("snippet", ""))
                authors, journal, year = _parse_meta(meta)
                doi = _extract_doi(title, meta, snippet, link)
                rows.append(
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
                        "rank": len(rows) + 1,
                    }
                )
                gain += 1
                if len(rows) >= target:
                    break
            print(f"[INFO] 已抓 {len(rows)} 条，本页新增 {gain} 条")
            if gain == 0:
                no_gain_pages += 1
            else:
                no_gain_pages = 0
            if no_gain_pages >= 2:
                print("[WARN] 连续 2 页无新增，停止（当前会话可能被软封锁或结果重叠）。")
                break
            if len(rows) >= target:
                break

            # 下一页（兼容英文/中文）
            next_clicked = False
            for sel in [
                "a[aria-label='Next']",
                "a[aria-label='下一页']",
                "button[aria-label='Next']",
                "button[aria-label='下一页']",
                "a#pnnext",
                "td a span.gs_ico_nav_next",
            ]:
                elems = driver.find_elements(By.CSS_SELECTOR, sel)
                if not elems:
                    continue
                try:
                    e = elems[0]
                    old_url = driver.current_url
                    tag = e.tag_name.lower()
                    if tag == "span":
                        driver.execute_script("arguments[0].closest('a').click();", e)
                    elif tag == "button":
                        driver.execute_script("arguments[0].click();", e)
                    else:
                        driver.execute_script("arguments[0].click();", e)
                    # 等待翻页，避免还在旧页就进入下一轮导致误判
                    wait.until(lambda d: d.current_url != old_url or _robot_block(d.page_source))
                    next_clicked = True
                    break
                except Exception:
                    continue
            if not next_clicked:
                # 按 start 参数强制跳页，不依赖按钮形态（第 3 页报错时常见）
                fallback_start = current_start + page_size
                fallback_url = _build_url(query, ns.hl, fallback_start, page_size, sy, ey, ns.sort_by)
                print(f"[WARN] 下一页按钮不可用，改用直接跳页: start={fallback_start}")
                if not _goto_with_retry(driver, wait, fallback_url, retries=2):
                    print("[INFO] 直接跳页也失败，停止。")
                    break
            if _robot_block(driver.page_source):
                input("[ACTION] 翻页后出现验证码，手工完成后按 Enter 继续...")

        out_json, out_csv = _dump(Path(ns.output_prefix), rows)
        print(f"[DONE] 共抓取 {len(rows)} 条")
        print(f"[DONE] JSON: {out_json}")
        print(f"[DONE] CSV : {out_csv}")
        return 0
    except FileNotFoundError as exc:
        print("[ERROR] 驱动文件不存在：", exc, file=sys.stderr)
        print("[HINT] 请下载与浏览器主版本一致的驱动，例如 Edge 150.x 对应 msedgedriver 150.x。", file=sys.stderr)
        return 1
    except WebDriverException as exc:
        print("[ERROR] 启动浏览器失败：", exc, file=sys.stderr)
        print(
            "[HINT] 可尝试显式指定驱动路径，例如 --browser edge --driver-path C:\\tools\\msedgedriver.exe",
            file=sys.stderr,
        )
        return 1
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())

