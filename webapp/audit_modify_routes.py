# -*- coding: utf-8 -*-
"""aiword 审核后修改集成：在本地组装 audit_remediation_by_target，再调上游 draft jobs API。

- 页面：/audit-modify/ （从页面2 任务行进入，可携带 upload_id）
- 提交：POST /audit-modify/api/jobs（multipart：base docx + 可选 report.json + payload）
- 轮询/下载：直接代理到 /draft-gen/api/jobs/<id>/status|download（共用 DraftGenerationJob）

报告来源（与用户选项 id_plus_upload 一致）：
1. 调用方显式 report_id（优先）
2. 本地 UploadRecord.last_audit_report_id（fallback）
3. 手动上传 report.json（最终兜底）

稳态边界：
- 仅 1 个目标模板 + 1 个 Base（同 draft，避免锚点漂移）
"""

from __future__ import annotations

import io
import json
import re
import uuid
from pathlib import Path
from typing import Any, Optional

import requests
from flask import (
    Blueprint,
    Response,
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
    INTEGRATION_SCOPE_PAGE0,
    build_integration_bootstrap_payload,
    build_upload_prefill_payload,
    client_llm_headers_for_session,
    integration_api_base,
    integration_read_timeout,
    integration_requests_timeout,
    integration_scope_from_request,
    integration_scope_list_filter,
    latest_audit_report_id_for_scope,
    login_wall,
    manual_upload_only_from_request,
    resolve_org_collection_for_integration,
    resolve_aicheckword_project_id_for_upload,
    safe_truncate,
    upload_record_visible_to_user,
    upstream_headers,
)
from .models import DraftGenerationJob, UploadRecord, now_local


audit_modify_bp = Blueprint("audit_modify", __name__, url_prefix="/audit-modify")


_SEVERITY_LABELS = {"high": "高", "medium": "中", "low": "低", "info": "提示"}


def _audit_modify_timeout() -> int:
    return integration_read_timeout("AICHECKWORD_DRAFT_TIMEOUT_SECONDS", default=600)


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


def _postaudit_target_key(nm: str) -> str:
    """与 aicheckword Streamlit 审核后修改的文件名归一化一致。"""
    s = str(nm or "").strip()
    if not s:
        return ""
    base = Path(s).name
    m = re.match(r"^\d+_(.+)$", base)
    return (m.group(1) if m else base).strip().lower()


def _parse_selected_refs(raw: Optional[str]) -> Optional[set[str]]:
    s = (raw or "").strip()
    if not s:
        return None
    out = {x.strip() for x in s.split(",") if x.strip()}
    return out or None


def _fetch_immediate_remediation_upstream(
    *,
    report_id: Optional[int] = None,
    report_dict: Optional[dict[str, Any]] = None,
    selected_refs: Optional[set[str]] = None,
    organization_id: Optional[str] = None,
) -> tuple[dict[str, str], Optional[str], dict[str, Any]]:
    """调用 aicheckword ``immediate-remediation`` API（与 Streamlit 同源逻辑）。"""
    base = integration_api_base()
    if not base:
        return {}, "未配置 AICHECKWORD_DRAFT_API_BASE / QUIZ_API_BASE_URL", {}
    refs_q = ""
    if selected_refs:
        refs_q = ",".join(sorted(selected_refs))
    try:
        if report_id is not None and report_id > 0:
            url = f"{base}/api/integration/audit/reports/{int(report_id)}/immediate-remediation"
            params = {"selected_refs": refs_q} if refs_q else None
            r = requests.get(
                url,
                params=params,
                headers=upstream_headers(
                    for_multipart=False, organization_id=organization_id
                ),
                timeout=integration_requests_timeout(read_seconds=min(30, _audit_modify_timeout())),
            )
        elif isinstance(report_dict, dict) and report_dict:
            r = requests.post(
                f"{base}/api/integration/audit/reports/immediate-remediation",
                headers=upstream_headers(
                    for_multipart=False, organization_id=organization_id
                ),
                json={
                    "report": report_dict,
                    "selected_refs": sorted(selected_refs) if selected_refs else None,
                },
                timeout=integration_requests_timeout(read_seconds=min(30, _audit_modify_timeout())),
            )
        else:
            return {}, "缺少 report_id 或 report 内容", {}
    except requests.RequestException as e:
        return {}, f"上游 immediate-remediation 不可达：{e}", {}

    if r.status_code != 200:
        detail = ""
        try:
            detail = (r.json() or {}).get("detail") or r.text[:500]
        except Exception:
            detail = r.text[:500]
        return {}, f"上游 HTTP {r.status_code}：{detail}", {}
    try:
        body = r.json()
    except Exception:
        return {}, "上游 immediate-remediation 响应非 JSON", {}
    if not isinstance(body, dict) or not body.get("ok"):
        return {}, (body.get("detail") or body.get("message") or "上游 immediate-remediation 失败"), {}
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    tbt = data.get("text_by_target") if isinstance(data.get("text_by_target"), dict) else {}
    out = {str(k): str(v) for k, v in tbt.items() if str(k).strip() and str(v or "").strip()}
    return out, None, data


