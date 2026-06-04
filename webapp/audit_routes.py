# -*- coding: utf-8 -*-
"""aiword 审核集成：将 aicheckword /api/integration/audit/* 暴露为页面级接口。

- 页面：/audit/ （从页面1 跳入，可携带 upload_ids / mode）
- 提交：POST /audit/api/jobs（multipart，与上游同结构）
- 轮询：GET /audit/api/jobs/<local_id>/status（同步上游并回写本地）
- 下载：GET /audit/api/jobs/<local_id>/download（代理上游 ZIP）
- 单任务最新报告：GET /audit/api/uploads/<id>/latest-report

稳态边界（来自初稿集成踩坑）：
- mode 必须三选一：single / multi / traceability
- multi / traceability 至少 2 个文件
- single 上限 50 个
- 文件来源二选一：upload_ids 拉取 vs 手动上传，不允许混用
"""

from __future__ import annotations

import io
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests
from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    session,
)
from sqlalchemy import desc

from . import db
from ._integration_common import (
    apply_upstream_job_fields,
    build_integration_bootstrap_payload,
    build_upload_prefill_payload,
    client_llm_headers_for_session,
    integration_api_base,
    integration_read_timeout,
    integration_requests_timeout,
    integration_scope_from_request,
    integration_scope_list_filter,
    login_wall,
    manual_upload_only_from_request,
    safe_truncate,
    resolve_aicheckword_project_id_for_upload,
    upload_record_visible_to_user,
    upstream_headers,
)
from .models import AuditJob, UploadRecord, now_local


audit_bp = Blueprint("audit", __name__, url_prefix="/audit")

_VALID_MODES = ("single", "multi", "traceability")
_SINGLE_MODE_MAX_FILES = 50


def _audit_timeout() -> int:
    return integration_read_timeout("AICHECKWORD_AUDIT_TIMEOUT_SECONDS", default=600)


def _enforce_audit_stable(
    mode: str, file_count: int
) -> Optional[str]:
    if mode not in _VALID_MODES:
        return f"mode 必须是 {list(_VALID_MODES)}，当前 {mode!r}"
    if file_count <= 0:
        return "至少需要 1 个文件"
    if mode == "single" and file_count > _SINGLE_MODE_MAX_FILES:
        return (
            f"single 模式单次最多 {_SINGLE_MODE_MAX_FILES} 个文件，"
            f"当前 {file_count} 个；请分批"
        )
    if mode in ("multi", "traceability") and file_count < 2:
        return f"{mode} 模式至少需要 2 个文件，当前 {file_count} 个"
    return None


def _apply_upstream_status(job: AuditJob, data: dict) -> None:
    """把上游 audit job 状态/进度同步到本地 AuditJob 记录。"""
    res = data.get("result") if isinstance(data.get("result"), dict) else None

    def _on_succeeded(_data: dict) -> None:
        if not isinstance(res, dict):
            return
        if isinstance(res.get("report_ids"), list):
            job.report_ids_json = [int(x) for x in res["report_ids"] if str(x).strip().isdigit()]
        if isinstance(res.get("reports_summary"), list):
            job.reports_summary_json = res["reports_summary"]
        if bool(res.get("audit_failed")):
            job.status = "failed"
            top = res.get("reports_summary") or []
            top_msg = ""
            if isinstance(top, list) and top:
                summaries = [
                    f"{x.get('file', '')}: {x.get('error', '')}"
                    for x in top
                    if isinstance(x, dict) and x.get("error")
                ]
                top_msg = "；".join(summaries[:3])
            job.error_summary = safe_truncate(
                "审核失败：上游未产出有效审核点。"
                + (f" 主因：{top_msg}" if top_msg else ""),
                4000,
            )
            if not (job.message or "").strip():
                job.message = "审核失败"

    apply_upstream_job_fields(job, data, on_succeeded=_on_succeeded)
    db.session.add(job)
    db.session.commit()


