from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import unescape
from typing import Any, Optional
from urllib.parse import quote, urlparse

import requests

from webapp import db
from webapp.models import (
    ProjectVersionRecord,
    VersionTaskGenerationFeedback,
    VersionTaskGenerationJob,
    now_local,
)

VERSION_RE = re.compile(r"^[Vv]?\s*(\d+)\.(\d+)\.(\d+)\.(\d+)\s*$")
DATE_PATTERNS = (
    re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b"),
    re.compile(r"\b(20\d{2})年(\d{1,2})月(\d{1,2})日\b"),
)
_DDG_URL_TEMPLATES = (
    "https://html.duckduckgo.com/html/?q={query}",
    "https://lite.duckduckgo.com/lite/?q={query}",
)


@dataclass(frozen=True)
class ParsedVersion:
    raw: str
    normalized: str
    x: int
    y: int
    z: int
    b: int


from .version_task_rules import (
    catalogs_for_dominant,
    load_version_task_rules,
    process_branch_label,
)

_RULE_META = load_version_task_rules()
RULE_BASIS_NOTE = str(_RULE_META.get("ruleBasis") or "")
RULE_SOURCE = str(_RULE_META.get("ruleSource") or "")


def parse_version(raw: str) -> ParsedVersion:
    text = (raw or "").strip()
    m = VERSION_RE.match(text)
    if not m:
        raise ValueError(f"版本号格式错误：{raw}（应为 X.Y.Z.B）")
    x, y, z, b = [int(m.group(i)) for i in range(1, 5)]
    return ParsedVersion(raw=text, normalized=f"{x}.{y}.{z}.{b}", x=x, y=y, z=z, b=b)


def parse_version_chain(
    from_version: str,
    to_version: str,
    intermediate_versions: Optional[list[str]] = None,
) -> list[ParsedVersion]:
    chain_raw = [from_version]
    for item in intermediate_versions or []:
        s = (item or "").strip()
        if s:
            chain_raw.append(s)
    chain_raw.append(to_version)
    parsed: list[ParsedVersion] = [parse_version(v) for v in chain_raw]
    return parsed


def dominant_change(prev_v: ParsedVersion, next_v: ParsedVersion) -> str:
    if next_v.x != prev_v.x:
        return "X"
    if next_v.y != prev_v.y:
        return "Y"
    if next_v.z != prev_v.z:
        return "Z"
    if next_v.b != prev_v.b:
        return "B"
    return "NONE"


def normalize_version_release_dates(
    chain: list[ParsedVersion],
    raw_dates: Optional[dict[str, Any]],
) -> dict[str, str]:
    if not isinstance(raw_dates, dict):
        raise ValueError("versionReleaseDates 必须为对象")
    out: dict[str, str] = {}
    missing: list[str] = []
    for version in chain:
        key = version.normalized
        value = str(raw_dates.get(key) or raw_dates.get(version.raw) or "").strip()
        if not value:
            missing.append(key)
            continue
        out[key] = _fmt_date(_parse_iso_date(value))
    if missing:
        raise ValueError(f"以下版本缺少发布时间：{', '.join(missing)}")
    return out


def build_transitions(chain: list[ParsedVersion]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx in range(len(chain) - 1):
        left = chain[idx]
        right = chain[idx + 1]
        change = dominant_change(left, right)
        out.append(
            {
                "fromVersion": left.normalized,
                "toVersion": right.normalized,
                "dominantChange": change,
                "changedSegments": {
                    "x": left.x != right.x,
                    "y": left.y != right.y,
                    "z": left.z != right.z,
                    "b": left.b != right.b,
                },
            }
        )
    return out


def _parse_iso_date(raw: str) -> date:
    value = (raw or "").strip()
    if not value:
        raise ValueError("发布时间不能为空")
    return datetime.strptime(value, "%Y-%m-%d").date()


def _fmt_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _merge_generated_item(target: dict[str, Any], patch: dict[str, Any]) -> None:
    allow_keys = {
        "fileName",
        "taskType",
        "author",
        "belongingModule",
        "notes",
        "dueDate",
        "documentDisplayDate",
        "targetVersion",
        "fileVersion",
        "registrationVersion",
    }
    for key in allow_keys:
        if key in patch:
            target[key] = patch[key]


def _task_identity(item: dict[str, Any]) -> tuple[str, str]:
    return (
        str(item.get("fileName") or "").strip().casefold(),
        str(item.get("taskType") or "").strip().casefold(),
    )


def apply_feedback_rules(
    generated_items: list[dict[str, Any]],
    feedback_rows: list[VersionTaskGenerationFeedback],
) -> tuple[list[dict[str, Any]], int]:
    items = [dict(x) for x in generated_items]
    hit = 0
    for row in feedback_rows:
        kind = (row.adjust_type or "").strip().lower()
        original = row.original_item_json if isinstance(row.original_item_json, dict) else {}
        adjusted = row.adjusted_item_json if isinstance(row.adjusted_item_json, dict) else {}
        identity = _task_identity(original)
        if kind == "add":
            candidate = dict(adjusted)
            if candidate and _task_identity(candidate) not in {_task_identity(x) for x in items}:
                items.append(candidate)
                hit += 1
            continue
        idx = next((i for i, x in enumerate(items) if _task_identity(x) == identity), None)
        if idx is None:
            continue
        if kind == "delete":
            del items[idx]
            hit += 1
            continue
        if kind in {"update", "replace"}:
            _merge_generated_item(items[idx], adjusted)
            hit += 1
    return items, hit


def _task_dedupe_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("taskKey") or item.get("fileName") or "").strip().casefold(),
        str(item.get("fileVersion") or "").strip().casefold(),
        str(item.get("taskType") or "").strip().casefold(),
    )