def _remediation_collapsed_to_template(
    text_by_target: dict[str, str],
    template_key: str,
    base_display_name: str,
) -> dict[str, str]:
    """把审核点目标名合并到与 ``template_file_names`` / Base 上传名一致的键，避免注入不到 LLM。"""
    tk = str(template_key or "").strip() or str(base_display_name or "").strip()
    if not tk:
        return dict(text_by_target or {})
    tn = _postaudit_target_key(tk)
    bn = _postaudit_target_key(base_display_name)
    parts: list[str] = []
    for src, txt in (text_by_target or {}).items():
        t = str(txt or "").strip()
        if not t:
            continue
        sn = _postaudit_target_key(src)
        if (
            not tn
            or sn == tn
            or (bn and (sn == bn or bn in sn or sn in bn))
            or len(text_by_target) == 1
        ):
            parts.append(t)
        else:
            parts.append(f"【审核目标：{src}】\n{t}")
    if not parts:
        parts = [str(v).strip() for v in text_by_target.values() if str(v).strip()]
    merged = "\n\n".join(parts).strip()
    return {tk: merged} if merged else {}


def _enforce_audit_modify_stable(
    target_file_names: list[str], base_file_count: int
) -> Optional[str]:
    if len(target_file_names) != 1:
        return f"稳态模式要求仅指定 1 个目标模板文件（当前 {len(target_file_names)} 个）。"
    if base_file_count != 1:
        return f"稳态模式要求仅提供 1 个 Base 文件（当前 {base_file_count} 个）。"
    return None


def _load_raw_report_for_request() -> tuple[Optional[dict], Optional[int], Optional[str]]:
    """解析 report 来源，返回 (report_dict, report_id, error)。"""
    base = integration_api_base()
    report_id_raw = (request.form.get("report_id") or request.args.get("report_id") or "").strip()
    upload_id_raw = (request.form.get("upload_id") or request.args.get("upload_id") or "").strip()
    org_id, _ = resolve_org_collection_for_integration(upload_id=upload_id_raw)
    report_file = request.files.get("report_json_file") if request.files else None
    if report_file:
        try:
            raw_text = report_file.read().decode("utf-8", errors="replace")
            rep = json.loads(raw_text)
            return (rep if isinstance(rep, dict) else {}), None, None
        except Exception as e:  # noqa: BLE001
            return None, None, f"上传的 report.json 解析失败：{e}"
    if report_id_raw and base:
        try:
            rid = int(report_id_raw)
        except ValueError:
            return None, None, "report_id 无效"
        try:
            r = requests.get(
                f"{base}/api/integration/audit/reports/{rid}",
                headers=upstream_headers(for_multipart=False, organization_id=org_id),
                timeout=integration_requests_timeout(read_seconds=min(30, _audit_modify_timeout())),
            )
            if r.status_code != 200:
                return None, None, f"上游 HTTP {r.status_code}（取 report_id）"
            data = r.json()
            if not isinstance(data, dict) or not data.get("ok"):
                return None, None, "上游响应无效（取 report_id）"
            rep = (data.get("data") or {}).get("report") or {}
            return (rep if isinstance(rep, dict) else {}), rid, None
        except requests.RequestException as e:
            return None, None, f"上游不可达（取 report_id）：{e}"
    if upload_id_raw:
        rec = UploadRecord.query.get(upload_id_raw)
        if not rec:
            return None, None, "未找到该 upload_id"
        if not upload_record_visible_to_user(rec):
            return None, None, "无权限访问该 upload_id"
        rid = rec.last_audit_report_id
        if not rid:
            return None, None, "该任务尚无历史审核报告，请改用 report_id 或上传 report.json"
        if not base:
            return None, None, "未配置上游 API"
        try:
            r = requests.get(
                f"{base}/api/integration/audit/reports/{int(rid)}",
                headers=upstream_headers(for_multipart=False, organization_id=org_id),
                timeout=integration_requests_timeout(read_seconds=min(30, _audit_modify_timeout())),
            )
            if r.status_code != 200:
                return None, None, f"上游 HTTP {r.status_code}（取本地缓存 report_id）"
            data = r.json()
            if not isinstance(data, dict) or not data.get("ok"):
                return None, None, "上游响应无效（取本地缓存 report_id）"
            rep = (data.get("data") or {}).get("report") or {}
            return (rep if isinstance(rep, dict) else {}), int(rid), None
        except requests.RequestException as e:
            return None, None, f"上游不可达（取本地缓存 report_id）：{e}"
    return None, None, "请提供 report_id、upload_id 之一，或上传 report.json"