def _maybe_update_upload_records(job: AuditJob, data: dict) -> None:
    """succeeded 且非 audit_failed 时，把 reports_summary 回写到对应 UploadRecord 的 last_audit_*。"""
    if job.status != "succeeded":
        return
    res = data.get("result") if isinstance(data.get("result"), dict) else {}
    if not isinstance(res, dict):
        return
    if bool(res.get("audit_failed")):
        return
    rs = res.get("reports_summary") or []
    if not isinstance(rs, list):
        return
    mode = (job.mode or "single").lower()
    upload_ids = list(job.upload_ids_json or []) if job.upload_ids_json else []
    if mode == "single":
        # 按位置匹配（与上游 items 顺序一致），最多写回前 N 条
        for i, summary in enumerate(rs):
            if not isinstance(summary, dict):
                continue
            uid = ""
            # 优先从 summary 里读 aiword_upload_id；否则按位置匹配 upload_ids
            uid = str(summary.get("aiword_upload_id") or "").strip()
            if not uid and i < len(upload_ids):
                uid = str(upload_ids[i]).strip()
            if not uid:
                continue
            rec = UploadRecord.query.get(uid)
            if not rec:
                continue
            rec.last_audit_report_id = summary.get("report_id")
            rec.last_audit_mode = mode
            rec.last_audit_severity_json = {
                k: summary.get(k)
                for k in ("total", "high", "medium", "low", "info")
                if summary.get(k) is not None
            }
            rec.last_audit_at = now_local()
            db.session.add(rec)
    else:
        # multi / traceability：把同一份报告挂到所有相关 upload_ids 下
        if not rs:
            return
        summary = rs[0] if isinstance(rs[0], dict) else {}
        for uid in upload_ids:
            uid = str(uid).strip()
            if not uid:
                continue
            rec = UploadRecord.query.get(uid)
            if not rec:
                continue
            rec.last_audit_report_id = summary.get("report_id")
            rec.last_audit_mode = mode
            rec.last_audit_severity_json = {
                k: summary.get(k)
                for k in ("total", "high", "medium", "low", "info")
                if summary.get(k) is not None
            }
            rec.last_audit_at = now_local()
            db.session.add(rec)
    db.session.commit()


