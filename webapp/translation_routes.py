# -*- coding: utf-8 -*-
"""aiword 翻译集成：将 aicheckword /api/integration/translation/* 暴露为页面级接口。

- 页面：/translate/
- 提交：POST /translate/api/jobs（multipart：input_files + payload，或 upload_ids 从任务拉文件）
- 轮询：GET /translate/api/jobs/<local_id>/status
- 下载：GET /translate/api/jobs/<local_id>/download

稳态边界：单次 ≤ 5 文件 + 1 target_lang；upload_ids 与 input_files 二选一。
"""

from __future__ import annotations

import io
import json
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
from .user_facing import api_debug_fields
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
    integration_organization_list_filter,
    login_wall,
    msg_proxy_download_failed,
    msg_upstream_http,
    msg_upstream_not_configured,
    msg_upstream_not_configured_env,
    msg_upstream_not_json,
    msg_upstream_no_job_id,
    msg_upstream_not_ready,
    msg_upstream_submit_failed,
    sanitize_integration_message,
    msg_upstream_sync_failed,
    personal_llm_key_wall,
    resolve_org_collection_for_integration,
    sync_active_organization_if_requested,
    safe_truncate,
    upload_record_visible_to_user,
    upstream_headers,
)
from .models import TranslationJob, UploadRecord, now_local


translation_bp = Blueprint("translation", __name__, url_prefix="/translate")

_VALID_LANGS = ("en", "de", "zh")
_MAX_FILES_PER_JOB = 5
_MAX_CORRECT_FILES_PER_JOB = 10
_SUPPORTED_EXTS = (".docx", ".txt", ".xlsx")
_UPLOAD_ARCHIVE_EXTS = (".zip", ".tar", ".gz", ".tgz")


def _translation_timeout() -> int:
    return integration_read_timeout(
        "AICHECKWORD_TRANSLATION_TIMEOUT_SECONDS", default=600
    )


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


@translation_bp.get("/api/meta")
def api_translate_meta():
    """与审核页相同 bootstrap（项目/维度/公司配置）。"""
    err = login_wall()
    if err:
        return err
    collection = (request.args.get("collection") or "regulations").strip() or "regulations"
    explicit_org = (request.args.get("organizationId") or request.args.get("organization_id") or "").strip()
    try:
        org_id, resolved_collection = resolve_org_collection_for_integration(
            preferred_collection=collection,
            explicit_organization_id=explicit_org or None,
        )
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    sync_active_organization_if_requested(explicit_org, org_id)
    payload = build_integration_bootstrap_payload(
        resolved_collection,
        read_timeout=min(30, _translation_timeout()),
        organization_id=org_id,
    )
    if not payload.get("ok"):
        return jsonify({"message": payload.get("message") or "加载失败"}), 502
    return jsonify(payload)


@translation_bp.get("/api/integration-bootstrap")
def api_translate_integration_bootstrap():
    return api_translate_meta()


@translation_bp.get("/api/upload-prefill")
def api_translate_upload_prefill():
    err = login_wall()
    if err:
        return err
    uid = (request.args.get("upload_id") or "").strip()
    body, code = build_upload_prefill_payload(uid)
    return jsonify(body), code


@translation_bp.get("/api/kb-query-extra")
def api_translate_kb_query_extra():
    """代理 aicheckword 按项目拼接 kb_query_extra（与 Streamlit 翻译页一致）。"""
    err = login_wall()
    if err:
        return err
    from ._integration_common import upstream_get_json

    try:
        pid = int((request.args.get("project_id") or "").strip())
    except ValueError:
        return jsonify({"message": "project_id 无效"}), 400
    if pid <= 0:
        return jsonify({"message": "缺少 project_id"}), 400
    params = {"project_id": pid}
    for k in (
        "registration_country",
        "registration_type",
        "registration_component",
        "project_form",
    ):
        v = (request.args.get(k) or "").strip()
        if v:
            params[k] = v
    org_id, _ = resolve_org_collection_for_integration()
    data, up_err = upstream_get_json(
        "api/integration/translation/kb-query-extra",
        params=params,
        read_timeout_seconds=20,
        organization_id=org_id,
    )
    if up_err:
        return jsonify({"message": up_err}), 502
    return jsonify({"ok": True, "kbQueryExtra": (data or {}).get("kb_query_extra") or ""})


