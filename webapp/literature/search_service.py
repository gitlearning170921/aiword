from __future__ import annotations

import time
from typing import Any

from flask import current_app

from . import LiteratureRecord, LiteratureSearchResult
from .dedupe import dedupe_records
from .normalize import normalize_record


SUPPORTED_AUTO_SOURCES = ("pubmed", "scholar")
SUPPORTED_IMPORT_SOURCES = ("embase", "cochrane")
SUPPORTED_SOURCES = SUPPORTED_AUTO_SOURCES + SUPPORTED_IMPORT_SOURCES


def _call_upstream_search(
    *,
    query: str,
    sources: list[str],
    start_year: int | None,
    end_year: int | None,
    max_results_per_source: int,
    scholar_captcha_session_id: str = "",
    scholar_sort_by: str = "relevance",
    scholar_start_offset: int = 0,
) -> tuple[list[LiteratureRecord], list[LiteratureSearchResult], dict[str, Any]]:
    """经 aicheckword 出站检索，复用其 llm_http_proxy（与初稿/Cursor 同一配置）。"""
    from .._integration_common import (
        format_upstream_request_error,
        integration_api_base,
        integration_request,
        integration_requests_timeout,
        upstream_headers,
    )
    from ..tenant_context import resolve_organization_context

    empty_meta: dict[str, Any] = {
        "needsCaptcha": False,
        "captchaSessionId": "",
        "captchaSource": "",
        "captchaSearchUrl": "",
    }
    base = integration_api_base()
    if not base:
        return (
            [],
            [
                {
                    "source": s,
                    "records": [],
                    "error": "文档服务未配置，无法检索外网文献（请联系管理员）",
                    "elapsed_ms": 0,
                }
                for s in sources
            ],
            empty_meta,
        )

    oid, _ = resolve_organization_context()
    url = f"{base.rstrip('/')}/api/integration/literature/search"
    t0 = time.perf_counter()
    payload = {
        "query": query,
        "sources": sources,
        "start_year": start_year,
        "end_year": end_year,
        "max_results_per_source": max_results_per_source,
        "scholar_sort_by": (scholar_sort_by or "relevance").strip() or "relevance",
        "scholar_start_offset": max(0, int(scholar_start_offset or 0)),
    }
    if (scholar_captcha_session_id or "").strip():
        payload["scholar_captcha_session_id"] = scholar_captcha_session_id.strip()
    try:
        resp = integration_request(
            "POST",
            url,
            json=payload,
            headers=upstream_headers(for_multipart=False, organization_id=oid or None),
            # Scholar 放慢翻页后一次全量抓取更耗时；读超时须大于后端抓取预算(1500s)
            timeout=integration_requests_timeout(read_seconds=1800),
        )
    except Exception as exc:
        err = format_upstream_request_error(exc, base)
        try:
            current_app.logger.warning("literature upstream search failed: %s", exc)
        except Exception:
            pass
        return (
            [],
            [
                {
                    "source": s,
                    "records": [],
                    "error": err,
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                }
                for s in sources
            ],
            empty_meta,
        )

    if resp.status_code != 200:
        detail = ""
        try:
            detail = (resp.json() or {}).get("detail") or resp.text[:500]
        except Exception:
            detail = (resp.text or "")[:500]
        err = f"文献检索服务失败（HTTP {resp.status_code}）{('：' + detail) if detail else ''}"
        return (
            [],
            [
                {
                    "source": s,
                    "records": [],
                    "error": err,
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                }
                for s in sources
            ],
            empty_meta,
        )

    try:
        body = resp.json()
    except Exception:
        err = "文献检索服务响应非 JSON"
        return (
            [],
            [
                {
                    "source": s,
                    "records": [],
                    "error": err,
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                }
                for s in sources
            ],
            empty_meta,
        )

    if not isinstance(body, dict) or not body.get("ok"):
        err = str((body or {}).get("detail") or (body or {}).get("message") or "文献检索失败")
        return (
            [],
            [
                {
                    "source": s,
                    "records": [],
                    "error": err,
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                }
                for s in sources
            ],
            empty_meta,
        )

    details_raw = body.get("details") if isinstance(body.get("details"), list) else []
    details: list[LiteratureSearchResult] = []
    for item in details_raw:
        if not isinstance(item, dict):
            continue
        recs = [
            normalize_record(x)
            for x in (item.get("records") or [])
            if isinstance(x, dict)
        ]
        details.append(
            {
                "source": str(item.get("source") or ""),
                "records": recs,
                "error": str(item.get("error") or ""),
                "elapsed_ms": int(item.get("elapsed_ms") or 0),
                "totalFound": int(item.get("totalFound") or 0),
                "fetched": int(item.get("fetched") or len(recs)),
            }
        )

    if not details:
        top_recs = [
            normalize_record(x)
            for x in (body.get("records") or [])
            if isinstance(x, dict)
        ]
        for s in sources:
            src_recs = [r for r in top_recs if (r.get("source") or "") == s]
            details.append(
                {
                    "source": s,
                    "records": src_recs,
                    "error": "",
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                }
            )

    aggregated: list[LiteratureRecord] = []
    for d in details:
        aggregated.extend(d.get("records") or [])

    meta = {
        "needsCaptcha": bool(body.get("needsCaptcha")),
        "captchaSessionId": str(body.get("captchaSessionId") or "").strip(),
        "captchaSource": str(body.get("captchaSource") or "").strip(),
        "captchaSearchUrl": str(body.get("captchaSearchUrl") or "").strip(),
    }
    return aggregated, details, meta


def run_search(
    *,
    query: str,
    sources: list[str],
    start_year: int | None = None,
    end_year: int | None = None,
    max_results_per_source: int = 30,
    scholar_captcha_session_id: str = "",
    scholar_sort_by: str = "relevance",
    scholar_start_offset: int = 0,
) -> tuple[list[LiteratureRecord], list[LiteratureSearchResult], dict[str, Any]]:
    srcs = [s.strip().lower() for s in sources if s and s.strip()]
    srcs = [s for s in srcs if s in SUPPORTED_SOURCES]
    if not srcs:
        raise ValueError("sources 不能为空，且必须是支持的数据源")

    auto_sources = [s for s in srcs if s in SUPPORTED_AUTO_SOURCES]
    details: list[LiteratureSearchResult] = []
    aggregated: list[LiteratureRecord] = []
    meta: dict[str, Any] = {
        "needsCaptcha": False,
        "captchaSessionId": "",
        "captchaSource": "",
        "captchaSearchUrl": "",
    }

    if auto_sources:
        records, auto_details, meta = _call_upstream_search(
            query=query,
            sources=auto_sources,
            start_year=start_year,
            end_year=end_year,
            max_results_per_source=max_results_per_source,
            scholar_captcha_session_id=scholar_captcha_session_id,
            scholar_sort_by=scholar_sort_by,
            scholar_start_offset=scholar_start_offset,
        )
        details.extend(auto_details)
        aggregated.extend(records)

    for source in srcs:
        if source in SUPPORTED_IMPORT_SOURCES:
            details.append(
                {
                    "source": source,
                    "records": [],
                    "error": "该来源在 MVP 阶段需手工导入 RIS/CSV",
                    "elapsed_ms": 0,
                }
            )

    deduped = dedupe_records(aggregated)
    return deduped, sorted(details, key=lambda x: x.get("source") or ""), meta
