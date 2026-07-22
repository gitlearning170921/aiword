# -*- coding: utf-8 -*-
from __future__ import annotations

import io
from typing import Any

from flask import Blueprint, Response, jsonify, render_template, request, send_file

from .authz import block_until_super_admin_or_user_id
from .literature.batch_store import clear_batches, delete_batch, list_batches, upsert_batch
from .literature.dedupe import dedupe_records
from .literature.export_docx import export_records_to_docx
from .literature.export_excel import export_records_to_excel
from .literature.importers.riscsv_importer import parse_import_file
from .literature.normalize import normalize_record
from .literature.search_service import SUPPORTED_SOURCES, run_search


literature_bp = Blueprint("literature", __name__, url_prefix="/literature")


def _login_wall(for_api: bool) -> Any:
    return block_until_super_admin_or_user_id(for_api=for_api)


def _parse_sources(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("sources")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        s = str(item or "").strip().lower()
        if not s or s in out:
            continue
        out.append(s)
    return out


def _parse_year(value: Any) -> int | None:
    s = str(value or "").strip()
    if not s:
        return None
    try:
        year = int(s)
    except ValueError:
        return None
    if 1900 <= year <= 3000:
        return year
    return None


def _proxy_scholar_captcha(session_id: str, *, path_suffix: str = "", query_string: str = "") -> Response:
    from ._integration_common import (
        format_upstream_request_error,
        integration_api_base,
        integration_request,
        integration_requests_timeout,
        upstream_headers,
    )
    from .tenant_context import resolve_organization_context

    sid = (session_id or "").strip()
    if not sid:
        return Response("missing session", status=400)
    base = integration_api_base()
    if not base:
        return Response("文档服务未配置", status=500)
    oid, _ = resolve_organization_context()
    rewrite_base = f"/literature/api/scholar-captcha/{sid}"
    upstream = f"{base.rstrip('/')}/api/integration/literature/scholar-captcha/{sid}{path_suffix}"
    params = {}
    if query_string:
        from urllib.parse import parse_qs

        raw = parse_qs(query_string, keep_blank_values=True)
        params = {k: (v[0] if isinstance(v, list) and v else "") for k, v in raw.items()}
    params["rewrite_base"] = rewrite_base

    method = (request.method or "GET").upper()
    try:
        if method == "POST":
            resp = integration_request(
                "POST",
                upstream,
                params=params,
                data=request.get_data(),
                headers={
                    **upstream_headers(for_multipart=True, organization_id=oid or None),
                    "Content-Type": request.headers.get("Content-Type")
                    or "application/x-www-form-urlencoded",
                },
                timeout=integration_requests_timeout(read_seconds=60),
            )
        else:
            resp = integration_request(
                "GET",
                upstream,
                params=params,
                headers=upstream_headers(for_multipart=False, organization_id=oid or None),
                timeout=integration_requests_timeout(read_seconds=60),
            )
    except Exception as exc:
        return Response(format_upstream_request_error(exc, base), status=502)

    content = resp.content or b""
    # 把上游绝对路径改写到本站（若 HTML 中残留）
    if b"/api/integration/literature/scholar-captcha/" in content:
        content = content.replace(
            b"/api/integration/literature/scholar-captcha/",
            b"/literature/api/scholar-captcha/",
        )
    headers = {
        "Cache-Control": "no-store",
        # 允许本站弹窗 iframe 嵌入
        "Content-Security-Policy": "frame-ancestors 'self'",
    }
    ctype = resp.headers.get("Content-Type") or "text/html; charset=utf-8"
    return Response(content, status=resp.status_code, headers=headers, mimetype=ctype)


@literature_bp.route("/", methods=["GET"])
def literature_page():
    blocked = _login_wall(for_api=False)
    if blocked is not None:
        return blocked
    return render_template("literature_search.html")


@literature_bp.route("/api/search", methods=["POST"])
def literature_search_api():
    blocked = _login_wall(for_api=True)
    if blocked is not None:
        return blocked
    payload = request.get_json(silent=True) or {}
    query = str(payload.get("query") or "").strip()
    sources = _parse_sources(payload)
    if not query:
        return jsonify({"ok": False, "message": "query 不能为空"}), 400
    if not sources:
        return jsonify({"ok": False, "message": "sources 至少选择 1 项"}), 400
    unsupported = [s for s in sources if s not in SUPPORTED_SOURCES]
    if unsupported:
        return jsonify({"ok": False, "message": f"不支持的数据源：{', '.join(unsupported)}"}), 400

    max_per_source = payload.get("max_results_per_source") or 200
    try:
        max_per_source = int(max_per_source)
    except (TypeError, ValueError):
        max_per_source = 200
    max_per_source = max(1, min(500, max_per_source))

    try:
        sort_by = str(payload.get("scholar_sort_by") or payload.get("sort_by") or "relevance").strip()
        if sort_by not in ("relevance", "date"):
            sort_by = "relevance"
        try:
            start_offset = max(0, int(payload.get("scholar_start_offset") or 0))
        except (TypeError, ValueError):
            start_offset = 0
        # 验证后续抓：上游从 start_offset 继续翻页，返回本段新增；再与已有记录合并
        prior_records = payload.get("prior_records")
        prior: list[dict[str, Any]] = []
        if isinstance(prior_records, list):
            prior = [x for x in prior_records if isinstance(x, dict)]
            if prior and start_offset <= 0:
                start_offset = len(prior)
        fetch_limit = max_per_source
        if prior:
            fetch_limit = max(1, max_per_source - len(prior))

        new_records, details, meta = run_search(
            query=query,
            sources=sources,
            start_year=_parse_year(payload.get("start_year")),
            end_year=_parse_year(payload.get("end_year")),
            max_results_per_source=fetch_limit,
            scholar_captcha_session_id=str(
                payload.get("scholar_captcha_session_id")
                or payload.get("captchaSessionId")
                or ""
            ).strip(),
            scholar_sort_by=sort_by,
            scholar_start_offset=start_offset,
        )
        try:
            prior_total_found = max(0, int(payload.get("prior_total_found") or 0))
        except (TypeError, ValueError):
            prior_total_found = 0
        if prior:
            records = dedupe_records(prior + list(new_records or []))
        else:
            records = new_records
        # 统一修正每源的 fetched/totalFound：
        # Scholar 的「约 N 条」估计会随翻页缩水，续抓时更明显；总数须取
        # 「历史见过的最大值」，且任何来源的总数都不得小于实际已抓数，避免出现
        # 「47/11」这类倒挂显示。
        for d in details:
            src = d.get("source") or ""
            cnt = len([r for r in (records or []) if (r.get("source") or "") == src])
            d["fetched"] = cnt
            base_total = int(d.get("totalFound") or 0)
            if src == "scholar":
                d["totalFound"] = max(base_total, prior_total_found, cnt)
            elif base_total < cnt:
                d["totalFound"] = cnt
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 500

    def _disp_total(d: dict[str, Any]) -> int:
        """展示用分母：Scholar 的「约 N 条」估计不可靠，估计值不明显大于已抓时，
        退回用用户填写的「每源条数」作目标；其它来源(如 PubMed)总数可信，原样用。"""
        tf = int(d.get("totalFound") or 0)
        ft = int(d.get("fetched") or len(d.get("records") or []))
        if (d.get("source") or "") == "scholar":
            return tf if tf > ft else max_per_source
        return tf

    detail_msg = " | ".join(
        (
            f"{d.get('source')}: {d.get('error')}"
            if d.get("error")
            else (
                f"{d.get('source')}: {d.get('fetched') or len(d.get('records') or [])}"
                + (f"/{_disp_total(d)}" if _disp_total(d) else "")
            )
        )
        for d in details
    )
    years = []
    sy = payload.get("start_year")
    ey = payload.get("end_year")
    if sy:
        years.append(str(sy))
    if ey:
        years.append(str(ey))
    year_part = "–".join(years) if years else "不限年份"
    totals = "；".join(
        (
            f"{d.get('source')}: {len([r for r in records if (r.get('source') or '') == d.get('source')])}"
            + (f"/{_disp_total(d)}" if _disp_total(d) else "")
        )
        for d in details
    )
    summary = (
        f"检索式：{query} ｜ 来源：{', '.join(sources)} ｜ {year_part} ｜ "
        f"每源上限 {max_per_source} ｜ 已取 {len(records)}"
        + (f"（{totals}）" if totals else "")
    )
    batch = None
    try:
        batch = upsert_batch(
            batch_id=str(payload.get("batch_id") or "").strip() or None,
            batch_type="search",
            query=query,
            sources=sources,
            summary=summary,
            status_note=detail_msg,
            details=details,
            records=records,
            params={
                "start_year": str(payload.get("start_year") or "").strip(),
                "end_year": str(payload.get("end_year") or "").strip(),
                "max_results_per_source": max_per_source,
                "scholar_sort_by": sort_by,
            },
        )
    except Exception as exc:
        # 检索成功但落库失败时仍返回结果，附带提示
        return jsonify(
            {
                "ok": True,
                "records": records,
                "details": details,
                "count": len(records),
                "sources": sources,
                "needsCaptcha": bool(meta.get("needsCaptcha")),
                "captchaSessionId": str(meta.get("captchaSessionId") or ""),
                "captchaSource": str(meta.get("captchaSource") or ""),
                "captchaSearchUrl": str(meta.get("captchaSearchUrl") or ""),
                "batch": None,
                "persistWarning": f"结果未落库：{exc}",
            }
        )

    return jsonify(
        {
            "ok": True,
            "records": records,
            "details": details,
            "count": len(records),
            "sources": sources,
            "needsCaptcha": bool(meta.get("needsCaptcha")),
            "captchaSessionId": str(meta.get("captchaSessionId") or ""),
            "captchaSource": str(meta.get("captchaSource") or ""),
            "captchaSearchUrl": str(meta.get("captchaSearchUrl") or ""),
            "batch": batch,
        }
    )


@literature_bp.route("/api/scholar-captcha/<session_id>", methods=["GET"])
def literature_scholar_captcha_entry(session_id: str):
    blocked = _login_wall(for_api=False)
    if blocked is not None:
        return blocked
    return _proxy_scholar_captcha(session_id, path_suffix="", query_string="")


@literature_bp.route("/api/scholar-captcha/<session_id>/nav", methods=["GET", "POST"])
def literature_scholar_captcha_nav(session_id: str):
    blocked = _login_wall(for_api=False)
    if blocked is not None:
        return blocked
    return _proxy_scholar_captcha(
        session_id,
        path_suffix="/nav",
        query_string=request.query_string.decode("utf-8", errors="ignore"),
    )


@literature_bp.route("/api/import", methods=["POST"])
def literature_import_api():
    blocked = _login_wall(for_api=True)
    if blocked is not None:
        return blocked

    source = str(request.form.get("source") or "").strip().lower()
    if source not in ("embase", "cochrane", "pubmed", "scholar"):
        return jsonify({"ok": False, "message": "source 不合法"}), 400

    f = request.files.get("file")
    if f is None or not str(f.filename or "").strip():
        return jsonify({"ok": False, "message": "请上传 RIS/CSV 文件"}), 400

    try:
        data = parse_import_file(str(f.filename), f.read(), source_name=source)
        records = dedupe_records([normalize_record(x) for x in data if isinstance(x, dict)])
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    batch = None
    try:
        batch = upsert_batch(
            batch_id=None,
            batch_type="import",
            query=str(f.filename or ""),
            sources=[source],
            summary=f"文件：{f.filename} ｜ 来源：{source} ｜ 命中 {len(records)}",
            status_note="",
            details=[{"source": source, "fetched": len(records), "totalFound": len(records), "error": ""}],
            records=records,
        )
    except Exception as exc:
        return jsonify(
            {
                "ok": True,
                "records": records,
                "count": len(records),
                "source": source,
                "batch": None,
                "persistWarning": f"结果未落库：{exc}",
            }
        )

    return jsonify(
        {
            "ok": True,
            "records": records,
            "count": len(records),
            "source": source,
            "batch": batch,
        }
    )


@literature_bp.route("/api/batches", methods=["GET"])
def literature_batches_list_api():
    blocked = _login_wall(for_api=True)
    if blocked is not None:
        return blocked
    try:
        limit = int(request.args.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    try:
        return jsonify({"ok": True, "batches": list_batches(limit=limit)})
    except Exception as exc:
        return jsonify({"ok": False, "message": f"读取历史批次失败：{exc}", "batches": []}), 500


@literature_bp.route("/api/batches/<batch_id>", methods=["DELETE"])
def literature_batch_delete_api(batch_id: str):
    blocked = _login_wall(for_api=True)
    if blocked is not None:
        return blocked
    ok = delete_batch(batch_id)
    if not ok:
        return jsonify({"ok": False, "message": "批次不存在或无权删除"}), 404
    return jsonify({"ok": True})


@literature_bp.route("/api/batches", methods=["DELETE"])
def literature_batches_clear_api():
    blocked = _login_wall(for_api=True)
    if blocked is not None:
        return blocked
    n = clear_batches()
    return jsonify({"ok": True, "deleted": n})


@literature_bp.route("/api/export", methods=["POST"])
def literature_export_api():
    blocked = _login_wall(for_api=True)
    if blocked is not None:
        return blocked
    payload = request.get_json(silent=True) or {}
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        return jsonify({"ok": False, "message": "records 不能为空"}), 400
    cleaned: list[dict[str, Any]] = []
    for item in records:
        if isinstance(item, dict):
            cleaned.append(normalize_record(item))
    if not cleaned:
        return jsonify({"ok": False, "message": "records 格式不正确"}), 400
    fmt = str(payload.get("format") or "docx").strip().lower()
    if fmt in ("xlsx", "excel"):
        blob, file_name = export_records_to_excel(cleaned)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        blob, file_name = export_records_to_docx(cleaned)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return send_file(
        io.BytesIO(blob),
        as_attachment=True,
        download_name=file_name,
        mimetype=mime,
    )


@literature_bp.route("/api/schema", methods=["GET"])
def literature_schema_api():
    blocked = _login_wall(for_api=True)
    if blocked is not None:
        return blocked
    return jsonify(
        {
            "ok": True,
            "requestShape": {
                "query": "string",
                "sources": ["pubmed", "scholar"],
                "start_year": "int|optional",
                "end_year": "int|optional",
                "max_results_per_source": "int|optional",
                "scholar_captcha_session_id": "string|optional",
            },
            "supportedSources": list(SUPPORTED_SOURCES),
            "note": "sources 必须是数组；单选时示例 [\"pubmed\"]。Scholar 触发人机验证时可弹窗完成。",
        }
    )
