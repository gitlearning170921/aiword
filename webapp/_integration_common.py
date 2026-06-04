# -*- coding: utf-8 -*-
"""aiword ↔ aicheckword 集成的公共薄基础设施。

抽出 ``audit_routes`` / ``audit_modify_routes`` / ``translation_routes`` 的同构片段：
- 取 aicheckword API base URL（与初稿统一）
- 取上游 Bearer / Integration-Secret 头
- 从已登录 session 透传"客户 LLM"头（仅在用户在初稿页保存过个人 Key 时才会有值）
- 标准登录拦截
- 上游读/连接超时
- "稳态模式"提示文案常量

这些是只读拷贝级辅助，不修改 ``draft_generation_routes.py`` 中已有的等价实现，
避免初稿模块的回归。
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

import requests
from flask import current_app, jsonify, session

from .app_settings import get_setting


# 与 draft_generation_routes 保持同步的"读超时上限"
INTEGRATION_READ_TIMEOUT_MAX_SECONDS = 72 * 3600


def integration_api_base() -> str:
    raw = (
        get_setting("AICHECKWORD_DRAFT_API_BASE", default="")
        or get_setting("QUIZ_API_BASE_URL", default="")
        or str(current_app.config.get("QUIZ_API_BASE_URL") or "")
    ).strip()
    return raw.rstrip("/")


def integration_read_timeout(setting_key: str, default: int = 600) -> int:
    raw = (get_setting(setting_key, default=str(default)) or str(default)).strip()
    try:
        v = int(raw)
    except ValueError:
        v = default
    return max(30, min(INTEGRATION_READ_TIMEOUT_MAX_SECONDS, v))


def integration_connect_timeout() -> int:
    raw = (get_setting("AICHECKWORD_DRAFT_CONNECT_TIMEOUT_SECONDS", default="8") or "8").strip()
    try:
        v = int(raw)
    except ValueError:
        v = 8
    return max(2, min(120, v))


def integration_requests_timeout(read_seconds: int) -> tuple[int, int]:
    return (integration_connect_timeout(), max(5, int(read_seconds)))


def upstream_headers(*, for_multipart: bool = False) -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/json"}
    bearer = (get_setting("QUIZ_API_BEARER_TOKEN") or "").strip()
    secret = (get_setting("QUIZ_API_SECRET") or "").strip()
    if bearer:
        h["Authorization"] = f"Bearer {bearer}"
    if secret:
        h["X-Integration-Secret"] = secret
    if not for_multipart:
        h["Content-Type"] = "application/json; charset=utf-8"
    return h


def login_wall():
    """与 draft 模块一致：未登录返回 401 JSON。"""
    if not session.get("user_id"):
        return jsonify({"message": "请先登录", "needsLogin": True}), 401
    return None


def fetch_upstream_common_bootstrap(
    collection: str,
    *,
    read_timeout_seconds: int = 30,
) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
    """拉取 aicheckword ``GET /api/integration/common/bootstrap``。"""
    base = integration_api_base()
    if not base:
        return None, "未配置 AICHECKWORD_DRAFT_API_BASE / QUIZ_API_BASE_URL"
    coll = (collection or "regulations").strip() or "regulations"
    try:
        r = requests.get(
            f"{base}/api/integration/common/bootstrap",
            params={"collection": coll},
            headers=upstream_headers(for_multipart=False),
            timeout=integration_requests_timeout(read_seconds=read_timeout_seconds),
        )
    except requests.RequestException as e:
        return None, f"上游请求失败：{e}"
    if r.status_code != 200:
        return None, f"上游 HTTP {r.status_code}"
    try:
        data = r.json()
    except Exception:
        return None, "上游响应非 JSON"
    if not isinstance(data, dict) or not data.get("ok"):
        return None, "上游 bootstrap 异常"
    return data, None


def integration_collection_rows() -> list[dict[str, str]]:
    """知识库下拉（与初稿页一致）。"""
    raw = (get_setting("AICHECKWORD_DRAFT_COLLECTION_IDS", default="") or "").strip()
    if raw:
        ids = [x.strip() for x in raw.split(",") if x.strip()]
    else:
        ids = ["regulations"]
    rows: list[dict[str, str]] = []
    for cid in ids:
        if cid == "regulations":
            lab = "法规/通用知识库（regulations）"
        else:
            lab = f"知识库「{cid}」"
        rows.append({"id": cid, "label": lab})
    return rows


def fetch_draft_page_bootstrap(
    collection: str,
    *,
    base_case_id: Optional[int] = None,
    template_names: Optional[list[str]] = None,
    read_timeout_seconds: int = 60,
) -> tuple[Optional[dict[str, Any]], Optional[str], Optional[dict[str, Any]]]:
    """拉取 aicheckword ``GET /api/integration/draft/page-bootstrap``。

    返回 (bootstrap_data, error, full_upstream_body)。
    """
    params: dict[str, Any] = {"collection": (collection or "regulations").strip() or "regulations"}
    if base_case_id is not None and int(base_case_id) > 0:
        params["base_case_id"] = int(base_case_id)
    if template_names:
        params["templates"] = [str(x).strip() for x in template_names if str(x).strip()]
    base = integration_api_base()
    if not base:
        return None, "未配置 AICHECKWORD_DRAFT_API_BASE / QUIZ_API_BASE_URL", None
    url = f"{base.rstrip('/')}/api/integration/draft/page-bootstrap"
    try:
        r = requests.get(
            url,
            params=params,
            headers=upstream_headers(for_multipart=False),
            timeout=integration_requests_timeout(read_seconds=read_timeout_seconds),
        )
    except requests.RequestException as e:
        return None, f"上游请求失败：{e}", None
    try:
        body = r.json()
    except Exception:
        return None, f"上游返回非 JSON（HTTP {r.status_code}）", None
    if r.status_code >= 400:
        return None, f"上游 HTTP {r.status_code}", body if isinstance(body, dict) else None
    if not isinstance(body, dict) or not body.get("ok"):
        return None, (body.get("detail") or body.get("message") or "上游 page-bootstrap 异常") if isinstance(body, dict) else "上游异常", body
    data = body.get("data")
    if not isinstance(data, dict):
        return None, "上游 page-bootstrap 无 data", body
    return data, None, body


def build_integration_bootstrap_payload(collection: str, *, read_timeout: int = 30) -> dict[str, Any]:
    """合并上游 common/bootstrap 与本地 collections 配置。"""
    data, err = fetch_upstream_common_bootstrap(collection, read_timeout_seconds=read_timeout)
    if err:
        return {"ok": False, "message": err}
    assert data is not None
    return {
        "ok": True,
        "metaError": None,
        "collection": (data.get("collection") or collection or "regulations"),
        "collections": integration_collection_rows(),
        "projects": data.get("projects") or [],
        "cases": data.get("cases") or [],
        "documentLanguages": data.get("documentLanguages") or [],
        "registrationCountries": data.get("registrationCountries") or [],
        "registrationTypes": data.get("registrationTypes") or [],
        "registrationComponents": data.get("registrationComponents") or [],
        "projectForms": data.get("projectForms") or [],
        "targetLangDefault": data.get("targetLangDefault") or "en",
        "supportedTargetLangs": data.get("supportedTargetLangs") or [],
        "companyConfig": data.get("companyConfig") if isinstance(data.get("companyConfig"), dict) else {},
    }


def client_llm_headers_for_session() -> dict[str, str]:
    """从已登录用户的 UserLlmCredential 取个人 LLM 头（与 draft 模块同源逻辑）。

    复用 draft_generation_routes 中已有实现，避免新增加密/解密重复路径。
    若用户未配置个人 Key，返回空 dict（上游回退系统设置）。
    """
    uid = session.get("user_id")
    if not uid:
        return {}
    try:
        from .draft_generation_routes import _client_llm_headers, _draft_personal_key_headers
    except Exception:
        return {}
    headers: dict[str, str] = {}
    try:
        headers.update(_client_llm_headers(str(uid)) or {})
    except Exception:
        headers = {}
    try:
        headers.update(_draft_personal_key_headers() or {})
    except Exception:
        pass
    return headers


def upload_record_visible_to_user(rec: Any) -> bool:
    """与页面2 / 初稿一致；公司/项目管理员在 RBAC 生效时只增权。"""
    from .authz import upload_record_visible_to_user as _authz_visible

    return _authz_visible(rec)


def safe_truncate(s: Optional[str], limit: int = 4000) -> str:
    return (s or "")[:limit]


def upstream_get_json(
    path: str,
    *,
    params: Optional[dict[str, Any]] = None,
    read_timeout_seconds: int = 30,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """GET aicheckword integration JSON；返回 (data 子对象, error)。"""
    base = integration_api_base()
    if not base:
        return None, "未配置 AICHECKWORD_DRAFT_API_BASE / QUIZ_API_BASE_URL"
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    try:
        r = requests.get(
            url,
            params=params,
            headers=upstream_headers(for_multipart=False),
            timeout=integration_requests_timeout(read_seconds=read_timeout_seconds),
        )
    except requests.RequestException as e:
        return None, f"上游请求失败：{e}"
    if r.status_code != 200:
        detail = r.text[:500]
        try:
            detail = (r.json() or {}).get("detail") or detail
        except Exception:
            pass
        return None, f"上游 HTTP {r.status_code}：{detail}"
    try:
        body = r.json()
    except Exception:
        return None, "上游响应非 JSON"
    if not isinstance(body, dict) or not body.get("ok"):
        return None, (body.get("detail") or body.get("message") or "上游失败") if isinstance(body, dict) else "上游失败"
    data = body.get("data")
    return (data if isinstance(data, dict) else body), None


def upstream_post_json(
    path: str,
    json_body: dict[str, Any],
    *,
    read_timeout_seconds: int = 30,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """POST aicheckword integration JSON；返回 (data 子对象, error)。"""
    base = integration_api_base()
    if not base:
        return None, "未配置 AICHECKWORD_DRAFT_API_BASE / QUIZ_API_BASE_URL"
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    try:
        r = requests.post(
            url,
            headers=upstream_headers(for_multipart=False),
            json=json_body,
            timeout=integration_requests_timeout(read_seconds=read_timeout_seconds),
        )
    except requests.RequestException as e:
        return None, f"上游请求失败：{e}"
    if r.status_code != 200:
        detail = r.text[:500]
        try:
            detail = (r.json() or {}).get("detail") or detail
        except Exception:
            pass
        return None, f"上游 HTTP {r.status_code}：{detail}"
    try:
        body = r.json()
    except Exception:
        return None, "上游响应非 JSON"
    if not isinstance(body, dict) or not body.get("ok"):
        return None, (body.get("detail") or body.get("message") or "上游失败") if isinstance(body, dict) else "上游失败"
    data = body.get("data")
    return (data if isinstance(data, dict) else body), None


def fetch_audit_prompt_defaults_upstream() -> dict[str, str]:
    data, err = upstream_get_json(
        "api/integration/audit/prompt-defaults",
        read_timeout_seconds=15,
    )
    if err or not data:
        return {}
    return {
        "system_prompt": str(data.get("system_prompt") or "").strip(),
        "user_prompt": str(data.get("user_prompt") or "").strip(),
        "extra_instructions": str(data.get("extra_instructions") or "").strip(),
    }


def enrich_audit_payload_from_upstream(payload_obj: dict[str, Any]) -> None:
    """提交审核前补全提示词与项目英文字段（与 Streamlit 默认一致）。"""
    if not isinstance(payload_obj, dict):
        return
    prompts = fetch_audit_prompt_defaults_upstream()
    for k in ("system_prompt", "user_prompt", "extra_instructions"):
        if not str(payload_obj.get(k) or "").strip() and prompts.get(k):
            payload_obj[k] = prompts[k]
    pid = payload_obj.get("project_id")
    try:
        pid_int = int(pid or 0)
    except (TypeError, ValueError):
        pid_int = 0
    if pid_int > 0:
        fields, err = upstream_get_json(
            f"api/integration/audit/projects/{pid_int}/review-fields",
            read_timeout_seconds=15,
        )
        if fields and not err:
            for k, v in fields.items():
                if v is not None and v != "" and not str(payload_obj.get(k) or "").strip():
                    payload_obj[k] = v
            rc = fields.get("registration_country")
            if rc and not payload_obj.get("registration_country"):
                payload_obj["registration_country"] = rc


def normalize_upstream_job_status(raw: Optional[str]) -> str:
    """把上游/历史任务状态归一为 queued|running|succeeded|failed|pending。"""
    st = (raw or "").strip().lower()
    if st in ("succeeded", "success", "successful", "completed", "complete", "done", "finished"):
        return "succeeded"
    if st in ("failed", "error", "errored", "cancelled", "canceled", "aborted"):
        return "failed"
    if st in ("queued", "running", "pending"):
        return st
    return st or "running"


def apply_upstream_job_fields(
    job: Any,
    data: dict[str, Any],
    *,
    on_succeeded: Optional[Any] = None,
) -> None:
    """同步 status/progress/message/error；可选在 succeeded 时执行额外逻辑。"""
    st = normalize_upstream_job_status(data.get("status"))
    job.status = st
    try:
        job.progress = float(data.get("progress") or 0.0)
    except (TypeError, ValueError):
        job.progress = 0.0
    job.message = safe_truncate(data.get("message") or "", 4000)
    err = data.get("error")
    if err:
        job.error_summary = safe_truncate(str(err), 4000)
    if st == "succeeded" and callable(on_succeeded):
        on_succeeded(data)


def _job_snapshot_refs_upload(snap: Any, upload_id: str) -> bool:
    if not isinstance(snap, dict) or not upload_id:
        return False
    bu = str(snap.get("base_upload_id") or "").strip()
    if bu and bu == upload_id:
        return True
    bus = snap.get("base_upload_ids")
    if isinstance(bus, list):
        for x in bus:
            if str(x).strip() == upload_id:
                return True
    uids = snap.get("upload_ids")
    if isinstance(uids, list):
        for x in uids:
            if str(x).strip() == upload_id:
                return True
    return False


def _valid_aicheckword_project_id(raw: Any) -> Optional[int]:
    try:
        n = int(raw or 0)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def resolve_aicheckword_project_id_for_upload(
    upload_id: str,
    *,
    user_id: Optional[str] = None,
) -> Optional[int]:
    """从本地上次初稿/审核/翻译任务推断 aicheckword 项目 ID（整数）。"""
    from .models import AuditJob, DraftGenerationJob, TranslationJob

    uid = (upload_id or "").strip()
    if not uid:
        return None
    uid_session = (user_id or "").strip() or None

    def _scan_draft_jobs() -> Optional[int]:
        q = DraftGenerationJob.query
        if uid_session:
            q = q.filter_by(user_id=uid_session)
        for job in q.order_by(DraftGenerationJob.created_at.desc()).limit(50).all():
            snap = (
                job.payload_snapshot_json
                if isinstance(job.payload_snapshot_json, dict)
                else {}
            )
            if not _job_snapshot_refs_upload(snap, uid):
                continue
            pid = _valid_aicheckword_project_id(job.project_id)
            if pid:
                return pid
            pid = _valid_aicheckword_project_id(snap.get("project_id"))
            if pid:
                return pid
        return None

    def _scan_audit_jobs() -> Optional[int]:
        q = AuditJob.query
        if uid_session:
            q = q.filter_by(user_id=uid_session)
        for job in q.order_by(AuditJob.created_at.desc()).limit(50).all():
            uids_json = job.upload_ids_json
            matched_upload = isinstance(uids_json, list) and uid in [
                str(x).strip() for x in uids_json
            ]
            snap = (
                job.payload_snapshot_json
                if isinstance(job.payload_snapshot_json, dict)
                else {}
            )
            if not matched_upload and not _job_snapshot_refs_upload(snap, uid):
                continue
            pid = _valid_aicheckword_project_id(snap.get("project_id"))
            if pid:
                return pid
        return None

    def _scan_translation_jobs() -> Optional[int]:
        q = TranslationJob.query
        if uid_session:
            q = q.filter_by(user_id=uid_session)
        for job in q.order_by(TranslationJob.created_at.desc()).limit(50).all():
            uids_json = job.upload_ids_json
            matched_upload = isinstance(uids_json, list) and uid in [
                str(x).strip() for x in uids_json
            ]
            snap = (
                job.payload_snapshot_json
                if isinstance(job.payload_snapshot_json, dict)
                else {}
            )
            if not matched_upload and not _job_snapshot_refs_upload(snap, uid):
                continue
            pid = _valid_aicheckword_project_id(snap.get("project_id"))
            if pid:
                return pid
        return None

    return _scan_draft_jobs() or _scan_audit_jobs() or _scan_translation_jobs()


def build_upload_prefill_payload(upload_id: str) -> tuple[dict[str, Any], int]:
    """从 aiword UploadRecord 组装页面2预填字段（供审核/翻译/审核后修改）。"""
    from flask import session

    from .models import UploadRecord

    uid = (upload_id or "").strip()
    if not uid:
        return {"ok": False, "message": "缺少 upload_id"}, 400
    rec = UploadRecord.query.get(uid)
    if not rec:
        return {"ok": False, "message": "未找到任务"}, 404
    if not upload_record_visible_to_user(rec):
        return {"ok": False, "message": "无权限查看该任务"}, 403
    fn = (
        (getattr(rec, "original_file_name", None) or "").strip()
        or (getattr(rec, "file_name", None) or "").strip()
        or (getattr(rec, "stored_file_name", None) or "").strip()
    )
    product = (getattr(rec, "product", None) or "").strip()
    if not product:
        product = (getattr(rec, "registered_product_name", None) or "").strip()
    acw_pid = resolve_aicheckword_project_id_for_upload(
        uid, user_id=str(session.get("user_id") or "")
    )
    body: dict[str, Any] = {
        "ok": True,
        "uploadId": uid,
        "project_name": (getattr(rec, "project_name", None) or "").strip(),
        "file_name": fn,
        "product": product,
        "country": (getattr(rec, "country", None) or "").strip(),
        "fromPage2": True,
    }
    if acw_pid:
        body["aicheckwordProjectId"] = acw_pid
        body["aicheckword_project_id"] = acw_pid
    return body, 200


def manual_upload_only_from_request() -> bool:
    """页面0 等入口带 ?manual=1 时，集成页隐藏 upload_id(s) 任务带入区。"""
    from flask import request

    v = (request.args.get("manual") or request.args.get("manual_upload") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


INTEGRATION_SCOPE_WORKFLOW = "workflow"
INTEGRATION_SCOPE_PAGE0 = "page0"


def normalize_integration_scope(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if s == INTEGRATION_SCOPE_PAGE0:
        return INTEGRATION_SCOPE_PAGE0
    return INTEGRATION_SCOPE_WORKFLOW


def integration_scope_from_request(*, allow_form: bool = True) -> str:
    """解析当前请求的集成数据域：页面0 手动工具 vs 页面1/2 工作流。"""
    from flask import request

    if allow_form:
        form_scope = (request.form.get("integration_scope") or "").strip()
        if form_scope:
            return normalize_integration_scope(form_scope)
    query_scope = (request.args.get("scope") or "").strip()
    if query_scope:
        return normalize_integration_scope(query_scope)
    if manual_upload_only_from_request():
        return INTEGRATION_SCOPE_PAGE0
    return INTEGRATION_SCOPE_WORKFLOW


def integration_scope_list_filter(q: Any, model: Any, scope: str) -> Any:
    """按 integration_scope 过滤 job 列表；旧数据 NULL 视为 workflow。"""
    from sqlalchemy import or_

    scope = normalize_integration_scope(scope)
    col = getattr(model, "integration_scope", None)
    if col is None:
        return q
    if scope == INTEGRATION_SCOPE_PAGE0:
        return q.filter(col == INTEGRATION_SCOPE_PAGE0)
    return q.filter(or_(col.is_(None), col == "", col == INTEGRATION_SCOPE_WORKFLOW))


def latest_audit_report_id_for_scope(
    user_id: str,
    scope: str = INTEGRATION_SCOPE_PAGE0,
) -> Optional[int]:
    """取指定 scope 下最近一次成功审核的主 report_id（供页面0 审核后修改预填）。"""
    from sqlalchemy import desc

    from .models import AuditJob

    uid = (user_id or "").strip()
    if not uid:
        return None
    q = AuditJob.query.filter_by(user_id=uid, status="succeeded")
    q = integration_scope_list_filter(q, AuditJob, scope)
    for job in q.order_by(desc(AuditJob.created_at)).limit(30).all():
        rids = job.report_ids_json
        if isinstance(rids, list) and rids:
            for rid in reversed(rids):
                try:
                    n = int(rid)
                except (TypeError, ValueError):
                    continue
                if n > 0:
                    return n
        rs = job.reports_summary_json
        if isinstance(rs, list):
            for item in reversed(rs):
                if not isinstance(item, dict):
                    continue
                try:
                    n = int(item.get("report_id") or 0)
                except (TypeError, ValueError):
                    continue
                if n > 0:
                    return n
    return None