def _resolve_upload_record_files(
    upload_ids: list[str],
) -> tuple[list[tuple[str, bytes, str]], list[str]]:
    """从一组 UploadRecord.id 取 (display_name, blob_bytes, upload_id) 三元组。

    返回 (resolved, missing)：missing 是因为权限/无文件被跳过的 upload_id 文案。
    """
    from .draft_generation_routes import _base_doc_bytes_from_upload, _template_display_filename

    resolved: list[tuple[str, bytes, str]] = []
    missing: list[str] = []
    seen: set[str] = set()
    for uid in upload_ids:
        uid = (uid or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        rec = UploadRecord.query.get(uid)
        if not rec:
            missing.append(f"{uid}: 未找到记录")
            continue
        if not upload_record_visible_to_user(rec):
            missing.append(f"{uid}: 无权限或不属于当前用户")
            continue
        try:
            blob, _name = _base_doc_bytes_from_upload(rec)
        except Exception as e:  # noqa: BLE001
            missing.append(f"{uid}: 取文件失败 ({e})")
            continue
        if not blob:
            missing.append(f"{uid}: 无可用模板文件")
            continue
        disp = _template_display_filename(rec) or rec.file_name or f"task_{uid}.docx"
        resolved.append((disp, blob, rec.id))
    return resolved, missing


def _fetch_upload_display_name(upload_id: str) -> str:
    rec = UploadRecord.query.get((upload_id or "").strip())
    if not rec:
        return ""
    if not upload_record_visible_to_user(rec):
        return ""
    fn = (
        (getattr(rec, "original_file_name", None) or "").strip()
        or (getattr(rec, "file_name", None) or "").strip()
        or (getattr(rec, "stored_file_name", None) or "").strip()
    )
    return fn


@audit_bp.route("/")
def audit_page():
    if not session.get("user_id"):
        from flask import redirect, url_for

        return redirect(url_for("pages.login_page"))
    scope = integration_scope_from_request()
    return render_template(
        "audit.html",
        manual_upload_only=manual_upload_only_from_request(),
        integration_scope=scope,
    )


@audit_bp.get("/api/meta")
def api_audit_meta():
    """审核/翻译页共用：项目 + 注册维度 + 文档语言（来自 aicheckword common/bootstrap）。"""
    err = login_wall()
    if err:
        return err
    collection = (request.args.get("collection") or "regulations").strip() or "regulations"
    payload = build_integration_bootstrap_payload(
        collection, read_timeout=min(30, _audit_timeout())
    )
    if not payload.get("ok"):
        return jsonify({"message": payload.get("message") or "加载失败"}), 502
    return jsonify(payload)


@audit_bp.get("/api/integration-bootstrap")
def api_integration_bootstrap():
    """与 ``/api/meta`` 相同，供审核/审核后修改/翻译页统一调用。"""
    return api_audit_meta()


@audit_bp.get("/api/upload-prefill")
def api_audit_upload_prefill():
    err = login_wall()
    if err:
        return err
    uid = (request.args.get("upload_id") or "").strip()
    body, code = build_upload_prefill_payload(uid)
    return jsonify(body), code


@audit_bp.get("/api/upload-name")
def api_audit_upload_name():
    err = login_wall()
    if err:
        return err
    uid = (request.args.get("upload_id") or "").strip()
    if not uid:
        return jsonify({"ok": False, "message": "缺少 upload_id"}), 400
    name = _fetch_upload_display_name(uid)
    if not name:
        return jsonify({"ok": False, "message": "未找到任务或无权限"}), 404
    return jsonify({"ok": True, "uploadId": uid, "fileName": name})


@audit_bp.get("/report-edit")
def audit_report_edit_page():
    err = login_wall()
    if err:
        return err
    return render_template("audit_report_edit.html")


@audit_bp.post("/api/jobs")
def api_audit_create_job():
    err = login_wall()
    if err:
        return err
    base = integration_api_base()
    if not base:
        return jsonify({"message": "未配置 AICHECKWORD_DRAFT_API_BASE / QUIZ_API_BASE_URL"}), 500

    # 表单字段：payload(JSON 字符串) + upload_ids（CSV）+ input_files[]
    payload_str = (request.form.get("payload") or "").strip()
    if not payload_str:
        return jsonify({"message": "payload 不能为空"}), 400
    try:
        payload_obj = json.loads(payload_str)
        if not isinstance(payload_obj, dict):
            raise ValueError("payload 必须是 JSON 对象")
    except Exception as e:  # noqa: BLE001
        return jsonify({"message": f"payload 解析失败：{e}"}), 400

    mode = (payload_obj.get("mode") or "single").strip().lower()
    if mode not in _VALID_MODES:
        return jsonify({"message": f"mode 必须是 {list(_VALID_MODES)}"}), 400

    upload_ids_raw = request.form.get("upload_ids") or ""
    upload_ids: list[str] = [
        x.strip() for x in upload_ids_raw.replace(",", "\n").splitlines() if x.strip()
    ]

    uploaded_files = request.files.getlist("input_files") or []
    has_task_source = bool(upload_ids)
    has_manual_source = bool(uploaded_files)
    if has_task_source and has_manual_source:
        return jsonify({"message": "来源唯一性：upload_ids 与 input_files 不可同时提供"}), 400
    if not has_task_source and not has_manual_source:
        return jsonify({"message": "请至少提供一个 upload_ids 或 input_files"}), 400

    try:
        pid = int(payload_obj.get("project_id") or 0)
    except (TypeError, ValueError):
        pid = 0
    if has_task_source and upload_ids:
        pid_guess = resolve_aicheckword_project_id_for_upload(
            upload_ids[0], user_id=str(session.get("user_id") or "")
        )
        if pid_guess and int(pid_guess) > 0 and pid != int(pid_guess):
            payload_obj["project_id"] = int(pid_guess)
            pid = int(pid_guess)
    if pid <= 0:
        return jsonify(
            {
                "message": (
                    "请先选择 aicheckword 项目后再提交审核。"
                    "未绑定项目会显著降低审核点召回与项目约束命中率。"
                )
            }
        ), 400

    # 组合 multipart files + display_name_map + aiword_upload_id_map
    resolved_blobs: list[tuple[str, bytes, str]] = []
    if has_task_source:
        resolved, missing = _resolve_upload_record_files(upload_ids)
        if not resolved:
            return jsonify(
                {
                    "message": "未能从所选任务取到任何可审核的文件",
                    "missing": missing,
                }
            ), 400
        resolved_blobs = resolved
    else:
        for f in uploaded_files:
            raw_name = (f.filename or "").strip() or "upload.bin"
            data = f.read()
            if not data:
                continue
            resolved_blobs.append((raw_name, data, ""))

    err_msg = _enforce_audit_stable(mode, len(resolved_blobs))
    if err_msg:
        return jsonify({"message": err_msg}), 400

    # display_name_map + aiword_upload_id_map：以 multipart "上传名"为 key
    display_map: dict[str, str] = {}
    upload_id_map: dict[str, str] = {}
    file_uploads: list[tuple[str, tuple[str, bytes, str]]] = []
    used_names: set[str] = set()
    for disp_name, blob, uid in resolved_blobs:
        # 上传名（去重）：使用展示名直接作为上传名（与显式 display_name_map 对齐，便于上游记录到位）
        candidate = disp_name
        i = 1
        while candidate in used_names:
            stem, dot, ext = (disp_name or "upload.bin").rpartition(".")
            candidate = f"{stem}__{i}.{ext}" if dot else f"{disp_name}_{i}"
            i += 1
        used_names.add(candidate)
        display_map[candidate] = disp_name
        if uid:
            upload_id_map[candidate] = uid
        file_uploads.append(
            ("input_files", (candidate, blob, "application/octet-stream"))
        )

    payload_obj["display_name_map"] = display_map
    if upload_id_map:
        payload_obj["aiword_upload_id_map"] = upload_id_map
    payload_obj["aiword_user_id"] = str(session.get("user_id") or "")

    from ._integration_common import enrich_audit_payload_from_upstream

    enrich_audit_payload_from_upstream(payload_obj)

    uid_session = str(session.get("user_id") or "")
    job_scope = integration_scope_from_request()
    # 本地 job 记录
    local_job = AuditJob(
        user_id=uid_session,
        status="pending",
        progress=0.0,
        mode=mode,
        collection=str(payload_obj.get("collection") or "regulations"),
        source=("task" if has_task_source else "manual"),
        integration_scope=job_scope,
        upload_ids_json=(list(upload_ids) if has_task_source else None),
        payload_snapshot_json={
            k: v
            for k, v in payload_obj.items()
            if k
            in (
                "mode",
                "collection",
                "project_id",
                "document_language",
                "registration_country",
                "registration_type",
                "registration_component",
                "project_form",
                "provider",
                "system_prompt",
                "user_prompt",
                "extra_instructions",
            )
        },
        message="提交中…",
    )
    db.session.add(local_job)
    db.session.commit()

    # 提交上游
    url = f"{base}/api/integration/audit/jobs"
    hdrs = upstream_headers(for_multipart=True)
    hdrs.update(client_llm_headers_for_session())
    try:
        r = requests.post(
            url,
            data={"payload": json.dumps(payload_obj, ensure_ascii=False)},
            files=file_uploads,
            headers=hdrs,
            timeout=integration_requests_timeout(read_seconds=_audit_timeout()),
        )
    except requests.RequestException as e:
        local_job.status = "failed"
        local_job.message = "提交上游失败"
        local_job.error_summary = safe_truncate(str(e), 4000)
        db.session.commit()
        return jsonify({"message": f"提交上游失败：{e}"}), 502

    if r.status_code != 200:
        local_job.status = "failed"
        local_job.message = f"上游 HTTP {r.status_code}"
        local_job.error_summary = safe_truncate(r.text, 4000)
        db.session.commit()
        return jsonify({"message": f"上游 HTTP {r.status_code}", "detail": r.text[:2000]}), 502

    try:
        upstream = r.json()
    except Exception:
        local_job.status = "failed"
        local_job.message = "上游响应非 JSON"
        db.session.commit()
        return jsonify({"message": "上游响应非 JSON"}), 502

    upstream_id = (upstream.get("job_id") or "").strip()
    if not upstream_id:
        local_job.status = "failed"
        local_job.message = "上游未返回 job_id"
        db.session.commit()
        return jsonify({"message": "上游未返回 job_id", "detail": upstream}), 502

    local_job.upstream_job_id = upstream_id
    local_job.status = (upstream.get("status") or "queued").strip().lower() or "queued"
    local_job.message = "已提交，等待处理…"
    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "localJobId": local_job.id,
            "upstreamJobId": upstream_id,
            "mode": mode,
        }
    )