@translation_bp.get("/api/upload-name")
def api_translate_upload_name():
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


def _enforce_translation_stable(target_lang: str, file_count: int) -> Optional[str]:
    if target_lang not in _VALID_LANGS:
        return f"target_lang 必须是 {list(_VALID_LANGS)}"
    if file_count <= 0:
        return "至少需要 1 个文件"
    if file_count > _MAX_FILES_PER_JOB:
        return (
            f"单次最多 {_MAX_FILES_PER_JOB} 个文件，当前 {file_count} 个；请分批"
        )
    return None


def _apply_upstream_status(job: TranslationJob, data: dict) -> None:
    res = data.get("result") if isinstance(data.get("result"), dict) else None

    def _on_succeeded(_data: dict) -> None:
        if not isinstance(res, dict):
            return
        if isinstance(res.get("out_files"), list):
            job.out_file_names_json = [str(x) for x in res["out_files"] if str(x).strip()]
        if bool(res.get("translation_empty")):
            job.status = "failed"
            failed = res.get("failed_files") or []
            top_msg = ""
            if isinstance(failed, list) and failed:
                top_msg = "；".join(
                    f"{x.get('file', '')}: {x.get('error', '')}"
                    for x in failed
                    if isinstance(x, dict)
                )[:1000]
            job.error_summary = safe_truncate(
                "翻译失败：所有文件译文为空。" + (f" 主因：{top_msg}" if top_msg else ""),
                4000,
            )
            if not (job.message or "").strip():
                job.message = "翻译失败"

    apply_upstream_job_fields(job, data, on_succeeded=_on_succeeded)
    db.session.add(job)
    db.session.commit()


@translation_bp.route("/")
def translate_page():
    from ._integration_common import integration_html_access_wall

    blocked = integration_html_access_wall(
        gate_description="请输入访问密码以进入文档翻译（超级管理员无需账号登录）。",
    )
    if blocked is not None:
        return blocked
    from ._integration_common import (
        integration_scope_from_request,
        manual_upload_only_from_request,
    )

    scope = integration_scope_from_request()
    return render_template(
        "translate.html",
        manual_upload_only=manual_upload_only_from_request(),
        integration_scope=scope,
    )