def generate_task_preview(
    *,
    from_version: str,
    to_version: str,
    intermediate_versions: Optional[list[str]],
    version_release_dates: dict[str, Any],
    feedback_rows: Optional[list[VersionTaskGenerationFeedback]] = None,
) -> dict[str, Any]:
    chain = parse_version_chain(from_version, to_version, intermediate_versions or [])
    release_dates = normalize_version_release_dates(chain, version_release_dates)
    transitions = build_transitions(chain)
    touched_changes = {
        t["dominantChange"] for t in transitions if t["dominantChange"] in {"X", "Y", "Z", "B"}
    }

    items: list[dict[str, Any]] = []
    route_by_version: dict[str, dict[str, str]] = {}
    for transition in transitions:
        dominant = transition["dominantChange"]
        if dominant not in {"X", "Y", "Z", "B"}:
            continue
        target_version = str(transition["toVersion"])
        route, catalog = catalogs_for_dominant(dominant)
        branch = route["processBranch"]
        route_by_version[target_version] = route
        transition["chapter"] = route["chapter"]
        transition["processBranch"] = branch
        transition["processBranchLabel"] = route.get("label") or process_branch_label(branch)
        anchor_date = _parse_iso_date(release_dates[target_version])
        for task in catalog:
            if dominant not in set(task.get("triggers") or set()):
                continue
            due = anchor_date + timedelta(days=int(task.get("phaseOffsetDays") or 0))
            task_branch = str(task.get("processBranch") or "")
            task_chapter = str(task.get("chapter") or route["chapter"])
            items.append(
                {
                    "taskKey": task["taskKey"],
                    "fileName": task["fileName"],
                    "taskType": task["taskType"],
                    "author": task["author"],
                    "belongingModule": task["belongingModule"],
                    "dueDate": _fmt_date(due),
                    "notes": task["reason"],
                    "fileVersion": target_version,
                    "registrationVersion": target_version,
                    "documentDisplayDate": _fmt_date(anchor_date),
                    "targetVersion": target_version,
                    "triggeredBy": [dominant],
                    "transition": f"{transition['fromVersion']} -> {transition['toVersion']}",
                    "chapter": task_chapter,
                    "processBranch": task_branch or branch,
                    "processBranchLabel": process_branch_label(task_branch or branch),
                    "ruleRef": task.get("ruleRef") or "YY-IW-020",
                    "archiveFrequency": task.get("archiveFrequency") or "",
                }
            )

    items_by_id: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in items:
        key = _task_dedupe_key(item)
        if key not in items_by_id:
            items_by_id[key] = item
            continue
        existing = items_by_id[key]
        merged_triggers = sorted(
            set((existing.get("triggeredBy") or []) + (item.get("triggeredBy") or []))
        )
        existing["triggeredBy"] = merged_triggers
        # 保留更高优先级备注（流程任务优先于纯归档重复键）
        if str(item.get("taskType") or "").endswith("流程") and not str(
            existing.get("taskType") or ""
        ).endswith("流程"):
            existing.update({k: item[k] for k in item if k != "triggeredBy"})
            existing["triggeredBy"] = merged_triggers
    deduped = list(items_by_id.values())
    deduped.sort(key=lambda x: (x.get("dueDate") or "", x.get("fileName") or ""))

    feedback_hit_count = 0
    if feedback_rows:
        deduped, feedback_hit_count = apply_feedback_rules(deduped, feedback_rows)

    if intermediate_versions:
        note = "已按提供的中间版本链路逐段推断触发规则。"
    else:
        note = "未提供中间版本，已按 from->to 单跳推断触发规则。"
    branch_summary = "；".join(
        f"{ver}:{r.get('label') or process_branch_label(r.get('processBranch') or '')}"
        for ver, r in sorted(route_by_version.items())
    )
    note = f"{RULE_BASIS_NOTE} {note} 路由：{branch_summary or '无'}。"
    note += (
        " 另请对照公司「发补记录」中同一注册国家与注册类别、且发补日期不晚于今日的历史意见"
        "（含未完成），补充相关文档/章节的复核与整改任务。"
    )

    return {
        "fromVersion": chain[0].normalized,
        "toVersion": chain[-1].normalized,
        "versionChain": [x.normalized for x in chain],
        "versionReleaseDates": release_dates,
        "transitions": transitions,
        "dominantChanges": sorted(list(touched_changes)),
        "processBranches": [
            {
                "version": ver,
                "chapter": r.get("chapter") or "",
                "branch": r.get("processBranch") or "",
                "label": r.get("label") or process_branch_label(r.get("processBranch") or ""),
            }
            for ver, r in sorted(route_by_version.items())
        ],
        "releaseDate": release_dates[chain[-1].normalized],
        "items": deduped,
        "note": note,
        "ruleBasis": RULE_BASIS_NOTE,
        "ruleSource": RULE_SOURCE,
        "feedbackHitCount": feedback_hit_count,
    }