@audit_bp.get("/api/jobs/<local_id>/status")
def api_audit_job_status(local_id: str):
    err = login_wall()
    if err:
        return err
    job = AuditJob.query.get(local_id)
    if not job:
        return jsonify({"message": "未找到任务"}), 404
    if job.user_id != str(session.get("user_id") or ""):
        return jsonify({"message": "无权限"}), 403
    if not job.upstream_job_id:
        return jsonify(
            {
                "ok": True,
                "localJobId": job.id,
                "status": job.status,
                "progress": job.progress or 0.0,
                "message": job.message or "",
                "error": job.error_summary or None,
            }
        )

    base = integration_api_base()
    if not base:
        return jsonify({"message": "未配置上游 API"}), 500
    url = f"{base}/api/integration/audit/jobs/{job.upstream_job_id}"
    try:
        r = requests.get(
            url,
            headers=upstream_headers(for_multipart=False),
            timeout=integration_requests_timeout(read_seconds=min(60, _audit_timeout())),
        )
    except requests.RequestException as e:
        return jsonify(
            {
                "ok": True,
                "localJobId": job.id,
                "status": job.status,
                "progress": job.progress or 0.0,
                "message": job.message or "",
                "error": f"上游同步失败：{e}",
            }
        )
    if r.status_code != 200:
        return jsonify(
            {
                "ok": True,
                "localJobId": job.id,
                "status": job.status,
                "progress": job.progress or 0.0,
                "message": job.message or "",
                "error": f"上游 HTTP {r.status_code}",
            }
        )
    try:
        data = r.json()
    except Exception:
        return jsonify(
            {
                "ok": True,
                "localJobId": job.id,
                "status": job.status,
                "progress": job.progress or 0.0,
                "message": job.message or "",
                "error": "上游响应非 JSON",
            }
        )

    _apply_upstream_status(job, data)
    _maybe_update_upload_records(job, data)
    return jsonify(
        {
            "ok": True,
            "localJobId": job.id,
            "upstreamJobId": job.upstream_job_id,
            "status": job.status,
            "progress": job.progress or 0.0,
            "message": job.message or "",
            "error": job.error_summary or None,
            "errorSummary": job.error_summary or None,
            "result": (data.get("result") if isinstance(data, dict) else None),
            "reportIds": list(job.report_ids_json or []),
            "reportsSummary": list(job.reports_summary_json or []),
        }
    )