@translation_bp.post("/api/jobs")
def api_translate_create_job():
    err = login_wall()
    if err:
        return err
    base = integration_api_base()
    if not base:
        return jsonify({"message": msg_upstream_not_configured_env()}), 500

    payload_str = (request.form.get("payload") or "").strip()
    if not payload_str:
        return jsonify({"message": "payload 不能为空"}), 400
    try:
        payload_obj = json.loads(payload_str)
        if not isinstance(payload_obj, dict):
            raise ValueError("payload 必须是 JSON 对象")
    except Exception as e:  # noqa: BLE001
        return jsonify({"message": f"payload 解析失败：{e}"}), 400

    target_lang = (payload_obj.get("target_lang") or "en").strip().lower()
    if target_lang not in _VALID_LANGS:
        return jsonify({"message": f"target_lang 必须是 {list(_VALID_LANGS)}"}), 400
    payload_obj["target_lang"] = target_lang

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

    explicit_org = str(
        payload_obj.get("organizationId") or payload_obj.get("organization_id") or ""
    ).strip()
    try:
        org_id, resolved_collection = resolve_org_collection_for_integration(
            preferred_collection=str(payload_obj.get("collection") or "regulations"),
            explicit_organization_id=explicit_org or None,
            upload_ids=upload_ids if has_task_source else None,
        )
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    payload_obj["collection"] = resolved_collection
    payload_obj["organizationId"] = org_id

    resolved: list[tuple[str, bytes, str]] = []
    if has_task_source:
        from .draft_generation_routes import _base_doc_bytes_from_upload, _template_display_filename

        for uid in upload_ids:
            rec = UploadRecord.query.get(uid)
            if not rec or not upload_record_visible_to_user(rec):
                continue
            try:
                blob, _name = _base_doc_bytes_from_upload(rec)
            except Exception:
                continue
            if not blob:
                continue
            disp = _template_display_filename(rec) or rec.file_name or f"task_{uid}.docx"
            resolved.append((disp, blob, rec.id))
    else:
        raw_items: list[tuple[str, bytes]] = []
        for f in uploaded_files:
            raw_name = (f.filename or "").strip() or "upload.bin"
            data = f.read()
            if not data:
                continue
            raw_items.append((raw_name, data))
        from .archive_expand import expand_translation_blobs

        for name, blob in expand_translation_blobs(raw_items):
            resolved.append((name, blob, ""))

    if not resolved:
        return jsonify({"message": "未能取到任何可翻译文件"}), 400

    # 扩展名校验（支持 zip/tar 压缩包，解压后须为可译格式）
    for disp, _blob, _uid in resolved:
        ext = Path(disp).suffix.lower()
        if ext not in _SUPPORTED_EXTS:
            return jsonify(
                {
                    "message": (
                        f"不支持翻译该格式：{disp}（支持 {list(_SUPPORTED_EXTS)}；"
                        f"压缩包 {list(_UPLOAD_ARCHIVE_EXTS)} 会自动解压）"
                    )
                }
            ), 400

    err_msg = _enforce_translation_stable(target_lang, len(resolved))
    if err_msg:
        return jsonify({"message": err_msg}), 400

    provider = str(payload_obj.get("provider") or "").strip() or None
    key_err = personal_llm_key_wall(provider=provider)
    if key_err:
        return key_err

    display_map: dict[str, str] = {}
    upload_id_map: dict[str, str] = {}
    files_to_upload: list[tuple[str, tuple[str, bytes, str]]] = []
    used: set[str] = set()
    for disp, blob, uid in resolved:
        cand = disp
        i = 1
        while cand in used:
            stem, dot, ext = (disp or "upload.bin").rpartition(".")
            cand = f"{stem}__{i}.{ext}" if dot else f"{disp}_{i}"
            i += 1
        used.add(cand)
        display_map[cand] = disp
        if uid:
            upload_id_map[cand] = uid
        files_to_upload.append(("input_files", (cand, blob, "application/octet-stream")))

    payload_obj["display_name_map"] = display_map
    if upload_id_map:
        payload_obj["aiword_upload_id_map"] = upload_id_map
    payload_obj["aiword_user_id"] = str(session.get("user_id") or "")

    uid_session = str(session.get("user_id") or "")
    job_scope = integration_scope_from_request()
    local_job = TranslationJob(
        user_id=uid_session,
        organization_id=(org_id or None),
        status="pending",
        progress=0.0,
        target_lang=target_lang,
        collection=resolved_collection,
        source=("task" if has_task_source else "manual"),
        integration_scope=job_scope,
        upload_ids_json=(list(upload_ids) if has_task_source else None),
        payload_snapshot_json={
            k: payload_obj.get(k)
            for k in (
                "target_lang",
                "collection",
                "use_kb",
                "provider",
                "company_overrides",
                "kb_query_extra",
            )
        },
        message="提交中…",
    )
    db.session.add(local_job)
    db.session.commit()

    url = f"{base}/api/integration/translation/jobs"
    hdrs = upstream_headers(for_multipart=True, organization_id=org_id)
    hdrs.update(client_llm_headers_for_session(provider=provider))
    try:
        r = requests.post(
            url,
            data={"payload": json.dumps(payload_obj, ensure_ascii=False)},
            files=files_to_upload,
            headers=hdrs,
            timeout=integration_requests_timeout(read_seconds=_translation_timeout()),
        )
    except requests.RequestException as e:
        local_job.status = "failed"
        local_job.message = "提交上游失败"
        local_job.error_summary = safe_truncate(str(e), 4000)
        db.session.commit()
        return jsonify({"message": msg_upstream_submit_failed(e)}), 502

    if r.status_code != 200:
        local_job.status = "failed"
        local_job.message = f"上游 HTTP {r.status_code}"
        local_job.error_summary = safe_truncate(r.text, 4000)
        db.session.commit()
        return jsonify({"message": msg_upstream_http(r.status_code), **api_debug_fields(detail=r.text[:2000])}), 502
    try:
        upstream = r.json()
    except Exception:
        local_job.status = "failed"
        local_job.message = "上游响应非 JSON"
        db.session.commit()
        return jsonify({"message": msg_upstream_not_json()}), 502
    upstream_id = (upstream.get("job_id") or "").strip()
    if not upstream_id:
        local_job.status = "failed"
        local_job.message = "上游未返回 job_id"
        db.session.commit()
        return jsonify({"message": msg_upstream_no_job_id(), **api_debug_fields(detail=upstream)}), 502

    local_job.upstream_job_id = upstream_id
    local_job.status = (upstream.get("status") or "queued").strip().lower() or "queued"
    local_job.message = "已提交，等待处理…"
    db.session.commit()

    resp_body: dict[str, Any] = {
        "ok": True,
        "localJobId": local_job.id,
        "upstreamJobId": upstream_id,
        "targetLang": target_lang,
    }
    if upstream.get("provider_note"):
        resp_body["providerNote"] = upstream.get("provider_note")
    if upstream.get("effective_provider"):
        resp_body["effectiveProvider"] = upstream.get("effective_provider")
    return jsonify(resp_body)