def _fetch_remediation_for_request() -> tuple[Optional[dict[str, str]], Optional[str], Any]:
    """根据请求构建 audit_remediation_by_target（与 aicheckword Streamlit 同源）。"""
    raw_report, report_id, err = _load_raw_report_for_request()
    if err:
        return None, err, None
    selected_refs = _parse_selected_refs(
        (request.form.get("selected_audit_point_refs") or request.args.get("selected_refs") or "")
    )
    org_id, _ = resolve_org_collection_for_integration(
        upload_id=(request.form.get("upload_id") or request.args.get("upload_id") or "").strip()
    )
    remediation, rem_err, _meta = _fetch_immediate_remediation_upstream(
        report_id=report_id,
        report_dict=raw_report if report_id is None else None,
        selected_refs=selected_refs,
        organization_id=org_id,
    )
    if rem_err:
        return None, rem_err, raw_report
    if not remediation:
        return (
            None,
            "审核报告里没有可执行的「立即修改」审核点（高/中风险在未标记 action 时默认视为立即修改）",
            raw_report,
        )
    return remediation, None, raw_report


@audit_modify_bp.route("/")
def audit_modify_page():
    if not session.get("user_id"):
        from flask import redirect, url_for

        return redirect(url_for("pages.login_page"))
    scope = integration_scope_from_request()
    default_page0_report_id = None
    if scope == INTEGRATION_SCOPE_PAGE0:
        default_page0_report_id = latest_audit_report_id_for_scope(
            str(session.get("user_id") or ""), scope
        )

    return render_template(
        "audit_modify.html",
        manual_upload_only=manual_upload_only_from_request(),
        integration_scope=scope,
        default_page0_report_id=default_page0_report_id,
    )


@audit_modify_bp.get("/api/integration-bootstrap")
def api_audit_modify_integration_bootstrap():
    err = login_wall()
    if err:
        return err
    collection = (request.args.get("collection") or "regulations").strip() or "regulations"
    org_id, resolved_collection = resolve_org_collection_for_integration(
        preferred_collection=collection
    )
    payload = build_integration_bootstrap_payload(
        resolved_collection,
        read_timeout=30,
        organization_id=org_id,
    )
    if not payload.get("ok"):
        return jsonify({"message": payload.get("message") or "加载失败"}), 502
    return jsonify(payload)


@audit_modify_bp.get("/api/upload-prefill")
def api_audit_modify_upload_prefill():
    err = login_wall()
    if err:
        return err
    uid = (request.args.get("upload_id") or "").strip()
    body, code = build_upload_prefill_payload(uid)
    return jsonify(body), code


@audit_modify_bp.get("/api/upload-name")
def api_audit_modify_upload_name():
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