def _safe_date(y: int, m: int, d: int) -> Optional[str]:
    try:
        return _fmt_date(date(y, m, d))
    except Exception:
        return None


def _extract_dates(text: str) -> list[str]:
    out: list[str] = []
    for pattern in DATE_PATTERNS:
        for m in pattern.finditer(text or ""):
            y, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
            parsed = _safe_date(y, mm, dd)
            if parsed:
                out.append(parsed)
    seen = set()
    uniq = []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq


def _parse_duckduckgo_html(html: str) -> tuple[list[dict[str, str]], str]:
    patterns: list[tuple[str, re.Pattern[str]]] = [
        (
            "primary",
            re.compile(
                r'<a[^>]*class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
                r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
                re.S,
            ),
        ),
        (
            "fallback_class",
            re.compile(
                r'<a[^>]*class="[^"]*result[^"]*"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
                re.S,
            ),
        ),
    ]
    out: list[dict[str, str]] = []
    parser = "none"
    for parser_name, block_re in patterns:
        for m in block_re.finditer(html):
            href = unescape(re.sub(r"\s+", " ", m.group("href") or "").strip())
            title = unescape(re.sub(r"<.*?>", "", m.group("title") or "").strip())
            snippet = ""
            if "snippet" in m.groupdict():
                snippet = unescape(re.sub(r"<.*?>", "", m.group("snippet") or "").strip())
            if not href:
                continue
            out.append({"url": href, "title": title, "snippet": snippet})
            if len(out) >= 10:
                break
        if out:
            parser = parser_name
            break
    if not out:
        link_re = re.compile(r'href="(https?://[^"]+)"[^>]*>([^<]{4,120})<', re.I)
        for m in link_re.finditer(html):
            href = unescape(m.group(1).strip())
            title = unescape(re.sub(r"<.*?>", "", m.group(2) or "").strip())
            if "duckduckgo.com" in href:
                continue
            out.append({"url": href, "title": title, "snippet": ""})
            if len(out) >= 8:
                break
        if out:
            parser = "link_fallback"
    return out, parser