@translation_bp.get("/api/jobs/<local_id>/status")
def api_translate_status(local_id: str):
    err = login_wall()
    if err:
        return err
    job = TranslationJob.query.get(local_id)
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
                "message": sanitize_integration_message(job.message),
                "error": job.error_summary or None,
            }
        )
    base = integration_api_base()
    if not base:
        return jsonify({"message": msg_upstream_not_configured()}), 500
    url = f"{base}/api/integration/translation/jobs/{job.upstream_job_id}"
    org_id = str(getattr(job, "organization_id", "") or "").strip()
    try:
        r = requests.get(
            url,
            headers=upstream_headers(for_multipart=False, organization_id=org_id),
            timeout=integration_requests_timeout(
                read_seconds=min(60, _translation_timeout())
            ),
        )
    except requests.RequestException as e:
        return jsonify(
            {
                "ok": True,
                "localJobId": job.id,
                "status": job.status,
                "progress": job.progress or 0.0,
                "message": sanitize_integration_message(job.message),
                "error": msg_upstream_sync_failed(e),
            }
        )
    if r.status_code != 200:
        return jsonify(
            {
                "ok": True,
                "localJobId": job.id,
                "status": job.status,
                "progress": job.progress or 0.0,
                "message": sanitize_integration_message(job.message),
                "error": msg_upstream_http(r.status_code),
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
                "message": sanitize_integration_message(job.message),
                "error": msg_upstream_not_json(),
            }
        )

    _apply_upstream_status(job, data)
    return jsonify(
        {
            "ok": True,
            "localJobId": job.id,
            "upstreamJobId": job.upstream_job_id,
            "status": job.status,
            "progress": job.progress or 0.0,
            "message": sanitize_integration_message(job.message),
            "error": job.error_summary or None,
            "errorSummary": job.error_summary or None,
            "result": (data.get("result") if isinstance(data, dict) else None),
            "outFiles": list(job.out_file_names_json or []),
        }
    )


def _translation_job_has_local_zip(job: TranslationJob) -> bool:
    p = (job.local_zip_path or "").strip()
    return bool(p and Path(p).is_file())