@audit_modify_bp.post("/api/jobs")
def api_audit_modify_create_job():
    err = login_wall()
    if err:
        return err
    base = integration_api_base()
    if not base:
        return jsonify({"message": "未配置 AICHECKWORD_DRAFT_API_BASE / QUIZ_API_BASE_URL"}), 500

    payload_str = (request.form.get("payload") or "").strip()
    if not payload_str:
        return jsonify({"message": "payload 不能为空"}), 400
    try:
        payload_obj = json.loads(payload_str)
        if not isinstance(payload_obj, dict):
            raise ValueError("payload 必须是 JSON 对象")
    except Exception as e:  # noqa: BLE001
        return jsonify({"message": f"payload 解析失败：{e}"}), 400

    org_id, resolved_collection = resolve_org_collection_for_integration(
        preferred_collection=str(payload_obj.get("collection") or "regulations"),
        upload_ids=[
            x for x in [upload_id, base_upload_id] if str(x or "").strip()
        ],
    )
    payload_obj["collection"] = resolved_collection

    try:
        pid = int(payload_obj.get("project_id") or 0)
    except (TypeError, ValueError):
        pid = 0

    # 报告来源：优先 report_id；其次 upload_id 的最近审核报告；最后 report.json。
    report_id_raw = (request.form.get("report_id") or request.args.get("report_id") or "").strip()
    report_id: Optional[int] = None
    raw_report: Optional[dict[str, Any]] = None
    if report_id_raw:
        try:
            report_id = int(report_id_raw)
        except ValueError:
            return jsonify({"message": "report_id 无效"}), 400
    else:
        report_file = request.files.get("report_json_file") if request.files else None
        if report_file:
            try:
                raw_text = report_file.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw_text)
            except Exception as e:  # noqa: BLE001
                return jsonify({"message": f"上传的 report.json 解析失败：{e}"}), 400
            if not isinstance(parsed, dict):
                return jsonify({"message": "report.json 必须是 JSON 对象"}), 400
            raw_report = parsed

    # Base 文件来源：multipart base_files / 同时支持 base_upload_id 拉任务
    base_upload_id = (request.form.get("base_upload_id") or "").strip()
    upload_id = (request.form.get("upload_id") or "").strip()
    if report_id is None and raw_report is None and upload_id:
        rec_for_report = UploadRecord.query.get(upload_id)
        if not rec_for_report:
            return jsonify({"message": "未找到该 upload_id"}), 404
        if not upload_record_visible_to_user(rec_for_report):
            return jsonify({"message": "无权限访问该 upload_id"}), 403
        rid = rec_for_report.last_audit_report_id
        if rid:
            report_id = int(rid)
    base_files_form = request.files.getlist("base_files") or []
    pid_guess = None
    if upload_id:
        pid_guess = resolve_aicheckword_project_id_for_upload(
            upload_id, user_id=str(session.get("user_id") or "")
        )
    if (not pid_guess) and base_upload_id:
        pid_guess = resolve_aicheckword_project_id_for_upload(
            base_upload_id, user_id=str(session.get("user_id") or "")
        )
    if pid_guess and int(pid_guess) > 0 and pid != int(pid_guess):
        payload_obj["project_id"] = int(pid_guess)
        pid = int(pid_guess)
    if pid <= 0:
        return jsonify(
            {
                "message": (
                    "请先选择 aicheckword 项目后再提交审核后修改。"
                    "未绑定项目会显著降低审核点约束与修订命中率。"
                )
            }
        ), 400
    if report_id is None and raw_report is None:
        return jsonify({"message": "请提供 report_id、upload_id 或上传 report.json"}), 400

    base_uploads: list[tuple[str, bytes]] = []  # (upload_name, blob)
    if base_upload_id and base_files_form:
        return jsonify(
            {
                "message": "Base 来源唯一性：base_upload_id 与 base_files 不可同时提供"
            }
        ), 400
    if base_upload_id:
        rec = UploadRecord.query.get(base_upload_id)
        if not rec or not upload_record_visible_to_user(rec):
            return jsonify({"message": "未找到任务或无权限"}), 404
        from .draft_generation_routes import _base_doc_bytes_from_upload, _template_display_filename

        try:
            blob, _name = _base_doc_bytes_from_upload(rec)
        except Exception as e:  # noqa: BLE001
            return jsonify({"message": f"从任务取 Base 失败：{e}"}), 500
        if not blob:
            return jsonify({"message": "该任务尚无可用 Base 模板文件"}), 400
        disp = _template_display_filename(rec) or rec.file_name or "base.docx"
        base_uploads.append((disp, blob))
    else:
        for f in base_files_form:
            data = f.read()
            if not data:
                continue
            base_uploads.append(((f.filename or "base.docx").strip() or "base.docx", data))

    if not base_uploads:
        return jsonify({"message": "请提供 base_upload_id 或上传 1 个 Base 文件"}), 400
    upload_name = base_uploads[0][0]
    tpl_manual = ""
    tpl0 = payload_obj.get("template_file_names")
    if isinstance(tpl0, list) and tpl0:
        tpl_manual = str(tpl0[0] or "").strip()
    skip_tpl = bool(payload_obj.get("skip_case_template_text", False))
    track = bool(payload_obj.get("docx_track_changes", True))
    try:
        pid_for_prepare = int(payload_obj.get("project_id") or 0) or None
    except (TypeError, ValueError):
        pid_for_prepare = None

    from ._integration_common import upstream_post_json

    prep_body: dict[str, Any] = {
        "template_file_name": tpl_manual or upload_name,
        "base_file_name": upload_name,
        "collection": resolved_collection,
        "project_id": pid_for_prepare,
        "skip_case_template_text": skip_tpl,
        "docx_track_changes": track,
        "provider": (payload_obj.get("provider") or "").strip() or None,
    }
    if report_id:
        prep_body["report_id"] = int(report_id)
    elif raw_report:
        prep_body["report"] = raw_report
    else:
        return jsonify({"message": "无法确定审核报告来源"}), 400

    prep_data, prep_err = upstream_post_json(
        "api/integration/audit/audit-modify/prepare-draft-payload",
        prep_body,
        read_timeout_seconds=min(15, _audit_modify_timeout()),
        organization_id=org_id,
    )
    if prep_err:
        return jsonify({"message": prep_err}), 400

    draft_from_upstream = (prep_data or {}).get("draftPayload") if isinstance(prep_data, dict) else {}
    if not isinstance(draft_from_upstream, dict) or not draft_from_upstream:
        return jsonify({"message": "上游未返回 draftPayload"}), 502

    for k, v in draft_from_upstream.items():
        payload_obj[k] = v
    if payload_obj.get("provider") is None and prep_body.get("provider"):
        payload_obj["provider"] = prep_body["provider"]
    payload_obj["aiword_user_id"] = str(session.get("user_id") or "")

    target_names = list(payload_obj.get("template_file_names") or [])
    if not target_names:
        return jsonify({"message": "上游未返回 template_file_names"}), 502

    stable_err = _enforce_audit_modify_stable(target_names, len(base_uploads))
    if stable_err:
        return jsonify({"message": stable_err}), 400

    template_key = str(target_names[0])
    base_files_by_target = payload_obj.get("base_files_by_target")
    if not isinstance(base_files_by_target, dict):
        base_files_by_target = {}
    base_files_by_target[template_key] = upload_name
    payload_obj["base_files_by_target"] = base_files_by_target

    uid_session = str(session.get("user_id") or "")
    job_scope = integration_scope_from_request()
    # 本地 job：复用 DraftGenerationJob，标记 source=audit_modify
    local_job = DraftGenerationJob(
        user_id=uid_session,
        organization_id=(org_id or None),
        status="pending",
        progress=0.0,
        collection=resolved_collection,
        base_case_id=int(payload_obj.get("base_case_id") or 0) or None,
        project_id=int(payload_obj.get("project_id") or 0) or None,
        template_names_json=list(target_names),
        input_display_names_json=[upload_name],
        integration_scope=job_scope,
        payload_snapshot_json={
            k: payload_obj.get(k)
            for k in (
                "collection",
                "base_case_id",
                "project_id",
                "document_language",
                "registration_country",
                "registration_type",
                "registration_component",
                "project_form",
                "provider",
                "draft_strategy",
                "inplace_patch",
                "save_as_case",
                "skip_case_template_text",
                "docx_track_changes",
                "audit_remediation_by_target",
                "template_file_names",
                "base_files_by_target",
            )
        },
        message="提交中…",
        source="audit_modify",
    )
    db.session.add(local_job)
    db.session.commit()

    # 提交上游 draft jobs
    url = f"{base}/api/integration/draft/jobs"
    hdrs = upstream_headers(for_multipart=True, organization_id=org_id)
    hdrs.update(client_llm_headers_for_session())
    files_to_upload: list[tuple[str, tuple[str, bytes, str]]] = [
        ("base_files", (upload_name, base_uploads[0][1], "application/octet-stream"))
    ]
    try:
        r = requests.post(
            url,
            data={"payload": json.dumps(payload_obj, ensure_ascii=False)},
            files=files_to_upload,
            headers=hdrs,
            # 提交只需要上游返回 job_id，避免前端长期卡在“提交中”。
            timeout=integration_requests_timeout(read_seconds=min(25, _audit_modify_timeout())),
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
            "remediationTargets": list(target_names),
        }
    )