def _collect_report_ids_for_job(
    job: AuditJob,
    upstream_result: Optional[dict[str, Any]] = None,
) -> list[int]:
    """从本地 job 与上游 result 汇总 report_id（去重、保序）。"""
    ids: list[int] = []

    def _add(raw: Any) -> None:
        try:
            v = int(raw)
        except (TypeError, ValueError):
            return
        if v > 0 and v not in ids:
            ids.append(v)

    for raw in job.report_ids_json or []:
        _add(raw)
    if isinstance(upstream_result, dict):
        for raw in upstream_result.get("report_ids") or []:
            _add(raw)
        for s in upstream_result.get("reports_summary") or []:
            if isinstance(s, dict):
                _add(s.get("report_id"))
    for s in job.reports_summary_json or []:
        if isinstance(s, dict):
            _add(s.get("report_id"))
    return ids


def _fetch_upstream_report_row(
    report_id: int,
    *,
    read_seconds: int,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """拉取 aicheckword ``GET /api/reports/{id}`` 完整行（含 report JSON）。"""
    base = integration_api_base()
    if not base:
        return None, "未配置上游 API"
    try:
        r = requests.get(
            f"{base}/api/reports/{int(report_id)}",
            headers=upstream_headers(for_multipart=False),
            timeout=integration_requests_timeout(read_seconds=read_seconds),
        )
    except requests.RequestException as e:
        return None, f"上游请求失败：{e}"
    if r.status_code != 200:
        return None, f"上游 HTTP {r.status_code}"
    try:
        data = r.json()
    except Exception:
        return None, "上游响应非 JSON"
    if not isinstance(data, dict):
        return None, "上游响应格式异常"
    return data, None


@audit_bp.get("/api/jobs/<local_id>/reports")
def api_audit_job_full_reports(local_id: str):
    """按本地任务拉取与 aicheckword 一致的完整审核报告（含全部 audit_points）。"""
    err = login_wall()
    if err:
        return err
    job = AuditJob.query.get(local_id)
    if not job:
        return jsonify({"message": "未找到任务"}), 404
    if job.user_id != str(session.get("user_id") or ""):
        return jsonify({"message": "无权限"}), 403

    upstream_result: Optional[dict[str, Any]] = None
    if job.upstream_job_id:
        base = integration_api_base()
        if base:
            try:
                r = requests.get(
                    f"{base}/api/integration/audit/jobs/{job.upstream_job_id}",
                    headers=upstream_headers(for_multipart=False),
                    timeout=integration_requests_timeout(read_seconds=min(60, _audit_timeout())),
                )
                if r.status_code == 200:
                    j = r.json()
                    if isinstance(j, dict):
                        upstream_result = j.get("result") if isinstance(j.get("result"), dict) else None
            except requests.RequestException:
                pass

    report_ids = _collect_report_ids_for_job(job, upstream_result)
    if not report_ids:
        return jsonify(
            {
                "ok": True,
                "localJobId": job.id,
                "reportIds": [],
                "items": [],
                "errors": [{"error": "该任务无 report_id，无法加载完整报告"}],
            }
        )

    read_sec = min(120, max(30, _audit_timeout()))
    items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for rid in report_ids:
        row, em = _fetch_upstream_report_row(rid, read_seconds=read_sec)
        if row:
            items.append(row)
        else:
            errors.append({"report_id": rid, "error": em or "未知错误"})
    return jsonify(
        {
            "ok": True,
            "localJobId": job.id,
            "reportIds": report_ids,
            "items": items,
            "errors": errors,
        }
    )


@audit_bp.get("/api/jobs/<local_id>/download")
def api_audit_job_download(local_id: str):
    err = login_wall()
    if err:
        return err
    job = AuditJob.query.get(local_id)
    if not job:
        return jsonify({"message": "未找到任务"}), 404
    if job.user_id != str(session.get("user_id") or ""):
        return jsonify({"message": "无权限"}), 403
    base = integration_api_base()
    if not base or not job.upstream_job_id:
        return jsonify({"message": "上游未就绪"}), 400
    url = f"{base}/api/integration/audit/jobs/{job.upstream_job_id}/download"
    try:
        r = requests.get(
            url,
            headers=upstream_headers(for_multipart=False),
            timeout=integration_requests_timeout(read_seconds=_audit_timeout()),
            stream=False,
        )
    except requests.RequestException as e:
        return jsonify({"message": f"代理下载失败：{e}"}), 502
    if r.status_code != 200:
        return jsonify({"message": f"上游 HTTP {r.status_code}", "detail": r.text[:1000]}), 502
    return send_file(
        io.BytesIO(r.content),
        as_attachment=True,
        download_name=f"audit_{job.id}.zip",
        mimetype="application/zip",
    )


@audit_bp.get("/api/jobs")
def api_audit_jobs_list():
    err = login_wall()
    if err:
        return err
    try:
        page = int((request.args.get("page") or "1").strip())
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int((request.args.get("page_size") or "10").strip())
    except (TypeError, ValueError):
        page_size = 10
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    offset = (page - 1) * page_size
    uid = str(session.get("user_id") or "")
    scope = integration_scope_from_request()
    q = AuditJob.query.filter_by(user_id=uid)
    q = integration_scope_list_filter(q, AuditJob, scope)
    total = q.count()
    rows = (
        q
        .order_by(desc(AuditJob.created_at))
        .offset(offset)
        .limit(page_size)
        .all()
    )
    out = []
    for j in rows:
        out.append(
            {
                "id": j.id,
                "status": j.status,
                "progress": j.progress or 0.0,
                "mode": j.mode,
                "source": j.source,
                "message": j.message or "",
                "error": j.error_summary or None,
                "uploadIds": list(j.upload_ids_json or []),
                "reportIds": list(j.report_ids_json or []),
                "reportsSummary": list(j.reports_summary_json or []),
                "createdAt": j.created_at.isoformat(timespec="seconds") if j.created_at else None,
                "updatedAt": j.updated_at.isoformat(timespec="seconds") if j.updated_at else None,
            }
        )
    total_pages = max(1, (total + page_size - 1) // page_size) if total else 1
    return jsonify(
        {
            "ok": True,
            "items": out,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            },
        }
    )


@audit_bp.get("/api/reports/<int:report_id>/edit-url")
def api_audit_report_edit_url(report_id: int):
    """返回 aiword 内置报告编辑页 URL（不依赖 aicheckword 前端）。"""
    err = login_wall()
    if err:
        return err
    return jsonify({"ok": True, "url": f"/audit/report-edit?report_id={int(report_id)}"})


@audit_bp.get("/api/reports/<int:report_id>/edit")
def api_audit_report_edit_redirect(report_id: int):
    """兼容旧入口：跳转到 aiword 内置报告编辑页。"""
    err = login_wall()
    if err:
        return err
    return jsonify({"ok": True, "url": f"/audit/report-edit?report_id={int(report_id)}"})


@audit_bp.get("/api/reports/<int:report_id>")
def api_audit_report_proxy_get(report_id: int):
    """代理 aicheckword GET /api/reports/{id}，供 aiword 内置编辑器读取。"""
    base = integration_api_base()
    if not base:
        return jsonify({"message": "未配置上游 API"}), 500
    try:
        r = requests.get(
            f"{base}/api/reports/{int(report_id)}",
            headers=upstream_headers(for_multipart=False),
            timeout=integration_requests_timeout(read_seconds=min(30, _audit_timeout())),
        )
    except requests.RequestException as e:
        return jsonify({"message": f"上游请求失败：{e}"}), 502
    if r.status_code != 200:
        return jsonify({"message": f"上游 HTTP {r.status_code}", "detail": r.text[:2000]}), 502
    try:
        data = r.json()
    except Exception:
        return jsonify({"message": "上游响应非 JSON"}), 502
    return jsonify({"ok": True, "data": data})


@audit_bp.patch("/api/reports/<int:report_id>/points/<int:point_index>")
def api_audit_report_proxy_patch_point(report_id: int, point_index: int):
    """代理 aicheckword PATCH /api/reports/{id}/points/{point_index}。"""
    err = login_wall()
    if err:
        return err
    base = integration_api_base()
    if not base:
        return jsonify({"message": "未配置上游 API"}), 500
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"message": "请求体必须是 JSON 对象"}), 400
    sub_idx_raw = (request.args.get("sub_report_index") or "0").strip()
    try:
        sub_idx = int(sub_idx_raw)
    except (TypeError, ValueError):
        sub_idx = 0
    if sub_idx < 0:
        sub_idx = 0
    try:
        r = requests.patch(
            f"{base}/api/reports/{int(report_id)}/points/{int(point_index)}",
            params={"sub_report_index": sub_idx},
            json=body,
            headers=upstream_headers(for_multipart=False),
            timeout=integration_requests_timeout(read_seconds=min(30, _audit_timeout())),
        )
    except requests.RequestException as e:
        return jsonify({"message": f"上游请求失败：{e}"}), 502
    if r.status_code != 200:
        return jsonify({"message": f"上游 HTTP {r.status_code}", "detail": r.text[:2000]}), 502
    try:
        data = r.json()
    except Exception:
        return jsonify({"message": "上游响应非 JSON"}), 502
    return jsonify({"ok": True, "data": data})