@translation_bp.get("/api/jobs/<local_id>/download")
def api_translate_download(local_id: str):
    err = login_wall()
    if err:
        return err
    job = TranslationJob.query.get(local_id)
    if not job:
        return jsonify({"message": "未找到任务"}), 404
    if job.user_id != str(session.get("user_id") or ""):
        return jsonify({"message": "无权限"}), 403
    if _translation_job_has_local_zip(job):
        return send_file(
            job.local_zip_path,
            as_attachment=True,
            download_name=f"translation_{job.id}.zip",
            mimetype="application/zip",
        )
    base = integration_api_base()
    if not base or not job.upstream_job_id:
        return jsonify({"message": msg_upstream_not_ready()}), 400
    url = f"{base}/api/integration/translation/jobs/{job.upstream_job_id}/download"
    org_id = str(getattr(job, "organization_id", "") or "").strip()
    try:
        r = requests.get(
            url,
            headers=upstream_headers(for_multipart=False, organization_id=org_id),
            timeout=integration_requests_timeout(read_seconds=_translation_timeout()),
            stream=False,
        )
    except requests.RequestException as e:
        return jsonify({"message": f"代理下载失败：{e}"}), 502
    if r.status_code != 200:
        return jsonify({"message": msg_upstream_http(r.status_code), **api_debug_fields(detail=r.text[:1000])}), 502
    out_dir = Path(current_app.config.get("OUTPUT_FOLDER") or "outputs") / "translation_zips"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    out_path = out_dir / f"{local_id}.zip"
    try:
        out_path.write_bytes(r.content)
        job.local_zip_path = str(out_path.resolve())
        db.session.commit()
    except OSError:
        return send_file(
            io.BytesIO(r.content),
            as_attachment=True,
            download_name=f"translation_{job.id}.zip",
            mimetype="application/zip",
        )
    return send_file(
        str(out_path),
        as_attachment=True,
        download_name=f"translation_{job.id}.zip",
        mimetype="application/zip",
    )