def _normalize_proxy_url(proxy: str) -> str:
    """本机代理写成 https://127.0.0.1:端口 时常触发 ProxyError/SSLEOF，归一为 http://。"""
    text = (proxy or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        return text
    host = (parsed.hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"} and (parsed.scheme or "").lower() == "https":
        netloc = parsed.netloc or f"{host}:{parsed.port or 7890}"
        return f"http://{netloc}"
    return text


def _resolve_local_search_proxy() -> Optional[str]:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        val = _normalize_proxy_url(os.environ.get(key) or "")
        if val:
            return val
    return None


def _is_proxy_or_ssl_error(exc: BaseException) -> bool:
    lowered = (str(exc) or "").lower()
    return any(
        key in lowered
        for key in (
            "proxyerror",
            "unable to connect to proxy",
            "ssleoferror",
            "eof occurred in violation of protocol",
            "ssl",
            "certificate",
            "proxy",
        )
    )


def _duckduckgo_search_with_diagnostics(query: str, timeout: float = 12.0) -> tuple[list[dict[str, str]], dict[str, Any]]:
    urls = [tpl.format(query=quote(query)) for tpl in _DDG_URL_TEMPLATES]
    proxy = _resolve_local_search_proxy()
    diagnostics: dict[str, Any] = {
        "url": urls[0] if urls else "",
        "httpStatus": None,
        "htmlBytes": 0,
        "parser": "none",
        "rawHits": 0,
        "networkError": None,
        "durationMs": 0,
        "proxyConfigured": bool(proxy),
        "proxyNormalized": proxy or "",
        "attempts": [],
    }
    started = time.time()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    attempts: list[dict[str, Any]] = []
    if proxy:
        attempts.append({"proxies": {"http": proxy, "https": proxy}, "verify": True, "label": "proxy"})
        attempts.append({"proxies": {"http": proxy, "https": proxy}, "verify": False, "label": "proxy_insecure"})
    # 关闭 trust_env，避免系统坏代理反复注入；失败后再直连
    attempts.append({"proxies": {}, "verify": True, "label": "direct"})
    attempts.append({"proxies": {}, "verify": False, "label": "direct_insecure"})

    html = ""
    last_err: Optional[str] = None
    for url in urls:
        for attempt in attempts:
            label = str(attempt["label"])
            try:
                with requests.Session() as sess:
                    sess.trust_env = False
                    resp = sess.get(
                        url,
                        headers=headers,
                        timeout=timeout,
                        proxies=attempt.get("proxies") or {},
                        verify=bool(attempt.get("verify")),
                    )
                diagnostics["httpStatus"] = resp.status_code
                resp.raise_for_status()
                html = resp.text
                diagnostics["url"] = url
                diagnostics["attemptUsed"] = label
                diagnostics["attempts"].append({"label": label, "ok": True, "status": resp.status_code})
                last_err = None
                break
            except Exception as exc:
                err = str(exc)
                last_err = err
                diagnostics["attempts"].append({"label": label, "ok": False, "error": err[:240]})
                if not _is_proxy_or_ssl_error(exc) and "timeout" not in err.lower():
                    break
        if html:
            break

    if not html:
        diagnostics["networkError"] = last_err or "DuckDuckGo 请求失败"
        diagnostics["durationMs"] = int((time.time() - started) * 1000)
        diagnostics["failureHint"] = (
            "本地回退检索失败。请优先保证文档服务（aicheckword）可调用；"
            "发布时间检索会复用那边 Cursor/LLM 已配置的代理，无需在本页再配一遍"
        )
        return [], diagnostics

    diagnostics["htmlBytes"] = len(html.encode("utf-8", errors="ignore"))
    out, parser = _parse_duckduckgo_html(html)
    diagnostics["parser"] = parser
    diagnostics["rawHits"] = len(out)
    diagnostics["durationMs"] = int((time.time() - started) * 1000)
    return out, diagnostics


def _build_candidates_from_results(
    *,
    version: str,
    results: list[dict[str, str]],
    include_skipped: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for row in results:
        text = f"{row.get('title', '')} {row.get('snippet', '')}"
        dates = _extract_dates(text)
        if not dates:
            skipped.append(
                {
                    "title": str(row.get("title") or "")[:120],
                    "reason": "snippet中未匹配到日期",
                }
            )
            continue
        candidates.append(
            {
                "version": version,
                "date": dates[0],
                "sourceUrl": row.get("url") or "",
                "sourceTitle": row.get("title") or "",
                "snippet": row.get("snippet") or "",
                "confidence": "low",
            }
        )
    dedup: dict[str, dict[str, Any]] = {}
    for c in candidates:
        if c["date"] not in dedup:
            dedup[c["date"]] = c
    ordered = sorted(dedup.values(), key=lambda x: x["date"], reverse=True)
    extraction: dict[str, Any] = {
        "rowsScanned": len(results),
        "rowsWithDate": len(candidates),
        "rowsSkippedNoDate": len(skipped),
        "candidateCount": len(ordered),
    }
    if include_skipped:
        extraction["skippedSamples"] = skipped[:5]
    if not results:
        extraction["failureHint"] = "DuckDuckGo 页面未解析到搜索结果，可能为网络拦截或 HTML 结构变更"
    elif results and not ordered:
        extraction["failureHint"] = "已解析到搜索结果，但标题/摘要中未提取到 20xx 日期"
    return ordered[:5], extraction


def _duckduckgo_search(query: str, timeout: float = 12.0) -> list[dict[str, str]]:
    results, _ = _duckduckgo_search_with_diagnostics(query, timeout=timeout)
    return results


def _suggest_release_date_for_version(
    *,
    product_name: str,
    version: str,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    terms = [x for x in [product_name.strip(), version.strip(), "发布", "版本"] if x]
    query = " ".join(terms) if terms else f"{version} 版本 发布时间"
    results, ddg_diag = _duckduckgo_search_with_diagnostics(query)
    if ddg_diag.get("networkError"):
        hint = str(ddg_diag.get("failureHint") or "").strip()
        err = str(ddg_diag.get("networkError") or "").strip()
        message = f"联网检索失败：{hint or err}"
        if hint and err and hint not in err:
            message = f"联网检索失败：{hint}（{err[:180]}）"
        payload: dict[str, Any] = {
            "version": version,
            "query": query,
            "candidates": [],
            "message": message,
        }
        if include_diagnostics:
            payload["diagnostics"] = {
                "duckduckgo": ddg_diag,
                "dateExtraction": {
                    "rowsScanned": 0,
                    "rowsWithDate": 0,
                    "rowsSkippedNoDate": 0,
                    "candidateCount": 0,
                    "failureHint": hint or "网络请求失败",
                },
            }
        return payload

    ordered, extraction = _build_candidates_from_results(
        version=version,
        results=results,
        include_skipped=include_diagnostics,
    )
    payload = {
        "version": version,
        "query": query,
        "candidates": ordered,
        "message": (
            "已检索到候选日期，请人工确认后采用。"
            if ordered
            else "未检索到该版本发布时间，请手动填写。"
        ),
    }
    if include_diagnostics:
        payload["diagnostics"] = {"duckduckgo": ddg_diag, "dateExtraction": extraction}
    return payload


def suggest_release_dates(
    *,
    product_name: str,
    from_version: str,
    to_version: str,
    intermediate_versions: Optional[list[str]] = None,
    target_version: Optional[str] = None,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    chain = parse_version_chain(from_version, to_version, intermediate_versions or [])
    versions = [x.normalized for x in chain]
    targets = versions
    if target_version:
        normalized = parse_version(target_version).normalized
        if normalized not in versions:
            raise ValueError(f"目标版本 {target_version} 不在版本链路中")
        targets = [normalized]

    per_version: list[dict[str, Any]] = []
    all_candidates: list[dict[str, Any]] = []
    for version in targets:
        result = _suggest_release_date_for_version(
            product_name=product_name,
            version=version,
            include_diagnostics=include_diagnostics,
        )
        per_version.append(result)
        for candidate in result.get("candidates") or []:
            all_candidates.append(candidate)

    summary: Optional[dict[str, Any]] = None
    if include_diagnostics:
        summary = {
            "versionCount": len(targets),
            "candidateCount": len(all_candidates),
            "versionsWithCandidates": sum(1 for x in per_version if (x.get("candidates") or [])),
            "totalRawHits": sum(
                int((x.get("diagnostics") or {}).get("duckduckgo", {}).get("rawHits") or 0)
                for x in per_version
            ),
        }
        if summary["candidateCount"] == 0 and summary["totalRawHits"] == 0:
            summary["failureHint"] = "未检索到发布时间，请检查外网或手动填写"
        elif summary["candidateCount"] == 0 and summary["totalRawHits"] > 0:
            summary["failureHint"] = "已命中搜索结果但未提取到日期，请手动填写"

    return {
        "fromVersion": chain[0].normalized,
        "toVersion": chain[-1].normalized,
        "versionChain": versions,
        "targetVersion": target_version or None,
        "perVersion": per_version,
        "candidates": all_candidates[:10],
        "message": (
            "已检索到候选发布时间，请人工确认后采用。"
            if all_candidates
            else "未检索到发布时间，请手动填写。"
        ),
        "source": "local",
        "diagnostics": summary,
    }


def diagnose_release_dates(
    *,
    product_name: str,
    from_version: str,
    to_version: str,
    intermediate_versions: Optional[list[str]] = None,
    target_version: Optional[str] = None,
) -> dict[str, Any]:
    result = suggest_release_dates(
        product_name=product_name,
        from_version=from_version,
        to_version=to_version,
        intermediate_versions=intermediate_versions,
        target_version=target_version,
        include_diagnostics=True,
    )
    result["mode"] = "diagnose"
    return result


def feedback_rows_for_org(org_id: str) -> list[VersionTaskGenerationFeedback]:
    return (
        VersionTaskGenerationFeedback.query.filter_by(organization_id=org_id)
        .order_by(VersionTaskGenerationFeedback.created_at.desc())
        .limit(200)
        .all()
    )


def build_adjustment_rows(
    *,
    org_id: str,
    source_job_id: Optional[str],
    project_id: Optional[str],
    adjustments: list[dict[str, Any]],
) -> list[VersionTaskGenerationFeedback]:
    rows: list[VersionTaskGenerationFeedback] = []
    for item in adjustments:
        kind = (str(item.get("type") or "update").strip().lower()) or "update"
        if kind not in {"add", "delete", "update", "replace"}:
            continue
        original = item.get("originalItem")
        adjusted = item.get("adjustedItem")
        rows.append(
            VersionTaskGenerationFeedback(
                organization_id=org_id,
                source_job_id=source_job_id or None,
                project_id=project_id or None,
                adjust_type=kind,
                original_item_json=original if isinstance(original, dict) else None,
                adjusted_item_json=adjusted if isinstance(adjusted, dict) else None,
                applied_count=0,
                last_applied_at=None,
            )
        )
    return rows


def touch_feedback_hits(rows: list[VersionTaskGenerationFeedback]) -> None:
    now = now_local()
    for row in rows:
        row.applied_count = int(row.applied_count or 0) + 1
        row.last_applied_at = now


def _generation_status_rank(status: str) -> int:
    mapping = {"none": 0, "previewed": 1, "generated": 2}
    return mapping.get((status or "").strip().lower(), 0)


def serialize_project_version_record(row: ProjectVersionRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "projectId": row.project_id,
        "version": row.version,
        "releasedAt": _fmt_date(row.released_at) if row.released_at else "",
        "productName": row.product_name or "",
        "chainFromVersion": row.chain_from_version or "",
        "chainToVersion": row.chain_to_version or "",
        "generationStatus": row.generation_status or "none",
        "lastJobId": row.last_job_id or "",
        "updatedAt": row.updated_at.isoformat() if row.updated_at else "",
    }


def _version_sort_key(raw: str) -> tuple[int, int, int, int]:
    p = parse_version(raw)
    return (p.x, p.y, p.z, p.b)


def list_project_version_records(
    *,
    org_id: str,
    project_id: str,
) -> list[dict[str, Any]]:
    rows = (
        ProjectVersionRecord.query.filter_by(organization_id=org_id, project_id=project_id)
        .all()
    )
    rows.sort(key=lambda r: _version_sort_key(r.version))
    return [serialize_project_version_record(x) for x in rows]


def get_project_version_record(
    *,
    org_id: str,
    record_id: str,
) -> Optional[ProjectVersionRecord]:
    row = ProjectVersionRecord.query.filter_by(id=record_id, organization_id=org_id).first()
    return row


def delete_project_version_record(*, org_id: str, record_id: str) -> bool:
    row = get_project_version_record(org_id=org_id, record_id=record_id)
    if not row:
        return False
    db.session.delete(row)
    return True


def _related_project_version_records(
    *,
    org_id: str,
    source: ProjectVersionRecord,
) -> list[ProjectVersionRecord]:
    """同一源项目下的相关版本记录：优先同链路，否则整项目版本组。"""
    rows = (
        ProjectVersionRecord.query.filter_by(
            organization_id=org_id, project_id=source.project_id
        ).all()
    )
    chain_from = (source.chain_from_version or "").strip()
    chain_to = (source.chain_to_version or "").strip()
    if chain_from and chain_to:
        same_chain = [
            r
            for r in rows
            if (r.chain_from_version or "").strip() == chain_from
            and (r.chain_to_version or "").strip() == chain_to
        ]
        if same_chain:
            return same_chain
    return rows


def rebind_project_version_records(
    *,
    org_id: str,
    record_id: str,
    target_project_id: str,
    version: str = "",
    released_at: Optional[str] = None,
    product_name: str = "",
    chain_from_version: str = "",
    chain_to_version: str = "",
    generation_status: str = "",
    allow_downgrade_status: bool = True,
) -> dict[str, Any]:
    """
    保存单条版本记录；若关联项目变更，则同步把相关版本记录与预览批次改绑到新项目。
    """
    source = get_project_version_record(org_id=org_id, record_id=record_id)
    if not source:
        raise ValueError("未找到版本记录")
    old_project_id = source.project_id
    target_project_id = (target_project_id or "").strip()
    if not target_project_id:
        raise ValueError("projectId 不能为空")

    related = _related_project_version_records(org_id=org_id, source=source)
    related_ids = {r.id for r in related}
    moved_jobs = 0

    if old_project_id != target_project_id:
        # 目标项目已有同版本号则拒绝整组改绑
        for r in related:
            conflict = ProjectVersionRecord.query.filter_by(
                project_id=target_project_id, version=r.version
            ).first()
            if conflict and conflict.id not in related_ids:
                raise ValueError(
                    f"目标项目已存在版本 {r.version}，无法同步改绑相关记录"
                )
        for r in related:
            r.project_id = target_project_id
            r.organization_id = org_id

        job_ids = {str(r.last_job_id).strip() for r in related if (r.last_job_id or "").strip()}
        chain_from = (source.chain_from_version or "").strip()
        chain_to = (source.chain_to_version or "").strip()
        jobs = VersionTaskGenerationJob.query.filter_by(
            organization_id=org_id, project_id=old_project_id
        ).all()
        for job in jobs:
            should_move = False
            if job.id and job.id in job_ids:
                should_move = True
            elif chain_from and chain_to:
                if (job.from_version or "") == chain_from and (job.to_version or "") == chain_to:
                    should_move = True
            if should_move:
                job.project_id = target_project_id
                moved_jobs += 1

    item = save_project_version_record_item(
        org_id=org_id,
        project_id=target_project_id,
        record_id=record_id,
        version=version or source.version,
        released_at=released_at,
        product_name=product_name,
        chain_from_version=chain_from_version,
        chain_to_version=chain_to_version,
        generation_status=generation_status,
        allow_downgrade_status=allow_downgrade_status,
    )
    moved_items = [serialize_project_version_record(r) for r in related]
    # related 已在 session 中更新；主记录以 save 结果为准刷新
    for idx, r in enumerate(moved_items):
        if r.get("id") == item.get("id"):
            moved_items[idx] = item
            break
    else:
        moved_items.append(item)

    return {
        "item": item,
        "moved": old_project_id != target_project_id,
        "fromProjectId": old_project_id,
        "toProjectId": target_project_id,
        "movedRecordCount": len({x.get("id") for x in moved_items if x.get("id")}),
        "movedJobCount": moved_jobs,
        "movedItems": moved_items,
    }


def batch_save_project_version_records(
    *,
    org_id: str,
    items: list[dict[str, Any]],
    chain_from_version: str = "",
    chain_to_version: str = "",
) -> dict[str, Any]:
    """批量保存版本记录；若有关联项目变更，先按组改绑再逐条落字段。"""
    if not isinstance(items, list) or not items:
        raise ValueError("items 不能为空")

    prepared: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {idx + 1} 条格式无效")
        project_id = str(raw.get("projectId") or "").strip()
        version_raw = str(raw.get("version") or "").strip()
        if not project_id:
            raise ValueError(f"第 {idx + 1} 条缺少关联项目")
        if not version_raw:
            raise ValueError(f"第 {idx + 1} 条版本号不能为空")
        version = parse_version(version_raw).normalized
        key = (project_id, version)
        if key in seen_keys:
            raise ValueError(f"批量数据中目标项目下版本 {version} 重复")
        seen_keys.add(key)
        prepared.append(
            {
                "id": str(raw.get("id") or "").strip(),
                "projectId": project_id,
                "version": version,
                "releasedAt": str(raw.get("releasedAt") or "").strip(),
                "productName": str(raw.get("productName") or "").strip(),
                "generationStatus": str(raw.get("generationStatus") or "none").strip().lower(),
                "chainFromVersion": str(
                    raw.get("chainFromVersion") or chain_from_version or ""
                ).strip(),
                "chainToVersion": str(
                    raw.get("chainToVersion") or chain_to_version or ""
                ).strip(),
            }
        )

    moved = False
    moved_job_count = 0
    moved_record_count = 0
    already_rebound: set[str] = set()
    for item in prepared:
        record_id = item["id"]
        if not record_id or record_id in already_rebound:
            continue
        row = get_project_version_record(org_id=org_id, record_id=record_id)
        if not row:
            raise ValueError(f"未找到版本记录：{record_id}")
        if row.project_id == item["projectId"]:
            continue
        result = rebind_project_version_records(
            org_id=org_id,
            record_id=record_id,
            target_project_id=item["projectId"],
            version=item["version"],
            released_at=item["releasedAt"],
            product_name=item["productName"],
            chain_from_version=item["chainFromVersion"],
            chain_to_version=item["chainToVersion"],
            generation_status=item["generationStatus"],
            allow_downgrade_status=True,
        )
        moved = moved or bool(result.get("moved"))
        moved_job_count += int(result.get("movedJobCount") or 0)
        moved_record_count = max(
            moved_record_count, int(result.get("movedRecordCount") or 0)
        )
        for moved_item in result.get("movedItems") or []:
            mid = str(moved_item.get("id") or "").strip()
            if mid:
                already_rebound.add(mid)

    saved_items: list[dict[str, Any]] = []
    for item in prepared:
        saved_items.append(
            save_project_version_record_item(
                org_id=org_id,
                project_id=item["projectId"],
                record_id=item["id"] or None,
                version=item["version"],
                released_at=item["releasedAt"],
                product_name=item["productName"],
                chain_from_version=item["chainFromVersion"],
                chain_to_version=item["chainToVersion"],
                generation_status=item["generationStatus"],
                allow_downgrade_status=True,
            )
        )

    return {
        "saved": len(saved_items),
        "items": saved_items,
        "moved": moved,
        "movedRecordCount": moved_record_count,
        "movedJobCount": moved_job_count,
    }


def save_project_version_record_item(
    *,
    org_id: str,
    project_id: str,
    version: str,
    released_at: Optional[str] = None,
    product_name: str = "",
    chain_from_version: str = "",
    chain_to_version: str = "",
    generation_status: str = "",
    job_id: Optional[str] = None,
    record_id: Optional[str] = None,
    allow_downgrade_status: bool = True,
) -> dict[str, Any]:
    normalized = parse_version(version).normalized
    row: Optional[ProjectVersionRecord] = None
    if record_id:
        row = get_project_version_record(org_id=org_id, record_id=record_id)
        if not row:
            raise ValueError("未找到版本记录")
    if row is None:
        row = ProjectVersionRecord.query.filter_by(project_id=project_id, version=normalized).first()
    if row is None:
        row = ProjectVersionRecord(
            organization_id=org_id,
            project_id=project_id,
            version=normalized,
        )
        db.session.add(row)
    elif row.project_id != project_id or row.version != normalized:
        conflict = ProjectVersionRecord.query.filter_by(
            project_id=project_id, version=normalized
        ).first()
        if conflict and conflict.id != row.id:
            raise ValueError(f"目标项目已存在版本 {normalized}")
        row.version = normalized
        row.project_id = project_id
    row.organization_id = org_id
    row.project_id = project_id
    # None = 不修改；空串 = 清空；非空 = 写入日期
    if released_at is not None:
        if str(released_at).strip() == "":
            row.released_at = None
        else:
            row.released_at = _parse_iso_date(str(released_at).strip())
    if product_name:
        row.product_name = product_name.strip()
    if chain_from_version:
        row.chain_from_version = parse_version(chain_from_version).normalized
    if chain_to_version:
        row.chain_to_version = parse_version(chain_to_version).normalized
    next_status = (generation_status or "").strip().lower()
    if next_status:
        current_status = (row.generation_status or "none").strip().lower()
        if allow_downgrade_status or _generation_status_rank(next_status) >= _generation_status_rank(current_status):
            row.generation_status = next_status
    elif not row.generation_status:
        row.generation_status = "none"
    if job_id:
        row.last_job_id = job_id
    return serialize_project_version_record(row)


def upsert_project_version_records(
    *,
    org_id: str,
    project_id: str,
    version_release_dates: dict[str, Any],
    product_name: str = "",
    chain_from_version: str = "",
    chain_to_version: str = "",
    generation_status: str = "",
    job_id: Optional[str] = None,
    allow_downgrade_status: bool = False,
) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    for raw_version, raw_date in (version_release_dates or {}).items():
        version = parse_version(str(raw_version or "").strip()).normalized
        released = _parse_iso_date(str(raw_date or "").strip()) if str(raw_date or "").strip() else None
        row = ProjectVersionRecord.query.filter_by(project_id=project_id, version=version).first()
        if not row:
            row = ProjectVersionRecord(
                organization_id=org_id,
                project_id=project_id,
                version=version,
            )
            db.session.add(row)
        row.organization_id = org_id
        if released:
            row.released_at = released
        if product_name:
            row.product_name = product_name.strip()
        if chain_from_version:
            row.chain_from_version = parse_version(chain_from_version).normalized
        if chain_to_version:
            row.chain_to_version = parse_version(chain_to_version).normalized
        next_status = (generation_status or "").strip().lower()
        if next_status:
            current_status = (row.generation_status or "none").strip().lower()
            if allow_downgrade_status or _generation_status_rank(next_status) >= _generation_status_rank(current_status):
                row.generation_status = next_status
        if job_id:
            row.last_job_id = job_id
        saved.append(serialize_project_version_record(row))
    return saved


def resolve_project_product_name(*, org_id: str, project_id: str) -> str:
    """从版本记录或最近预览批次解析应用市场产品名。"""
    pid = (project_id or "").strip()
    if not pid:
        return ""
    for row in list_project_version_records(org_id=org_id, project_id=pid):
        name = str(row.get("productName") or "").strip()
        if name:
            return name
    job = (
        VersionTaskGenerationJob.query.filter_by(organization_id=org_id, project_id=pid)
        .order_by(VersionTaskGenerationJob.updated_at.desc())
        .first()
    )
    if not job:
        return ""
    snap = job.rule_snapshot_json if isinstance(job.rule_snapshot_json, dict) else {}
    name = str(snap.get("productName") or "").strip()
    if name:
        return name
    preview = job.preview_json if isinstance(job.preview_json, dict) else {}
    return str(preview.get("productName") or "").strip()


def set_project_product_name(
    *,
    org_id: str,
    project_id: str,
    product_name: str,
) -> dict[str, Any]:
    """把应用市场产品名写回该项目的版本记录与预览批次。"""
    pid = (project_id or "").strip()
    name = (product_name or "").strip()
    if not pid:
        raise ValueError("projectId 不能为空")
    updated_records = 0
    for row in ProjectVersionRecord.query.filter_by(
        organization_id=org_id, project_id=pid
    ).all():
        row.product_name = name or None
        updated_records += 1
    updated_jobs = 0
    for job in VersionTaskGenerationJob.query.filter_by(
        organization_id=org_id, project_id=pid
    ).all():
        snap = dict(job.rule_snapshot_json) if isinstance(job.rule_snapshot_json, dict) else {}
        snap["productName"] = name
        job.rule_snapshot_json = snap
        if isinstance(job.preview_json, dict):
            preview = dict(job.preview_json)
            preview["productName"] = name
            job.preview_json = preview
        updated_jobs += 1
    return {
        "projectId": pid,
        "productName": name,
        "updatedRecords": updated_records,
        "updatedJobs": updated_jobs,
    }


def save_version_task_preview_edits(
    *,
    org_id: str,
    job_id: str,
    items: list[dict[str, Any]],
    adjustments: Optional[list[dict[str, Any]]] = None,
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    """保存人工编辑后的预览清单，并可选写入反馈供下次生成生效。"""
    jid = (job_id or "").strip()
    if not jid:
        raise ValueError("jobId 不能为空")
    if not isinstance(items, list):
        raise ValueError("items 必须为数组")
    job = VersionTaskGenerationJob.query.filter_by(
        id=jid, organization_id=org_id
    ).first()
    if not job:
        raise ValueError("未找到预览批次")
    preview = dict(job.preview_json) if isinstance(job.preview_json, dict) else {}
    cleaned_items: list[dict[str, Any]] = []
    for raw in items:
        if isinstance(raw, dict):
            cleaned_items.append(dict(raw))
    preview["items"] = cleaned_items
    preview["editedAt"] = now_local().isoformat()
    preview["manualEdited"] = True
    job.preview_json = preview
    if (job.status or "") != "applied":
        job.status = "previewed"
    if project_id and not job.project_id:
        job.project_id = str(project_id).strip() or None

    feedback_saved = 0
    if adjustments:
        rows = build_adjustment_rows(
            org_id=org_id,
            source_job_id=job.id,
            project_id=(project_id or job.project_id or None),
            adjustments=adjustments,
        )
        for row in rows:
            db.session.add(row)
        feedback_saved = len(rows)
    return {
        "jobId": job.id,
        "projectId": job.project_id or "",
        "itemCount": len(cleaned_items),
        "feedbackSaved": feedback_saved,
        "updatedAt": now_local().isoformat(),
        "items": cleaned_items,
    }


def get_latest_version_task_preview(
    *,
    org_id: str,
    project_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """返回组织内最近一次带 preview_json 的生成批次（可按项目过滤）。"""
    query = VersionTaskGenerationJob.query.filter_by(organization_id=org_id).filter(
        VersionTaskGenerationJob.preview_json.isnot(None)
    )
    if (project_id or "").strip():
        query = query.filter_by(project_id=str(project_id).strip())
    job = query.order_by(VersionTaskGenerationJob.updated_at.desc()).first()
    if not job or not isinstance(job.preview_json, dict):
        return None
    payload = dict(job.preview_json)
    product_name = str(payload.get("productName") or "").strip()
    if not product_name and job.project_id:
        product_name = resolve_project_product_name(
            org_id=org_id, project_id=str(job.project_id)
        )
    payload.update(
        {
            "jobId": job.id,
            "projectId": job.project_id or "",
            "status": job.status or "",
            "updatedAt": job.updated_at.isoformat() if job.updated_at else "",
            "productName": product_name,
        }
    )
    return payload

