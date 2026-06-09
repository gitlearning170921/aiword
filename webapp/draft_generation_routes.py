# -*- coding: utf-8 -*-
"""文档初稿生成：对接 aicheckword /api/integration/draft/*，用户 LLM 凭据存本地加密表。

初稿 LLM（页面2个人配置）：默认 deepseek / cursor / tongyi；**允许列表与是否须个人 Key**
由 aicheckword ``GET /api/integration/draft/interop-config`` 下发并与本页合并。
``X-Client-Llm-Personal-Keys-Only`` 仅在上游 ``personalKeysOnly`` 为 true 时发送。
说明见 aicheckword ``docs/integration-draft-provider-status.md``。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

from sqlalchemy import desc, or_

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
from werkzeug.utils import secure_filename

from . import db
from .app_settings import get_setting
from ._integration_common import (
    fetch_draft_page_bootstrap,
    integration_collection_rows,
    integration_org_context_payload,
    integration_scope_from_request,
    integration_scope_list_filter,
    integration_organization_list_filter,
    manual_upload_only_from_request,
    resolve_aicheckword_project_id_for_upload,
    resolve_org_collection_for_integration,
    upstream_get_json,
)
from .llm_credential_crypto import decrypt_api_key, encrypt_api_key
from .models import DraftGenerationJob, UploadRecord, UserLlmCredential, now_local

# 上游 HTTP「读超时」配置上限（秒）：提交大 multipart、下载 ZIP 等单请求可等待的最长时间。
# 与前端 draft_gen.js 中轮询墙钟上限保持一致，避免服务端允许 72h 而浏览器约 32min 就判超时。
_DRAFT_READ_TIMEOUT_MAX_SECONDS = 72 * 3600

# 上游 GET /api/integration/draft/interop-config 短缓存（秒）
_INTEROP_CACHE_TTL_SEC = 45.0
_interop_ts: float = 0.0
_interop_data: Optional[dict[str, Any]] = None
_interop_err: str = ""

draft_gen_bp = Blueprint("draft_gen", __name__, url_prefix="/draft-gen")

# 与 aicheckword 初稿集成 API 已做端到端联调的 provider；其余不在初稿页开放。
# 状态说明见 aicheckword 仓库：docs/integration-draft-provider-status.md
AIWORD_DRAFT_LLM_PROVIDERS: tuple[str, ...] = ("deepseek", "cursor", "tongyi")

_DRAFT_LLM_PROVIDER_KEY_ATTR: dict[str, str] = {
    "deepseek": "api_key_encrypted_deepseek",
    "cursor": "api_key_encrypted_cursor",
    "tongyi": "api_key_encrypted_tongyi",
}
_DRAFT_LLM_BASE_ATTR: dict[str, str] = {
    "deepseek": "base_url_deepseek",
    "cursor": "base_url_cursor",
    "tongyi": "base_url_tongyi",
}
_DRAFT_LLM_MODEL_ATTR: dict[str, str] = {
    "deepseek": "model_deepseek",
    "cursor": "model_cursor",
    "tongyi": "model_tongyi",
}


def _base_url_for_provider(row: Optional[UserLlmCredential], provider: str) -> str:
    if not row:
        return ""
    p = (provider or "").strip().lower()
    if p not in AIWORD_DRAFT_LLM_PROVIDERS:
        return ""
    attr = _DRAFT_LLM_BASE_ATTR[p]
    v = getattr(row, attr, None)
    if v and str(v).strip():
        return str(v).strip()
    if (row.provider or "").strip().lower() == p:
        leg = (row.base_url or "").strip()
        if leg:
            return leg
    return ""


def _model_for_provider(row: Optional[UserLlmCredential], provider: str) -> str:
    if not row:
        return ""
    p = (provider or "").strip().lower()
    if p not in AIWORD_DRAFT_LLM_PROVIDERS:
        return ""
    attr = _DRAFT_LLM_MODEL_ATTR[p]
    v = getattr(row, attr, None)
    if v and str(v).strip():
        return str(v).strip()
    if (row.provider or "").strip().lower() == p:
        leg = (row.model or "").strip()
        if leg:
            return leg
    return ""


def _encrypted_key_blob_for_provider(row: UserLlmCredential, provider: str) -> Optional[bytes]:
    """读取某提供方已存密文：优先分栏列，其次兼容旧单列 ``api_key_encrypted``（且 ``row.provider`` 须一致）。"""
    p = (provider or "").strip().lower()
    if p not in AIWORD_DRAFT_LLM_PROVIDERS:
        return None
    attr = _DRAFT_LLM_PROVIDER_KEY_ATTR[p]
    blob = getattr(row, attr, None)
    if blob:
        return blob
    legacy = row.api_key_encrypted
    if legacy and (row.provider or "").strip().lower() == p:
        return legacy
    return None


def _has_usable_stored_key_for_provider(row: Optional[UserLlmCredential], provider: str, *, sk: str) -> bool:
    """与 ``hasApiKey`` 对齐：仅有密文但 ``SECRET_KEY`` 变更导致无法解密时视为未保存，避免误导用户。"""
    if not row:
        return False
    blob = _encrypted_key_blob_for_provider(row, provider)
    if not blob:
        return False
    return bool(decrypt_api_key(sk, blob).strip())


def _decrypt_key_for_provider(row: UserLlmCredential, provider: str, sk: str) -> str:
    blob = _encrypted_key_blob_for_provider(row, provider)
    if not blob:
        return ""
    try:
        return decrypt_api_key(sk, blob).strip()
    except Exception:
        return ""



def _normalized_draft_provider(row: Optional[UserLlmCredential]) -> Optional[str]:
    if not row:
        return None
    p = (row.provider or "").strip().lower()
    if p not in AIWORD_DRAFT_LLM_PROVIDERS:
        return None
    allowed = _effective_allowed_provider_ids_ordered()
    if allowed and p not in allowed:
        return None
    return p


def _normalize_requested_provider(provider: Optional[str]) -> Optional[str]:
    """校验页面/ payload 请求的 provider（须在白名单与 aiword 支持列表内）。"""
    p = (provider or "").strip().lower()
    if p not in AIWORD_DRAFT_LLM_PROVIDERS:
        return None
    allowed = _effective_allowed_provider_ids_ordered()
    if allowed and p not in allowed:
        return None
    return p


def _resolve_submit_provider(
    user_id: str, requested: Optional[str] = None
) -> tuple[Optional[str], str]:
    """初稿提交实际使用的 provider：优先本次请求的 provider（页面下拉），其次库内已保存项。"""
    row = _load_user_credential(user_id)
    saved = _normalized_draft_provider(row) if row else None
    req = _normalize_requested_provider(requested)
    p = req or saved
    if not p:
        return None, "请先在「个人 LLM 设置」中选择提供方（DeepSeek / Cursor / 通义千问）并保存个人 API Key。"
    sk = str(current_app.config.get("SECRET_KEY") or "")
    if row and _has_usable_stored_key_for_provider(row, p, sk=sk):
        return p, ""
    labels = {"deepseek": "DeepSeek", "cursor": "Cursor", "tongyi": "通义千问"}
    if req and saved and req != saved:
        return None, (
            f"当前选择为 {labels.get(req, req)}，但该提供方尚未保存可用的 API Key；"
            f"请填写 Key 并点「保存个人 LLM 设置」，或改回已配置的 {labels.get(saved, saved)}。"
        )
    return None, "请先在「个人 LLM 设置」中保存个人 API Key（与 aicheckword 系统管理员配置无关）。"


def _login_wall():
    from ._integration_common import login_wall

    return login_wall()


def _session_user_id() -> str:
    return str(session.get("user_id") or "")


def _account_user_id_wall():
    """超管仅访问密码、无 user_id 时：只读 API 可用，写入/个人任务须账号登录。"""
    uid = _session_user_id()
    if uid:
        return None, uid
    from .authz import is_page13_super_admin

    if is_page13_super_admin():
        return (
            jsonify(
                {
                    "message": "超级管理员（仅访问密码）请使用账号登录后再保存 LLM 设置或提交/查看个人初稿任务",
                    "needsLogin": True,
                }
            ),
            403,
        ), ""
    return jsonify({"message": "请先登录", "needsLogin": True}), 401, ""


def _upload_record_visible_to_draft_user(rec: UploadRecord) -> bool:
    from ._integration_common import upload_record_visible_to_user

    return upload_record_visible_to_user(rec)


def _auto_bind_base_files_by_target(
    payload_obj: dict[str, Any], base_multipart_names: list[str]
) -> None:
    """
    模板目标名（如「附件3 …docx」）与 Base 上传名（如「3_A0.docx」）不一致时，
    上游 base_bound_targets 为空，易导致路由/锚点上下文错位。单 Base 时自动写入绑定。
    """
    tpl = payload_obj.get("template_file_names")
    if not isinstance(tpl, list) or not tpl:
        return
    bases = [str(x).strip() for x in (base_multipart_names or []) if str(x).strip()]
    if len(bases) != 1:
        return
    base_fn = bases[0]
    bfbt = payload_obj.get("base_files_by_target")
    if not isinstance(bfbt, dict):
        bfbt = {}
    changed = False
    for tn in tpl:
        tns = str(tn).strip()
        if not tns:
            continue
        if (bfbt.get(tns) or "").strip():
            continue
        bfbt[tns] = base_fn
        changed = True
    if changed or bfbt:
        payload_obj["base_files_by_target"] = bfbt


def _enforce_stable_single_target_and_base(
    payload_obj: dict[str, Any], base_multipart_names: list[str]
) -> Optional[str]:
    """稳态模式：仅允许单目标模板 + 单 Base，降低锚点漂移与路由歧义。"""
    tpl_raw = payload_obj.get("template_file_names")
    tpl = [str(x).strip() for x in (tpl_raw or []) if str(x).strip()] if isinstance(tpl_raw, list) else []
    if len(tpl) != 1:
        return "稳态模式要求仅选择 1 个模板文件（当前为 %d 个）。" % len(tpl)
    payload_obj["template_file_names"] = [tpl[0]]

    bases = [str(x).strip() for x in (base_multipart_names or []) if str(x).strip()]
    if len(bases) != 1:
        return "稳态模式要求仅提供 1 个 Base 文件（当前为 %d 个）。" % len(bases)

    bfbt = payload_obj.get("base_files_by_target")
    if not isinstance(bfbt, dict):
        bfbt = {}
    bfbt = {str(k).strip(): str(v).strip() for k, v in bfbt.items() if str(k).strip() and str(v).strip()}
    bfbt[tpl[0]] = bases[0]
    payload_obj["base_files_by_target"] = bfbt
    return None


def _collect_base_upload_record_ids(payload: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    one = payload.get("base_upload_id")
    if one is not None:
        s = str(one).strip()
        if s and s not in seen:
            seen.add(s)
            ordered.append(s)
    many = payload.get("base_upload_ids")
    if isinstance(many, list):
        for x in many:
            s = str(x).strip()
            if s and s not in seen:
                seen.add(s)
                ordered.append(s)
    return ordered


def _template_display_filename(rec: UploadRecord) -> str:
    """初稿/交接展示用文件名（修复乱码，优先 original_file_name）。"""
    from .routes import _normalize_handoff_display_filename

    raw = (getattr(rec, "original_file_name", None) or rec.file_name or "").strip()
    if not raw:
        return ""
    return _normalize_handoff_display_filename(raw)


def _ftp_path_for_display(ftp_path: str, display_name: str) -> str:
    """将 FTP 绝对路径末段替换为可读中文名，便于初稿页展示（不影响实际下载路径）。"""
    fp = (ftp_path or "").strip().replace("\\", "/")
    dn = (display_name or "").strip()
    if not fp:
        return dn
    if not dn:
        return fp
    if "/" in fp:
        return fp.rsplit("/", 1)[0] + "/" + dn
    return dn


def _base_doc_bytes_from_upload(upload: UploadRecord) -> tuple[Optional[bytes], str]:
    """从任务记录取 Base 文档字节；(None, name) 表示无文件（仅链接等）。"""
    from .ftp_store import download_bytes

    fn = (upload.original_file_name or upload.file_name or "base.docx").strip() or "base.docx"
    blob = upload.template_file_blob
    fp = (getattr(upload, "ftp_path", None) or "").strip()
    if fp:
        try:
            return download_bytes(fp), fn
        except Exception:
            if blob:
                return blob, fn
            raise
    if blob:
        return blob, fn
    return None, fn


@draft_gen_bp.get("/api/task-base")
def api_task_base_hint():
    """页面2带入 upload_id 时：返回该任务模板 FTP 路径或 BLOB 回退说明（须登录且任务可见）。"""
    err = _login_wall()
    if err:
        return err
    uid = (request.args.get("upload_id") or "").strip()
    if not uid:
        return jsonify({"message": "缺少 upload_id"}), 400
    rec = UploadRecord.query.get(uid)
    if not rec or not _upload_record_visible_to_draft_user(rec):
        return jsonify({"message": "未找到该任务或无权限"}), 404
    fp = (getattr(rec, "ftp_path", None) or "").strip()
    blob = rec.template_file_blob
    display_fn = _template_display_filename(rec) or (rec.file_name or "").strip()
    if fp:
        return jsonify(
            {
                "ok": True,
                "uploadId": rec.id,
                "fileName": rec.file_name,
                "templateFileName": display_fn or None,
                "ftpPath": fp,
                "ftpPathDisplay": _ftp_path_for_display(fp, display_fn) if display_fn else fp,
                "source": "ftp",
            }
        )
    if blob:
        return jsonify(
            {
                "ok": True,
                "uploadId": rec.id,
                "fileName": rec.file_name,
                "templateFileName": display_fn or None,
                "ftpPath": None,
                "ftpPathDisplay": None,
                "source": "blob",
            }
        )
    return jsonify(
        {
            "ok": True,
            "uploadId": rec.id,
            "fileName": rec.file_name,
            "templateFileName": display_fn or None,
            "ftpPath": None,
            "ftpPathDisplay": None,
            "source": "none",
        }
    )


def _draft_api_base() -> str:
    from ._integration_common import integration_api_base

    return integration_api_base()


def _draft_timeout() -> int:
    raw = (get_setting("AICHECKWORD_DRAFT_TIMEOUT_SECONDS", default="600") or "600").strip()
    try:
        v = int(raw)
    except ValueError:
        v = 600
    return max(30, min(_DRAFT_READ_TIMEOUT_MAX_SECONDS, v))


def _draft_connect_timeout_seconds() -> int:
    """与读超时分离：上游 TCP 不可达时尽快失败，减轻与其它进程一并停止时的拖尾。"""
    raw = (get_setting("AICHECKWORD_DRAFT_CONNECT_TIMEOUT_SECONDS", default="8") or "8").strip()
    try:
        v = int(raw)
    except ValueError:
        v = 8
    return max(2, min(120, v))


def _draft_requests_timeout(*, read_seconds: int) -> tuple[int, int]:
    return (_draft_connect_timeout_seconds(), max(5, int(read_seconds)))


def _refresh_upstream_interop_if_stale(*, force: bool = False) -> None:
    """拉取 aicheckword interop-config，写入模块级缓存。"""
    global _interop_ts, _interop_data, _interop_err
    now = time.monotonic()
    if (
        not force
        and _interop_data is not None
        and (now - _interop_ts) < _INTEROP_CACHE_TTL_SEC
    ):
        return
    base = _draft_api_base()
    if not base:
        _interop_ts = now
        _interop_data = None
        _interop_err = "未配置 AICHECKWORD_DRAFT_API_BASE 或 QUIZ_API_BASE_URL"
        return
    url = f"{base}/api/integration/draft/interop-config"
    org_id, _ = resolve_org_collection_for_integration()
    try:
        r = requests.get(
            url,
            headers=_upstream_headers(
                for_multipart=False, organization_id=org_id
            ),
            timeout=_draft_requests_timeout(read_seconds=min(30, _draft_timeout())),
        )
        if r.status_code != 200:
            _interop_ts = now
            _interop_data = None
            _interop_err = f"interop-config HTTP {r.status_code}"
            return
        j = r.json()
        if not isinstance(j, dict) or not j.get("ok"):
            _interop_ts = now
            _interop_data = None
            _interop_err = "interop-config 响应无效"
            return
        _interop_ts = now
        _interop_data = j
        _interop_err = ""
    except requests.RequestException as e:
        _interop_ts = now
        _interop_data = None
        _interop_err = str(e)[:500]


def _upstream_personal_keys_only() -> bool:
    _refresh_upstream_interop_if_stale()
    if _interop_data and isinstance(_interop_data.get("personalKeysOnly"), bool):
        return bool(_interop_data["personalKeysOnly"])
    return True


def _upstream_admin_notes() -> str:
    _refresh_upstream_interop_if_stale()
    if not _interop_data:
        return ""
    return str(_interop_data.get("adminNotes") or "").strip()


def _builtin_provider_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": "deepseek",
            "label": "DeepSeek",
            "requiresApiKey": True,
            "hint": "须个人 API Key；可选 API Base URL、模型名，留空则用上游默认。",
        },
        {
            "id": "cursor",
            "label": "Cursor",
            "requiresApiKey": True,
            "hint": "须个人 Cursor API Key；可选 Cursor API Base、模型名；仓库/ref 用上游 cursor_*。",
        },
        {
            "id": "tongyi",
            "label": "通义千问（DashScope）",
            "requiresApiKey": True,
            "hint": "须个人 DashScope API Key；可选模型名，留空则用上游默认。",
        },
    ]


def _effective_allowed_provider_ids_ordered() -> list[str]:
    """与上游白名单求交后，保留 AIWORD 内置顺序。"""
    _refresh_upstream_interop_if_stale()
    base = list(AIWORD_DRAFT_LLM_PROVIDERS)
    if not _interop_data:
        return base
    restrict = bool(_interop_data.get("restrictProviders"))
    ups = _interop_data.get("allowedProviders") or []
    upstream_ids: set[str] = set()
    if isinstance(ups, list):
        for x in ups:
            if isinstance(x, dict):
                pid = str(x.get("id") or "").strip().lower()
                if pid:
                    upstream_ids.add(pid)
    if not restrict:
        return base
    return [p for p in base if p in upstream_ids]


def _merged_allowed_providers_for_client() -> list[dict[str, Any]]:
    eff = _effective_allowed_provider_ids_ordered()
    builtin_by_id = {str(x["id"]): x for x in _builtin_provider_rows()}
    ups_list = (_interop_data or {}).get("allowedProviders") if _interop_data else None
    label_from_upstream: dict[str, dict[str, Any]] = {}
    if isinstance(ups_list, list):
        for x in ups_list:
            if isinstance(x, dict):
                pid = str(x.get("id") or "").strip().lower()
                if pid:
                    label_from_upstream[pid] = x
    out: list[dict[str, Any]] = []
    for pid in eff:
        u = label_from_upstream.get(pid)
        b = builtin_by_id.get(pid, {})
        hint_u = (u.get("hint") if u else None) or ""
        hint_u = str(hint_u).strip() if hint_u else ""
        out.append(
            {
                "id": pid,
                "label": (u.get("label") if u else None) or b.get("label") or pid,
                "requiresApiKey": bool((u or {}).get("requiresApiKey", True)),
                "hint": hint_u or str(b.get("hint") or ""),
            }
        )
    return out


def _interop_sync_warnings() -> list[str]:
    """给人看的短句列表（非致命亦可提示）。"""
    _refresh_upstream_interop_if_stale()
    w: list[str] = []
    if _interop_err:
        w.append(f"未能同步上游联调策略（{_interop_err}），已使用本地默认可选提供方。")
    eff = _effective_allowed_provider_ids_ordered()
    if _interop_data and bool(_interop_data.get("restrictProviders")) and not eff:
        w.append(
            "上游初稿联调白名单与 aiword 当前支持的提供方（DeepSeek/Cursor/通义）无交集，"
            "请在 aicheckword 系统配置「初稿集成」中调整 draft_interop_allowed_providers。"
        )
    return w


def _draft_personal_key_headers() -> dict[str, str]:
    """上游 personalKeysOnly 为 true 时声明个人 Key 模式。"""
    if not _upstream_personal_keys_only():
        return {}
    return {"X-Client-Llm-Personal-Keys-Only": "1"}


def _upstream_headers(
    *,
    for_multipart: bool = False,
    organization_id: Optional[str] = None,
) -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/json"}
    bearer = (get_setting("QUIZ_API_BEARER_TOKEN") or "").strip()
    secret = (get_setting("QUIZ_API_SECRET") or "").strip()
    if bearer:
        h["Authorization"] = f"Bearer {bearer}"
    if secret:
        h["X-Integration-Secret"] = secret
    if organization_id:
        h["X-Aiword-Company-Id"] = str(organization_id).strip()
    if not for_multipart:
        h["Content-Type"] = "application/json; charset=utf-8"
    return h


def _load_user_credential(user_id: str) -> Optional[UserLlmCredential]:
    return UserLlmCredential.query.filter_by(user_id=user_id).first()


def _client_llm_headers(user_id: str, provider: Optional[str] = None) -> dict[str, str]:
    """发往 aicheckword 的个人 LLM 头：Key 必填（个人）；Base URL / 模型可选，空则上游用系统默认。"""
    row = _load_user_credential(user_id)
    if not row:
        return {}
    prov, _ = _resolve_submit_provider(user_id, provider)
    if not prov:
        return {}
    sk = str(current_app.config.get("SECRET_KEY") or "")
    key_plain = _decrypt_key_for_provider(row, prov, sk)
    if not key_plain.strip():
        return {}
    bu = _base_url_for_provider(row, prov)
    mo = _model_for_provider(row, prov)

    def _with_optional(h: dict[str, str]) -> dict[str, str]:
        if bu:
            h["X-Client-Llm-Base-Url"] = bu
        if mo:
            h["X-Client-Llm-Model"] = mo
        return h

    if prov == "cursor":
        return _with_optional(
            {
                "X-Client-Llm-Provider": "cursor",
                "X-Client-Llm-Api-Key": key_plain.strip(),
            }
        )
    if prov == "tongyi":
        return _with_optional(
            {
                "X-Client-Llm-Provider": "tongyi",
                "X-Client-Llm-Api-Key": key_plain.strip(),
            }
        )
    return _with_optional(
        {
            "X-Client-Llm-Provider": "deepseek",
            "X-Client-Llm-Api-Key": key_plain.strip(),
        }
    )


def _personal_key_ready(user_id: str, provider: Optional[str] = None) -> tuple[bool, str]:
    """初稿提交前：上游要求个人 Key 时须已配置并解密出非空 API Key。"""
    if not _upstream_personal_keys_only():
        return True, ""
    p, err = _resolve_submit_provider(user_id, provider)
    if not p:
        return False, err
    return True, ""


@draft_gen_bp.route("/")
def draft_gen_page():
    from ._integration_common import integration_html_access_wall

    blocked = integration_html_access_wall(
        gate_description="请输入访问密码以进入初稿生成（超级管理员无需账号登录）。",
    )
    if blocked is not None:
        return blocked
    scope = integration_scope_from_request()
    return render_template(
        "draft_gen.html",
        manual_upload_only=manual_upload_only_from_request(),
        integration_scope=scope,
    )


def _llm_settings_payload_for_user(uid: str, *, configured: bool) -> dict[str, Any]:
    _refresh_upstream_interop_if_stale()
    eff = _effective_allowed_provider_ids_ordered()
    notes = _upstream_admin_notes()
    pko = _upstream_personal_keys_only()
    warns = _interop_sync_warnings()
    allowed_rows = _merged_allowed_providers_for_client()
    row = _load_user_credential(uid)
    stored = ((row.provider or "deepseek") if row else "deepseek").strip().lower()
    if stored not in AIWORD_DRAFT_LLM_PROVIDERS:
        stored = "deepseek"
    if eff:
        provider_out = stored if stored in eff else eff[0]
    else:
        provider_out = stored
    sk = str(current_app.config.get("SECRET_KEY") or "")
    has_by = {pid: _has_usable_stored_key_for_provider(row, pid, sk=sk) for pid in AIWORD_DRAFT_LLM_PROVIDERS}
    has_key = bool(has_by.get(provider_out))
    base_by = {pid: _base_url_for_provider(row, pid) for pid in AIWORD_DRAFT_LLM_PROVIDERS}
    model_by = {pid: _model_for_provider(row, pid) for pid in AIWORD_DRAFT_LLM_PROVIDERS}
    return {
        "configured": configured,
        "provider": provider_out,
        "hasApiKey": has_key,
        "hasApiKeyByProvider": has_by,
        "apiBaseUrl": base_by.get(provider_out, ""),
        "llmModel": model_by.get(provider_out, ""),
        "apiBaseUrlByProvider": base_by,
        "llmModelByProvider": model_by,
        "allowedProviders": allowed_rows,
        "personalKeysOnly": pko,
        "adminNotes": notes,
        "interopSynced": bool(_interop_data and not _interop_err),
        "interopSyncWarnings": warns,
    }


@draft_gen_bp.get("/api/llm-settings")
def api_llm_settings_get():
    err = _login_wall()
    if err:
        return err
    uid = _session_user_id()
    row = _load_user_credential(uid)
    if not row:
        return jsonify(_llm_settings_payload_for_user(uid, configured=False))
    return jsonify(_llm_settings_payload_for_user(uid, configured=True))


@draft_gen_bp.post("/api/llm-settings")
def api_llm_settings_post():
    err = _login_wall()
    if err:
        return err
    blocked, uid = _account_user_id_wall()
    if blocked:
        return blocked
    _refresh_upstream_interop_if_stale(force=True)
    data = request.get_json(force=True) or {}
    provider = (data.get("provider") or "deepseek").strip().lower()
    api_key = (data.get("apiKey") or data.get("api_key") or "").strip()
    api_base = (data.get("apiBaseUrl") or data.get("api_base_url") or "").strip()
    llm_model = (data.get("llmModel") or data.get("llm_model") or "").strip()

    if provider not in AIWORD_DRAFT_LLM_PROVIDERS:
        return jsonify({"message": f"仅支持 provider: {', '.join(AIWORD_DRAFT_LLM_PROVIDERS)}"}), 400
    eff = _effective_allowed_provider_ids_ordered()
    if eff and provider not in eff:
        return jsonify(
            {
                "message": (
                    f"当前 aicheckword 初稿联调配置不允许 provider={provider!r}，"
                    f"允许：{', '.join(eff)}"
                )
            }
        ), 400
    if not eff:
        return jsonify(
            {
                "message": (
                    "上游初稿联调白名单与 aiword 支持的提供方无交集，无法保存。"
                    "请在 aicheckword 系统配置「初稿集成」中调整。"
                )
            }
        ), 400

    row = _load_user_credential(uid)
    if not row:
        row = UserLlmCredential(user_id=uid, provider=provider)
        db.session.add(row)
    row.provider = provider
    base_attr = _DRAFT_LLM_BASE_ATTR[provider]
    model_attr = _DRAFT_LLM_MODEL_ATTR[provider]
    setattr(row, base_attr, api_base or None)
    setattr(row, model_attr, llm_model or None)
    row.base_url = None
    row.model = None
    row.cursor_repository = None
    row.cursor_ref = None

    sk = str(current_app.config.get("SECRET_KEY") or "")
    labels = {"deepseek": "DeepSeek", "cursor": "Cursor", "tongyi": "通义千问（DashScope）"}
    key_attr = _DRAFT_LLM_PROVIDER_KEY_ATTR[provider]
    if api_key:
        setattr(row, key_attr, encrypt_api_key(sk, api_key))
        row.api_key_encrypted = None
    elif not _encrypted_key_blob_for_provider(row, provider) and _upstream_personal_keys_only():
        return jsonify({"message": f"{labels[provider]} 须填写并保存个人 API Key（不使用 aicheckword 系统管理员 Key）"}), 400
    db.session.commit()
    return jsonify({"ok": True, "message": "已保存"})


def _fetch_upstream_meta(
    collection: str,
    base_case_id: Optional[int],
    *,
    organization_id: Optional[str] = None,
) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
    """请求 aicheckword draft meta；返回 (json_body, error_message)。"""
    base = _draft_api_base()
    if not base:
        return None, "未配置 AICHECKWORD_DRAFT_API_BASE 或 QUIZ_API_BASE_URL"
    params: dict[str, Any] = {"collection": (collection or "regulations").strip() or "regulations"}
    if base_case_id is not None and int(base_case_id) > 0:
        params["base_case_id"] = int(base_case_id)
    url = f"{base}/api/integration/draft/meta"
    try:
        r = requests.get(
            url,
            params=params,
            headers=_upstream_headers(
                for_multipart=False,
                organization_id=organization_id,
            ),
            timeout=_draft_requests_timeout(read_seconds=min(60, _draft_timeout())),
        )
        try:
            body = r.json()
        except Exception:
            return None, f"上游返回非 JSON（HTTP {r.status_code}）"
        if r.status_code >= 400:
            return body, f"上游 HTTP {r.status_code}"
        return body, None
    except requests.RequestException as e:
        return None, str(e)[:500]


@draft_gen_bp.get("/api/draft-bootstrap")
def api_draft_bootstrap():
    """初稿页下拉：透传 aicheckword page-bootstrap；仅合并 aiword 部署侧知识库列表配置。"""
    err = _login_wall()
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
    bc_raw = (request.args.get("base_case_id") or "").strip()
    base_case_id: Optional[int] = None
    if bc_raw:
        try:
            base_case_id = int(bc_raw)
        except ValueError:
            base_case_id = None
    if base_case_id is not None and base_case_id <= 0:
        base_case_id = None

    tpl_names = [str(x).strip() for x in request.args.getlist("templates") if str(x).strip()]
    bootstrap, boot_err, upstream_body = fetch_draft_page_bootstrap(
        resolved_collection,
        base_case_id=base_case_id,
        template_names=tpl_names or None,
        organization_id=org_id,
    )
    meta_body, meta_err = _fetch_upstream_meta(
        resolved_collection,
        base_case_id,
        organization_id=org_id,
    )

    out: dict[str, Any] = {"ok": True}
    if bootstrap:
        out.update(bootstrap)
        out["collection"] = bootstrap.get("collection") or resolved_collection
    else:
        out["collection"] = resolved_collection
    out["collections"] = integration_collection_rows()
    org_ctx = integration_org_context_payload()
    out["organizations"] = org_ctx.get("organizations") or []
    out["activeOrganizationId"] = org_ctx.get("activeOrganizationId")
    out["activeKnowledgeCollection"] = org_ctx.get("activeKnowledgeCollection")
    out["metaOk"] = boot_err is None and bool(bootstrap)
    out["metaError"] = boot_err or (None if bootstrap else "page-bootstrap 异常")
    if isinstance(upstream_body, dict):
        out["upstreamBody"] = upstream_body
    elif isinstance(meta_body, dict):
        out["upstreamBody"] = meta_body
    if boot_err and not bootstrap:
        out["metaError"] = boot_err
    return jsonify(out)


@draft_gen_bp.get("/api/suggest-author-role")
def api_suggest_author_role():
    """代理 aicheckword ``GET /api/integration/draft/suggest-author-role``。"""
    err = _login_wall()
    if err:
        return err
    params: dict[str, Any] = {
        "registration_type": (request.args.get("registration_type") or "").strip(),
        "project_form": (request.args.get("project_form") or "").strip(),
    }
    names = [str(x).strip() for x in request.args.getlist("templates") if str(x).strip()]
    if names:
        params["templates"] = names
    base = _draft_api_base()
    if not base:
        return jsonify({"message": "未配置 AICHECKWORD_DRAFT_API_BASE 或 QUIZ_API_BASE_URL"}), 503
    org_id, _ = resolve_org_collection_for_integration()
    try:
        r = requests.get(
            f"{base}/api/integration/draft/suggest-author-role",
            params=params,
            headers=_upstream_headers(
                for_multipart=False, organization_id=org_id
            ),
            timeout=_draft_requests_timeout(read_seconds=30),
        )
        body = r.json()
    except requests.RequestException as e:
        return jsonify({"ok": False, "message": str(e)[:500]}), 502
    except Exception:
        return jsonify({"ok": False, "message": "上游返回非 JSON"}), 502
    if r.status_code >= 400:
        return jsonify(body if isinstance(body, dict) else {"message": f"上游 HTTP {r.status_code}"}), r.status_code
    return jsonify(body)


@draft_gen_bp.get("/api/projects/<int:project_id>/draft-defaults")
def api_project_draft_defaults(project_id: int):
    """代理 aicheckword 项目初稿维度默认值。"""
    err = _login_wall()
    if err:
        return err
    data, up_err = upstream_get_json(
        f"api/integration/draft/projects/{int(project_id)}/draft-defaults",
        read_timeout_seconds=15,
    )
    if up_err:
        return jsonify({"ok": False, "message": up_err}), 502
    return jsonify({"ok": True, "data": data or {}})


@draft_gen_bp.get("/api/meta")
def api_meta():
    err = _login_wall()
    if err:
        return err
    base = _draft_api_base()
    if not base:
        return jsonify({"message": "未配置 AICHECKWORD_DRAFT_API_BASE 或 QUIZ_API_BASE_URL"}), 503
    collection = (request.args.get("collection") or "regulations").strip()
    org_id, resolved_collection = resolve_org_collection_for_integration(
        preferred_collection=collection
    )
    bc = request.args.get("base_case_id")
    params: dict[str, Any] = {"collection": resolved_collection}
    if bc is not None and str(bc).strip() != "":
        try:
            params["base_case_id"] = int(bc)
        except ValueError:
            pass
    url = f"{base}/api/integration/draft/meta"
    try:
        r = requests.get(
            url,
            params=params,
            headers=_upstream_headers(
                for_multipart=False, organization_id=org_id
            ),
            timeout=_draft_requests_timeout(read_seconds=min(60, _draft_timeout())),
        )
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:2000]}
        return jsonify(body), r.status_code
    except requests.RequestException as e:
        return jsonify({"message": f"上游请求失败: {e}"}), 503


@draft_gen_bp.get("/api/jobs")
def api_jobs_list():
    err = _login_wall()
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
    uid = _session_user_id()
    scope = integration_scope_from_request()
    q = DraftGenerationJob.query.filter_by(user_id=uid).filter(
        or_(
            DraftGenerationJob.source.is_(None),
            DraftGenerationJob.source == "",
            DraftGenerationJob.source == "draft",
        )
    )
    q = integration_scope_list_filter(q, DraftGenerationJob, scope)
    q = integration_organization_list_filter(q, DraftGenerationJob)
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
        snap = j.payload_snapshot_json if isinstance(j.payload_snapshot_json, dict) else {}
        tpl_raw = j.template_names_json
        tpl_list = tpl_raw if isinstance(tpl_raw, list) else []
        in_raw = j.input_display_names_json
        in_list = in_raw if isinstance(in_raw, list) else []
        summary_parts = []
        if j.collection:
            summary_parts.append(f"知识库 {j.collection}")
        if j.base_case_id is not None:
            summary_parts.append(f"案例 ID {j.base_case_id}")
        pid = snap.get("project_id")
        if pid is not None and str(pid).strip():
            summary_parts.append(f"项目 {pid}")
        if tpl_list:
            summary_parts.append(f"模板 {len(tpl_list)} 个")
        if in_list:
            names = [str(x).strip() for x in in_list if str(x).strip()]
            head = "、".join(names[:4])
            if len(names) > 4:
                head += f" 等共 {len(names)} 个文件"
            summary_parts.append(f"输入 {head}")
        out.append(
            {
                "id": j.id,
                "upstreamJobId": j.upstream_job_id,
                "status": j.status,
                "progress": j.progress,
                "message": (j.message or "")[:500],
                "errorSummary": (j.error_summary or "")[:500],
                "collection": j.collection,
                "baseCaseId": j.base_case_id,
                "projectId": j.project_id,
                "projectCaseId": j.project_case_id,
                "durationMs": j.duration_ms,
                "hasLocalZip": bool(j.local_zip_path and Path(j.local_zip_path).is_file()),
                "createdAt": j.created_at.isoformat() if j.created_at else None,
                "summaryLine": " · ".join(summary_parts) if summary_parts else (j.message or "")[:120],
                "templateCount": len(tpl_list),
                "inputFileCount": len(in_list),
                "hasPayloadSnapshot": bool(snap),
            }
        )
    total_pages = max(1, (total + page_size - 1) // page_size) if total else 1
    return jsonify(
        {
            "jobs": out,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            },
        }
    )


@draft_gen_bp.get("/api/jobs/<local_id>/snapshot")
def api_job_snapshot(local_id: str):
    """返回历史任务的 payload 快照，供「相同参数再提交」回填表单。"""
    err = _login_wall()
    if err:
        return err
    uid = _session_user_id()
    job = DraftGenerationJob.query.filter_by(id=local_id, user_id=uid).first()
    if not job:
        return jsonify({"message": "任务不存在"}), 404
    snap = job.payload_snapshot_json if isinstance(job.payload_snapshot_json, dict) else {}
    tpl_raw = job.template_names_json
    return jsonify(
        {
            "ok": True,
            "snapshot": snap,
            "templateNames": tpl_raw if isinstance(tpl_raw, list) else [],
            "collection": job.collection,
            "baseCaseId": job.base_case_id,
            "projectId": job.project_id,
            "inputDisplayNames": job.input_display_names_json if isinstance(job.input_display_names_json, list) else [],
        }
    )


def _apply_upstream_status_to_job(job: DraftGenerationJob, data: dict[str, Any]) -> None:
    st = (data.get("status") or "").strip().lower()
    if st in ("queued", "running", "succeeded", "failed", "pending"):
        job.status = st
    job.progress = float(data.get("progress") or 0.0)
    job.message = (data.get("message") or "")[:4000]
    err_msg = data.get("error")
    if err_msg:
        job.error_summary = str(err_msg)[:4000]
    res = data.get("result")
    if st == "succeeded" and isinstance(res, dict):
        if bool(res.get("docx_unchanged")):
            top = res.get("patch_skip_reason_histogram")
            top_msg = ""
            if isinstance(top, dict) and top:
                pairs = sorted(top.items(), key=lambda x: (-int(x[1] or 0), str(x[0])))[:3]
                top_msg = "；".join(f"{k}({v})" for k, v in pairs if str(k).strip())
            job.status = "failed"
            job.error_summary = (
                "PATCH 已生成但未写入文档（applied=0，文档与基底一致）。"
                + (f" 主因：{top_msg}" if top_msg else "")
            )[:4000]
            if not (job.message or "").strip():
                job.message = "生成失败：patch 未落地"
        try:
            job.project_id = int(res["project_id"]) if res.get("project_id") is not None else job.project_id
        except (TypeError, ValueError, KeyError):
            pass
        try:
            job.project_case_id = (
                int(res["project_case_id"]) if res.get("project_case_id") is not None else job.project_case_id
            )
        except (TypeError, ValueError, KeyError):
            pass
    if st in ("succeeded", "failed") and job.duration_ms is None:
        try:
            job.duration_ms = int(max(0.0, (now_local() - job.created_at).total_seconds()) * 1000)
        except Exception:
            pass


@draft_gen_bp.post("/api/check-input-vector-duplicates")
def api_check_input_vector_duplicates():
    """代理 aicheckword：按项目检测参考文件名是否已在向量库。"""
    err = _login_wall()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    try:
        pid = int(body.get("project_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"message": "缺少有效的 project_id"}), 400
    if pid <= 0:
        return jsonify({"message": "请选择具体项目后再检测"}), 400
    names = body.get("file_names")
    if not isinstance(names, list):
        names = []
    file_names = [str(x).strip() for x in names if str(x).strip()]
    base = _draft_api_base()
    if not base:
        return jsonify({"message": "未配置 AICHECKWORD_DRAFT_API_BASE 或 QUIZ_API_BASE_URL"}), 503
    url = f"{base}/api/integration/draft/check-input-vector-duplicates"
    try:
        r = requests.post(
            url,
            json={"project_id": pid, "file_names": file_names},
            timeout=_draft_requests_timeout(read_seconds=30),
        )
        data = r.json() if r.content else {}
        if r.status_code >= 400:
            return jsonify(
                {"ok": False, "message": data.get("detail") or data.get("message") or r.text[:500]}
            ), r.status_code
        return jsonify(data)
    except requests.RequestException as e:
        return jsonify({"ok": False, "message": f"上游检测失败：{e}"}), 502


@draft_gen_bp.post("/api/jobs")
def api_jobs_submit():
    err = _login_wall()
    if err:
        return err
    blocked, uid = _account_user_id_wall()
    if blocked:
        return blocked
    base = _draft_api_base()
    if not base:
        return jsonify({"message": "未配置 AICHECKWORD_DRAFT_API_BASE 或 QUIZ_API_BASE_URL"}), 503

    _refresh_upstream_interop_if_stale(force=True)
    eff = _effective_allowed_provider_ids_ordered()
    if not eff:
        return jsonify(
            {
                "message": (
                    "上游初稿联调白名单与 aiword 支持的提供方无交集，无法提交。"
                    "请在 aicheckword「初稿集成」中调整或联系管理员。"
                )
            }
        ), 400
    cred0 = _load_user_credential(uid)
    if cred0:
        p0 = _normalized_draft_provider(cred0)
        if not p0:
            return jsonify(
                {
                    "message": (
                        "当前提供方不在上游允许列表内，请在「个人 LLM 设置」中改选允许项并保存。"
                    )
                }
            ), 400

    payload_str = (request.form.get("payload") or "").strip()
    if not payload_str:
        return jsonify({"message": "缺少 payload"}), 400
    try:
        payload_obj: dict[str, Any] = json.loads(payload_str)
    except json.JSONDecodeError as e:
        return jsonify({"message": f"payload 不是有效 JSON: {e}"}), 400

    requested_prov = (payload_obj.get("provider") or "").strip() or None
    ok_key, key_msg = _personal_key_ready(uid, provider=requested_prov)
    if not ok_key:
        return jsonify({"message": key_msg}), 400

    cred = _load_user_credential(uid)
    p, prov_err = _resolve_submit_provider(uid, requested_prov)
    if not p:
        return jsonify({"message": prov_err or "无法确定 LLM 提供方"}), 400
    if p:
        payload_obj["provider"] = p
        if cred and (cred.provider or "").strip().lower() != p:
            cred.provider = p

    payload_obj["aiword_user_id"] = uid

    base_ids_ordered = _collect_base_upload_record_ids(payload_obj)
    explicit_org = str(
        payload_obj.get("organizationId") or payload_obj.get("organization_id") or ""
    ).strip()
    try:
        org_id, resolved_collection = resolve_org_collection_for_integration(
            preferred_collection=str(payload_obj.get("collection") or "regulations"),
            explicit_organization_id=explicit_org or None,
            upload_ids=base_ids_ordered,
        )
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    payload_obj["collection"] = resolved_collection
    payload_obj["organizationId"] = org_id
    if base_ids_ordered:
        pid_guess = resolve_aicheckword_project_id_for_upload(base_ids_ordered[0], user_id=uid)
        try:
            pid_cur = int(payload_obj.get("project_id") or 0)
        except (TypeError, ValueError):
            pid_cur = 0
        if pid_guess and int(pid_guess) > 0 and pid_cur != int(pid_guess):
            payload_obj["project_id"] = int(pid_guess)
    base_from_uploads: list[tuple[str, bytes]] = []
    for bid in base_ids_ordered:
        ur = UploadRecord.query.get(bid)
        if not ur or not _upload_record_visible_to_draft_user(ur):
            return jsonify({"message": f"无效或无权的 base 任务 id: {bid}"}), 400
        bdata, suggested_fn = _base_doc_bytes_from_upload(ur)
        if not bdata:
            return jsonify({"message": f"任务 {bid} 无可用模板文件作 Base（可能仅为链接）"}), 400
        fn0 = secure_filename(suggested_fn) or "base.docx"
        base_from_uploads.append((fn0, bdata))

    base_multipart_names = [fn for fn, _ in base_from_uploads]
    for f in request.files.getlist("base_files") or []:
        fn = secure_filename(f.filename or "unnamed.bin")
        if fn and fn not in base_multipart_names:
            base_multipart_names.append(fn)
    _auto_bind_base_files_by_target(payload_obj, base_multipart_names)

    payload_for_upstream = {
        k: v for k, v in payload_obj.items() if k not in ("base_upload_id", "base_upload_ids")
    }
    payload_str2 = json.dumps(payload_for_upstream, ensure_ascii=False)

    input_parts = request.files.getlist("input_files") or []
    base_parts = request.files.getlist("base_files") or []
    display_names = [secure_filename(f.filename or "file") for f in input_parts]

    snap = {
        k: payload_obj.get(k)
        for k in (
            "base_case_id",
            "template_file_names",
            "project_id",
            "inplace_patch",
            "document_language",
            "collection",
        )
        if k in payload_obj
    }
    if "base_upload_id" in payload_obj:
        snap["base_upload_id"] = payload_obj.get("base_upload_id")
    if "base_upload_ids" in payload_obj:
        snap["base_upload_ids"] = payload_obj.get("base_upload_ids")
    _uap_snap = (payload_obj.get("user_prompt_append") or "").strip()
    if _uap_snap:
        snap["user_prompt_append_preview"] = _uap_snap[:500] + ("…" if len(_uap_snap) > 500 else "")

    job = DraftGenerationJob(
        user_id=uid,
        organization_id=(org_id or None),
        status="pending",
        collection=resolved_collection[:64],
        base_case_id=payload_obj.get("base_case_id"),
        template_names_json=payload_obj.get("template_file_names"),
        input_display_names_json=display_names,
        payload_snapshot_json=snap,
        integration_scope=integration_scope_from_request(),
    )
    db.session.add(job)
    db.session.commit()

    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for f in input_parts:
        fn = secure_filename(f.filename or "unnamed.bin")
        files.append(("input_files", (fn, f.read(), "application/octet-stream")))
    for fn_b, bdata in base_from_uploads:
        files.append(("base_files", (fn_b, bdata, "application/octet-stream")))
    for f in base_parts:
        fn = secure_filename(f.filename or "unnamed.bin")
        files.append(("base_files", (fn, f.read(), "application/octet-stream")))

    hdr = {
        **_upstream_headers(for_multipart=True, organization_id=org_id),
        **_draft_personal_key_headers(),
        **_client_llm_headers(uid, provider=p),
    }
    url = f"{base}/api/integration/draft/jobs"
    try:
        r = requests.post(
            url,
            data={"payload": payload_str2},
            files=files,
            headers=hdr,
            timeout=_draft_requests_timeout(read_seconds=_draft_timeout()),
        )
    except requests.RequestException as e:
        job.status = "failed"
        job.error_summary = str(e)[:2000]
        job.message = "提交上游失败（网络）"
        db.session.commit()
        return jsonify({"message": str(e), "localJobId": job.id}), 503

    try:
        body = r.json()
    except Exception:
        body = {"raw": (r.text or "")[:4000]}

    if r.status_code >= 400 or not body.get("ok"):
        job.status = "failed"
        job.error_summary = json.dumps(body, ensure_ascii=False)[:4000]
        job.message = (body.get("message") or body.get("detail") or "上游返回错误")[:2000]
        db.session.commit()
        return jsonify({"message": job.message, "upstream": body, "localJobId": job.id}), 502

    upstream_id = (body.get("job_id") or "").strip()
    job.upstream_job_id = upstream_id or None
    job.status = str(body.get("status") or "queued").lower() or "queued"
    job.message = (body.get("message") or "已提交上游")[:2000]
    try:
        job.progress = float(body.get("progress") or 0.02)
    except (TypeError, ValueError):
        job.progress = 0.02
    db.session.commit()
    return jsonify({"ok": True, "localJobId": job.id, "upstreamJobId": upstream_id})


@draft_gen_bp.get("/api/jobs/<local_id>/status")
def api_job_status(local_id: str):
    err = _login_wall()
    if err:
        return err
    uid = _session_user_id()
    job = DraftGenerationJob.query.filter_by(id=local_id, user_id=uid).first()
    if not job:
        return jsonify({"message": "任务不存在"}), 404

    if not job.upstream_job_id:
        return jsonify(
            {
                "localJobId": job.id,
                "upstreamJobId": None,
                "status": job.status,
                "progress": job.progress,
                "message": job.message,
                "error": job.error_summary,
                "result": None,
            }
        )

    base = _draft_api_base()
    if not base:
        return jsonify({"message": "未配置上游地址"}), 503
    hdr = {
        **_upstream_headers(
            for_multipart=True,
            organization_id=str(getattr(job, "organization_id", "") or "").strip(),
        ),
        **_client_llm_headers(uid),
    }
    url = f"{base}/api/integration/draft/jobs/{job.upstream_job_id}"
    try:
        r = requests.get(
            url,
            headers=hdr,
            timeout=_draft_requests_timeout(read_seconds=min(120, _draft_timeout())),
        )
        body = r.json()
    except requests.RequestException as e:
        return jsonify({"message": str(e), "localJobId": job.id}), 503
    except ValueError:
        return jsonify({"message": "上游返回非 JSON", "localJobId": job.id}), 502

    if isinstance(body, dict):
        _apply_upstream_status_to_job(job, body)
        db.session.commit()
    return jsonify(body), r.status_code


@draft_gen_bp.get("/api/jobs/<local_id>/download")
def api_job_download(local_id: str):
    err = _login_wall()
    if err:
        return err
    uid = _session_user_id()
    job = DraftGenerationJob.query.filter_by(id=local_id, user_id=uid).first()
    if not job or not job.upstream_job_id:
        return jsonify({"message": "任务不存在或未提交上游"}), 404

    if job.local_zip_path:
        p = Path(job.local_zip_path)
        if p.is_file():
            return send_file(str(p), as_attachment=True, download_name=f"draft_{local_id}.zip")

    base = _draft_api_base()
    if not base:
        return jsonify({"message": "未配置上游地址"}), 503
    hdr = {
        **_upstream_headers(
            for_multipart=True,
            organization_id=str(getattr(job, "organization_id", "") or "").strip(),
        ),
        **_draft_personal_key_headers(),
        **_client_llm_headers(uid),
    }
    url = f"{base}/api/integration/draft/jobs/{job.upstream_job_id}/download"
    try:
        r = requests.get(
            url,
            headers=hdr,
            timeout=_draft_requests_timeout(read_seconds=_draft_timeout()),
            stream=True,
        )
    except requests.RequestException as e:
        return jsonify({"message": str(e)}), 503
    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = {"raw": (r.text or "")[:2000]}
        return jsonify({"message": "下载失败", "upstream": detail}), 502

    out_dir = Path(current_app.config.get("OUTPUT_FOLDER") or "outputs") / "draft_zips"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    out_path = out_dir / f"{local_id}.zip"
    try:
        with open(out_path, "wb") as fh:
            for chunk in r.iter_content(65536):
                if chunk:
                    fh.write(chunk)
    except OSError as e:
        return jsonify({"message": f"保存 ZIP 失败: {e}"}), 500

    job.local_zip_path = str(out_path.resolve())
    db.session.commit()
    return send_file(str(out_path), as_attachment=True, download_name=f"draft_{local_id}.zip")