@translation_bp.get("/api/jobs")
def api_translate_jobs_list():
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
    q = TranslationJob.query.filter_by(user_id=uid)
    q = integration_scope_list_filter(q, TranslationJob, scope)
    q = integration_organization_list_filter(q, TranslationJob)
    total = q.count()
    rows = (
        q
        .order_by(desc(TranslationJob.created_at))
        .offset(offset)
        .limit(page_size)
        .all()
    )
    out = []
    for j in rows:
        has_local_zip = _translation_job_has_local_zip(j)
        st = (j.status or "").strip().lower()
        can_download = st == "succeeded" and (has_local_zip or bool(j.upstream_job_id))
        out.append(
            {
                "id": j.id,
                "status": j.status,
                "progress": j.progress or 0.0,
                "targetLang": j.target_lang,
                "source": j.source,
                "message": j.message or "",
                "error": j.error_summary or None,
                "uploadIds": list(j.upload_ids_json or []),
                "outFiles": list(j.out_file_names_json or []),
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


@translation_bp.post("/api/correct/jobs")
def api_translate_correct_create_job():
    err = login_wall()
    if err:
        return err
    base = integration_api_base()
    if not base:
        return jsonify({"message": msg_upstream_not_configured_env()}), 500

    payload_str = (request.form.get("payload") or "").strip()
    if not payload_str:
        return jsonify({"message": "payload 不能为空"}), 400
    try:
        payload_obj = json.loads(payload_str)
        if not isinstance(payload_obj, dict):
            raise ValueError("payload 必须是 JSON 对象")
    except Exception as e:  # noqa: BLE001
        return jsonify({"message": f"payload 解析失败：{e}"}), 400

    target_lang = (payload_obj.get("target_lang") or "en").strip().lower()
    if target_lang not in _VALID_LANGS:
        return jsonify({"message": f"target_lang 必须是 {list(_VALID_LANGS)}"}), 400
    payload_obj["target_lang"] = target_lang

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

    explicit_org = str(
        payload_obj.get("organizationId") or payload_obj.get("organization_id") or ""
    ).strip()
    try:
        org_id, resolved_collection = resolve_org_collection_for_integration(
            preferred_collection=str(payload_obj.get("collection") or "regulations"),
            explicit_organization_id=explicit_org or None,
            upload_ids=upload_ids if has_task_source else None,
        )
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    payload_obj["collection"] = resolved_collection
    payload_obj["organizationId"] = org_id

    resolved: list[tuple[str, bytes, str]] = []
    if has_task_source:
        from .draft_generation_routes import _base_doc_bytes_from_upload, _template_display_filename

        for uid in upload_ids:
            rec = UploadRecord.query.get(uid)
            if not rec or not upload_record_visible_to_user(rec):
                continue
            try:
                blob, _name = _base_doc_bytes_from_upload(rec)
            except Exception:
                continue
            if not blob:
                continue
            disp = _template_display_filename(rec) or rec.file_name or f"task_{uid}.docx"
            resolved.append((disp, blob, rec.id))
    else:
        for f in uploaded_files:
            raw_name = (f.filename or "").strip() or "upload.bin"
            data = f.read()
            if not data:
                continue
            resolved.append((raw_name, data, ""))

    if not resolved:
        return jsonify({"message": "未能取到任何可校正文件"}), 400
    if len(resolved) > _MAX_CORRECT_FILES_PER_JOB:
        return jsonify({"message": f"单次最多 {_MAX_CORRECT_FILES_PER_JOB} 个文件，当前 {len(resolved)} 个"}), 400

    for disp, _blob, _uid in resolved:
        ext = Path(disp).suffix.lower()
        if ext not in set(_SUPPORTED_EXTS).union({".zip"}):
            return jsonify(
                {
                    "message": (
                        f"不支持校正该格式：{disp}（仅支持 {list(_SUPPORTED_EXTS) + ['.zip']}）"
                    )
                }
            ), 400

    provider = str(payload_obj.get("provider") or "").strip() or None
    key_err = personal_llm_key_wall(provider=provider)
    if key_err:
        return key_err

    display_map: dict[str, str] = {}
    upload_id_map: dict[str, str] = {}
    files_to_upload: list[tuple[str, tuple[str, bytes, str]]] = []
    used: set[str] = set()
    for disp, blob, uid in resolved:
        cand = disp
        i = 1
        while cand in used:
            stem, dot, ext = (disp or "upload.bin").rpartition(".")
            cand = f"{stem}__{i}.{ext}" if dot else f"{disp}_{i}"
            i += 1
        used.add(cand)
        display_map[cand] = disp
        if uid:
            upload_id_map[cand] = uid
        files_to_upload.append(("input_files", (cand, blob, "application/octet-stream")))

    payload_obj["display_name_map"] = display_map
    if upload_id_map:
        payload_obj["aiword_upload_id_map"] = upload_id_map
    payload_obj["aiword_user_id"] = str(session.get("user_id") or "")

    uid_session = str(session.get("user_id") or "")
    job_scope = integration_scope_from_request()
    local_job = TranslationJob(
        user_id=uid_session,
        organization_id=(org_id or None),
        status="pending",
        progress=0.0,
        target_lang=target_lang,
        collection=resolved_collection,
        source=("task_correct" if has_task_source else "manual_correct"),
        integration_scope=job_scope,
        upload_ids_json=(list(upload_ids) if has_task_source else None),
        payload_snapshot_json={
            k: payload_obj.get(k)
            for k in (
                "target_lang",
                "collection",
                "use_kb",
                "provider",
                "manual_rules",
                "save_glossary",
                "kb_query_extra",
            )
        },
        message="提交中…",
    )
    db.session.add(local_job)
    db.session.commit()

    url = f"{base}/api/integration/translation/correct/jobs"
    hdrs = upstream_headers(for_multipart=True, organization_id=org_id)
    hdrs.update(client_llm_headers_for_session(provider=provider))
    try:
        r = requests.post(
            url,
            data={"payload": json.dumps(payload_obj, ensure_ascii=False)},
            files=files_to_upload,
            headers=hdrs,
            timeout=integration_requests_timeout(read_seconds=_translation_timeout()),
        )
    except requests.RequestException as e:
        local_job.status = "failed"
        local_job.message = "提交上游失败"
        local_job.error_summary = safe_truncate(str(e), 4000)
        db.session.commit()
        return jsonify({"message": msg_upstream_submit_failed(e)}), 502

    if r.status_code != 200:
        local_job.status = "failed"
        local_job.message = f"上游 HTTP {r.status_code}"
        local_job.error_summary = safe_truncate(r.text, 4000)
        db.session.commit()
        return jsonify({"message": msg_upstream_http(r.status_code), **api_debug_fields(detail=r.text[:2000])}), 502
    try:
        upstream = r.json()
    except Exception:
        local_job.status = "failed"
        local_job.message = "上游响应非 JSON"
        db.session.commit()
        return jsonify({"message": msg_upstream_not_json()}), 502
    upstream_id = (upstream.get("job_id") or "").strip()
    if not upstream_id:
        local_job.status = "failed"
        local_job.message = "上游未返回 job_id"
        db.session.commit()
        return jsonify({"message": msg_upstream_no_job_id(), **api_debug_fields(detail=upstream)}), 502

    local_job.upstream_job_id = upstream_id
    local_job.status = (upstream.get("status") or "queued").strip().lower() or "queued"
    local_job.message = "已提交，等待处理…"
    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "localJobId": local_job.id,
            "upstreamJobId": upstream_id,
            "targetLang": target_lang,
        }
    )