@audit_modify_bp.get("/api/jobs/<local_id>/status")
def api_audit_modify_status(local_id: str):
    """审核后修改与初稿共用 DraftGenerationJob → 直接复用 draft 模块的轮询。"""
    err = login_wall()
    if err:
        return err
    from .draft_generation_routes import api_job_status

    return api_job_status(local_id)


@audit_modify_bp.get("/api/jobs/<local_id>/download")
def api_audit_modify_download(local_id: str):
    err = login_wall()
    if err:
        return err
    from .draft_generation_routes import api_job_download

    return api_job_download(local_id)


@audit_modify_bp.get("/api/jobs")
def api_audit_modify_jobs_list():
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
    q = DraftGenerationJob.query.filter_by(user_id=uid, source="audit_modify")
    q = integration_scope_list_filter(q, DraftGenerationJob, scope)
    total = q.count()
    rows = (
        q
        .order_by(desc(DraftGenerationJob.created_at))
        .offset(offset)
        .limit(page_size)
        .all()
    )
    out = []
    for j in rows:
        has_local_zip = bool(j.local_zip_path and Path(j.local_zip_path).is_file())
        st = (j.status or "").strip().lower()
        can_download = st == "succeeded" and (has_local_zip or bool(j.upstream_job_id))
        out.append(
            {
                "id": j.id,
                "status": j.status,
                "progress": j.progress or 0.0,
                "message": j.message or "",
                "error": j.error_summary or None,
                "templateNames": list(j.template_names_json or []),
                "hasLocalZip": has_local_zip,
                "canDownload": can_download,
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


@audit_modify_bp.get("/api/latest-audit-report")
def api_audit_modify_latest_audit_report():
    """页面0：取当前用户在该 scope 下最近一次成功审核的 report_id。"""
    err = login_wall()
    if err:
        return err
    scope = integration_scope_from_request(allow_form=False)
    uid = str(session.get("user_id") or "")
    rid = latest_audit_report_id_for_scope(uid, scope)
    if not rid:
        return jsonify({"ok": True, "reportId": None, "scope": scope})
    return jsonify({"ok": True, "reportId": rid, "scope": scope})


@audit_modify_bp.get("/api/post-audit-defaults")
def api_post_audit_defaults():
    """代理 aicheckword 审核后修改维度默认值。"""
    err = login_wall()
    if err:
        return err
    from ._integration_common import upstream_get_json

    report_id = (request.args.get("report_id") or "").strip()
    upload_id = (request.args.get("upload_id") or "").strip()
    if not report_id and upload_id:
        rec = UploadRecord.query.get(upload_id)
        if rec and upload_record_visible_to_user(rec) and rec.last_audit_report_id:
            report_id = str(rec.last_audit_report_id)
    if not report_id:
        return jsonify({"message": "缺少 report_id 或带历史报告的 upload_id"}), 400
    org_id, _ = resolve_org_collection_for_integration(upload_id=upload_id)
    params: dict[str, Any] = {}
    pid = (request.args.get("project_id") or "").strip()
    if pid:
        params["project_id"] = pid
    data, up_err = upstream_get_json(
        f"api/integration/audit/reports/{int(report_id)}/post-audit-defaults",
        params=params or None,
        read_timeout_seconds=20,
        organization_id=org_id,
    )
    if up_err:
        return jsonify({"message": up_err}), 502
    return jsonify({"ok": True, "meta": data or {}})


@audit_modify_bp.get("/api/preview-remediation")
def api_preview_remediation():
    """预览将注入到 draft 的 audit_remediation_by_target（与 Streamlit 同源 immediate-remediation）。"""
    err = login_wall()
    if err:
        return err
    raw_report, report_id, load_err = _load_raw_report_for_request()
    if load_err:
        return jsonify({"message": load_err}), 400
    selected_refs = _parse_selected_refs(request.args.get("selected_refs"))
    org_id, _ = resolve_org_collection_for_integration(
        upload_id=(request.args.get("upload_id") or "").strip()
    )
    rem, rem_err, meta = _fetch_immediate_remediation_upstream(
        report_id=report_id,
        report_dict=raw_report if report_id is None else None,
        selected_refs=selected_refs,
        organization_id=org_id,
    )
    if rem_err:
        return jsonify({"message": rem_err}), 400
    return jsonify(
        {
            "ok": True,
            "targets": list(rem.keys()),
            "remediation": rem,
            "immediateCount": int((meta or {}).get("immediate_count") or 0),
            "reportSummary": {
                "id": (raw_report or {}).get("id") or report_id,
                "file_name": (raw_report or {}).get("file_name"),
                "total_points": (raw_report or {}).get("total_points"),
                "high_count": (raw_report or {}).get("high_count"),
                "medium_count": (raw_report or {}).get("medium_count"),
                "low_count": (raw_report or {}).get("low_count"),
                "info_count": (raw_report or {}).get("info_count"),
            },
        }
    )