@audit_bp.get("/api/uploads/<upload_id>/latest-report")
def api_upload_latest_report(upload_id: str):
    """页面2 审核后修改：取该任务最近一次审核报告。优先本地缓存，未命中再回上游。"""
    err = login_wall()
    if err:
        return err
    rec = UploadRecord.query.get((upload_id or "").strip())
    if not rec:
        return jsonify({"message": "未找到任务"}), 404
    if not upload_record_visible_to_user(rec):
        return jsonify({"message": "无权限"}), 403

    local_rid = rec.last_audit_report_id
    base = integration_api_base()
    if local_rid and base:
        try:
            r = requests.get(
                f"{base}/api/integration/audit/reports/{int(local_rid)}",
                headers=upstream_headers(for_multipart=False),
                timeout=integration_requests_timeout(read_seconds=min(30, _audit_timeout())),
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and data.get("ok"):
                    return jsonify(
                        {
                            "ok": True,
                            "source": "local_cache",
                            "uploadId": rec.id,
                            "reportId": int(local_rid),
                            "data": data.get("data") or {},
                        }
                    )
        except requests.RequestException:
            pass

    # fallback：按 upload_id / 展示名查
    if not base:
        return jsonify({"message": "未配置上游 API"}), 500
    fn = (rec.original_file_name or rec.file_name or "").strip()
    try:
        r = requests.get(
            f"{base}/api/integration/audit/reports/by-upload",
            params={
                "aiword_upload_id": rec.id,
                "file_name": fn,
                "limit": 1,
            },
            headers=upstream_headers(for_multipart=False),
            timeout=integration_requests_timeout(read_seconds=min(30, _audit_timeout())),
        )
    except requests.RequestException as e:
        return jsonify({"message": f"上游查询失败：{e}"}), 502
    if r.status_code != 200:
        return jsonify({"message": f"上游 HTTP {r.status_code}"}), 502
    try:
        data = r.json()
    except Exception:
        return jsonify({"message": "上游响应非 JSON"}), 502
    items = (data or {}).get("items") or []
    if not items:
        return jsonify(
            {
                "ok": False,
                "uploadId": rec.id,
                "message": "未找到该任务的历史审核报告",
            }
        ), 404
    first = items[0]
    return jsonify(
        {
            "ok": True,
            "source": "by_upload",
            "uploadId": rec.id,
            "reportId": first.get("id"),
            "data": first,
        }
    )