@translation_bp.get("/api/correct/jobs/<local_id>/status")
def api_translate_correct_status(local_id: str):
    # 复用同一张表与状态更新逻辑
    return api_translate_status(local_id)


@translation_bp.get("/api/correct/jobs/<local_id>/download")
def api_translate_correct_download(local_id: str):
    err = login_wall()
    if err:
        return err
    job = TranslationJob.query.get(local_id)
    if not job:
        return jsonify({"message": "未找到任务"}), 404
    if job.user_id != str(session.get("user_id") or ""):
        return jsonify({"message": "无权限"}), 403
    if _translation_job_has_local_zip(job):
        return send_file(
            job.local_zip_path,
            as_attachment=True,
            download_name=f"translation_correct_{job.id}.zip",
            mimetype="application/zip",
        )
    base = integration_api_base()
    if not base or not job.upstream_job_id:
        return jsonify({"message": msg_upstream_not_ready()}), 400
    url = f"{base}/api/integration/translation/correct/jobs/{job.upstream_job_id}/download"
    org_id = str(getattr(job, "organization_id", "") or "").strip()
    try:
        r = requests.get(
            url,
            headers=upstream_headers(for_multipart=False, organization_id=org_id),
            timeout=integration_requests_timeout(read_seconds=_translation_timeout()),
            stream=False,
        )
    except requests.RequestException as e:
        return jsonify({"message": f"代理下载失败：{e}"}), 502
    if r.status_code != 200:
        return jsonify({"message": msg_upstream_http(r.status_code), **api_debug_fields(detail=r.text[:1000])}), 502
    out_dir = Path(current_app.config.get("OUTPUT_FOLDER") or "outputs") / "translation_zips"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    out_path = out_dir / f"{local_id}.zip"
    try:
        out_path.write_bytes(r.content)
        job.local_zip_path = str(out_path.resolve())
        db.session.commit()
    except OSError:
        return send_file(
            io.BytesIO(r.content),
            as_attachment=True,
            download_name=f"translation_correct_{job.id}.zip",
            mimetype="application/zip",
        )
    return send_file(
        str(out_path),
        as_attachment=True,
        download_name=f"translation_correct_{job.id}.zip",
        mimetype="application/zip",
    )
