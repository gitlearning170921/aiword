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

from sqlalchemy import desc

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
from .draft_author_role_infer import (
    DRAFT_AUTHOR_ROLE_KEYS,
    DRAFT_AUTHOR_ROLE_LABELS,
    infer_draft_author_role_key,
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


# 与 aicheckword ``src/app.py`` 初稿页文案保持一致（侧边栏/训练页同源常量）
DOC_LANG_VALUE_TO_LABEL: dict[str, str] = {
    "": "不指定",
    "zh": "中文版",
    "en": "英文版",
    "both": "中英文",
}
DRAFT_STRATEGY_OPTIONS_UI: tuple[dict[str, str], ...] = (
    {
        "value": "change",
        "label": "注册变更：对照参考在基础文件上自动识别新增/细化/删除（保留版式与未涉及原文）",
    },
    {
        "value": "reuse",
        "label": "新项目复用：按参考文件全量更新内容（保留格式章节不变）",
    },
)
def _project_option_label(p: dict[str, Any]) -> str:
    """与 aicheckword ``format_project_option_label`` 一致。"""
    try:
        nm = str((p or {}).get("name") or "").strip() or "未命名"
    except Exception:
        nm = "未命名"
    try:
        pid = int((p or {}).get("id") or 0)
    except Exception:
        pid = 0
    pc = ""
    try:
        pc = str((p or {}).get("project_code") or "").strip()
    except Exception:
        pc = ""
    suf = f" · {pc}" if pc else ""
    head = f"{nm} (ID:{pid}){suf}"

    prod = ""
    try:
        prod = str((p or {}).get("product_name") or "").strip()
    except Exception:
        prod = ""
    if not prod:
        try:
            prod = str((p or {}).get("product_name_en") or "").strip()
        except Exception:
            prod = ""

    rcn = ""
    rce = ""
    try:
        rcn = str((p or {}).get("registration_country") or "").strip()
    except Exception:
        rcn = ""
    try:
        rce = str((p or {}).get("registration_country_en") or "").strip()
    except Exception:
        rce = ""
    if rcn and rce and rcn != rce:
        cshow = f"{rcn} / {rce}"
    elif rcn:
        cshow = rcn
    else:
        cshow = rce

    reg_type = ""
    try:
        reg_type = str((p or {}).get("registration_type") or "").strip()
    except Exception:
        reg_type = ""

    extras: list[str] = []
    if prod:
        extras.append(f"产品:{prod}")
    if cshow:
        extras.append(f"国家:{cshow}")
    if reg_type:
        extras.append(f"类别:{reg_type}")
    if not extras:
        return head
    return f"{head} | " + " | ".join(extras)


def _format_case_option(c: dict[str, Any]) -> str:
    """与 aicheckword ``_format_case_option`` 一致。"""
    name = (str(c.get("case_name") or "").strip()) or "—"
    product = (str(c.get("product_name") or "").strip()) or "—"
    country = (str(c.get("registration_country") or "").strip()) or "—"
    lang_val = str(c.get("document_language") or "").strip()
    lang_label = DOC_LANG_VALUE_TO_LABEL.get(lang_val, lang_val or "—")
    return f"{name}（{product} · {country} · {lang_label}）"


def _draft_collection_select_rows() -> list[dict[str, str]]:
    """知识库名称下拉；默认 regulations；可在系统配置增加 AICHECKWORD_DRAFT_COLLECTION_IDS=regulations,custom1。"""
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


def _login_wall():
    if not session.get("user_id"):
        return jsonify({"message": "请先登录", "needsLogin": True}), 401
    return None


def _upload_record_visible_to_draft_user(rec: UploadRecord) -> bool:
    """与页面2「我的任务」一致：负责人或编写人匹配当前登录用户。"""
    username = (session.get("username") or "").strip()
    display_name = (session.get("display_name") or "").strip()
    an = (rec.assignee_name or "").strip()
    au = (rec.author or "").strip()
    if username and (an == username or au == username):
        return True
    if display_name and (an == display_name or au == display_name):
        return True
    return False


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
    if fp:
        return jsonify(
            {
                "ok": True,
                "uploadId": rec.id,
                "fileName": rec.file_name,
                "ftpPath": fp,
                "source": "ftp",
            }
        )
    if blob:
        return jsonify(
            {
                "ok": True,
                "uploadId": rec.id,
                "fileName": rec.file_name,
                "ftpPath": None,
                "source": "blob",
            }
        )
    return jsonify(
        {
            "ok": True,
            "uploadId": rec.id,
            "fileName": rec.file_name,
            "ftpPath": None,
            "source": "none",
        }
    )


def _draft_api_base() -> str:
    raw = (
        get_setting("AICHECKWORD_DRAFT_API_BASE", default="")
        or get_setting("QUIZ_API_BASE_URL", default="")
        or str(current_app.config.get("QUIZ_API_BASE_URL") or "")
    ).strip()
    return raw.rstrip("/")


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
    try:
        r = requests.get(
            url,
            headers=_upstream_headers(for_multipart=False),
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


def _upstream_headers(*, for_multipart: bool = False) -> dict[str, str]:
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


def _load_user_credential(user_id: str) -> Optional[UserLlmCredential]:
    return UserLlmCredential.query.filter_by(user_id=user_id).first()


def _client_llm_headers(user_id: str) -> dict[str, str]:
    """发往 aicheckword 的个人 LLM 头：Key 必填（个人）；Base URL / 模型可选，空则上游用系统默认。"""
    row = _load_user_credential(user_id)
    if not row:
        return {}
    prov = _normalized_draft_provider(row)
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


def _personal_key_ready(user_id: str) -> tuple[bool, str]:
    """初稿提交前：上游要求个人 Key 时须已配置并解密出非空 API Key。"""
    if not _upstream_personal_keys_only():
        return True, ""
    row = _load_user_credential(user_id)
    p = _normalized_draft_provider(row) if row else None
    if not p:
        return False, "请先在「个人 LLM 设置」中选择提供方（DeepSeek / Cursor / 通义千问）并保存个人 API Key。"
    if not row or not _encrypted_key_blob_for_provider(row, p):
        return False, "请先在「个人 LLM 设置」中保存个人 API Key（与 aicheckword 系统管理员配置无关）。"
    sk = str(current_app.config.get("SECRET_KEY") or "")
    try:
        plain = _decrypt_key_for_provider(row, p, sk).strip()
    except Exception:
        return False, "个人 API Key 解密失败，请重新保存。"
    if not plain:
        return False, "个人 API Key 无效或为空，请重新填写并保存。"
    return True, ""


@draft_gen_bp.route("/")
def draft_gen_page():
    if not session.get("user_id"):
        from flask import redirect, url_for

        return redirect(url_for("pages.login_page"))
    return render_template("draft_gen.html")


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
    uid = str(session["user_id"])
    row = _load_user_credential(uid)
    if not row:
        return jsonify(_llm_settings_payload_for_user(uid, configured=False))
    return jsonify(_llm_settings_payload_for_user(uid, configured=True))


@draft_gen_bp.post("/api/llm-settings")
def api_llm_settings_post():
    err = _login_wall()
    if err:
        return err
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

    uid = str(session["user_id"])
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


def _fetch_upstream_meta(collection: str, base_case_id: Optional[int]) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
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
            headers=_upstream_headers(for_multipart=False),
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
    """
    初稿页下拉数据：知识库/项目/案例/模板文件名等与 aicheckword meta 对齐；
    文档语言、生成策略等文案与 aicheckword 初稿页 selectbox 一致。
    """
    err = _login_wall()
    if err:
        return err
    collection = (request.args.get("collection") or "regulations").strip() or "regulations"
    bc_raw = (request.args.get("base_case_id") or "").strip()
    base_case_id: Optional[int] = None
    if bc_raw:
        try:
            base_case_id = int(bc_raw)
        except ValueError:
            base_case_id = None
    if base_case_id is not None and base_case_id <= 0:
        base_case_id = None

    body, meta_err = _fetch_upstream_meta(collection, base_case_id)
    data: dict[str, Any] = {}
    if isinstance(body, dict) and body.get("ok") and isinstance(body.get("data"), dict):
        data = body["data"]

    projects_raw: List[Any] = list(data.get("projects") or [])
    cases_raw: List[Any] = list(data.get("cases") or [])
    templates_raw: List[Any] = list(data.get("template_file_names") or [])

    project_rows: list[dict[str, Any]] = []
    for p in projects_raw:
        if not isinstance(p, dict):
            continue
        try:
            pid = int(p.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        project_rows.append(
            {
                "id": pid,
                "label": _project_option_label(p),
                "name": str(p.get("name") or "").strip(),
                "productName": str(p.get("product_name") or "").strip(),
                "productNameEn": str(p.get("product_name_en") or "").strip(),
                "registrationCountry": str(p.get("registration_country") or "").strip(),
                "registrationCountryEn": str(p.get("registration_country_en") or "").strip(),
            }
        )

    case_rows: list[dict[str, Any]] = []
    for c in cases_raw:
        if not isinstance(c, dict):
            continue
        try:
            cid = int(c.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if cid <= 0:
            continue
        case_rows.append(
            {
                "id": cid,
                "label": f"ID:{cid} | {_format_case_option(c)}",
                "productName": str(c.get("product_name") or "").strip(),
                "productNameEn": str(c.get("product_name_en") or "").strip(),
                "registrationCountry": str(c.get("registration_country") or "").strip(),
                "registrationCountryEn": str(c.get("registration_country_en") or "").strip(),
                "caseName": str(c.get("case_name") or "").strip(),
                "caseNameEn": str(c.get("case_name_en") or "").strip(),
                "documentLanguage": str(c.get("document_language") or "").strip().lower(),
                "registrationType": str(c.get("registration_type") or "").strip(),
                "projectForm": str(c.get("project_form") or "").strip(),
            }
        )

    template_rows: list[dict[str, str]] = []
    for name in templates_raw:
        fn = str(name or "").strip()
        if fn:
            template_rows.append({"id": fn, "label": fn})

    # 顺序与 aicheckword ``DOC_LANG_OPTIONS`` 一致：不指定、中文版、英文版、中英文
    _doc_order = ("", "zh", "en", "both")
    doc_lang_rows = [{"value": k, "label": DOC_LANG_VALUE_TO_LABEL[k]} for k in _doc_order]

    author_role_rows = [
        {"value": DRAFT_AUTHOR_ROLE_KEYS[i], "label": DRAFT_AUTHOR_ROLE_LABELS[i]}
        for i in range(min(len(DRAFT_AUTHOR_ROLE_KEYS), len(DRAFT_AUTHOR_ROLE_LABELS)))
    ]

    suggested_author = ""
    if base_case_id and template_rows:
        sel_case: Optional[dict[str, Any]] = None
        for c in cases_raw:
            if not isinstance(c, dict):
                continue
            try:
                if int(c.get("id") or 0) == int(base_case_id):
                    sel_case = c
                    break
            except (TypeError, ValueError):
                continue
        if sel_case:
            fnames = [str(t.get("id") or "").strip() for t in template_rows if str(t.get("id") or "").strip()]
            suggested_author = infer_draft_author_role_key(
                fnames,
                registration_type=str(sel_case.get("registration_type") or ""),
                project_form=str(sel_case.get("project_form") or ""),
            )

    out: dict[str, Any] = {
        "ok": True,
        "metaOk": meta_err is None and isinstance(body, dict) and body.get("ok"),
        "metaError": meta_err or (None if (isinstance(body, dict) and body.get("ok")) else "meta 异常"),
        "collection": collection,
        "collections": _draft_collection_select_rows(),
        "documentLanguages": doc_lang_rows,
        "draftStrategies": [{"value": x["value"], "label": x["label"]} for x in DRAFT_STRATEGY_OPTIONS_UI],
        "projectModes": [
            {"value": "existing", "label": "使用已有项目（不新建）"},
            {"value": "new", "label": "新建项目"},
        ],
        "projects": project_rows,
        "cases": case_rows,
        "templates": template_rows,
        "authorRoles": author_role_rows,
        "suggestedAuthorRole": suggested_author,
        "booleanOptions": [
            {
                "id": "inplace_patch",
                "label": "就地修改（保留基础文件格式，推荐用于注册递交版式）",
                "default": True,
            },
            {
                "id": "save_as_case",
                "label": "将本次生成结果写入案例库（project_cases）",
                "default": True,
            },
            {
                "id": "multi_base_auto_route",
                "label": "多份基础/多份参考时由 AI 自动分配（推荐：自动匹配改哪几份 Base、参考内容如何拆分）",
                "default": True,
            },
            {
                "id": "docx_track_changes",
                "label": "就地修改导出 Word 时使用修订标记（插入/删除，便于在 Word 中审阅修订）",
                "default": True,
            },
        ],
        "templateScopeModes": [
            {"value": "selected", "label": "仅生成下方所选模板文件（可多选）"},
            {"value": "all", "label": "生成该案例下全部模板文件（与 aicheckword「需显式确认全选」等效）"},
        ],
    }
    if isinstance(body, dict):
        out["upstreamBody"] = body
    return jsonify(out)


@draft_gen_bp.get("/api/suggest-author-role")
def api_suggest_author_role():
    """按当前模板文件名列表 + 案例注册类别/项目形态推断 author_role（与 aicheckword 初稿页一致）。"""
    err = _login_wall()
    if err:
        return err
    rt = (request.args.get("registration_type") or "").strip()
    pf = (request.args.get("project_form") or "").strip()
    names = [str(x).strip() for x in request.args.getlist("templates") if str(x).strip()]
    key = infer_draft_author_role_key(names, registration_type=rt, project_form=pf)
    return jsonify({"ok": True, "authorRole": key})


@draft_gen_bp.get("/api/meta")
def api_meta():
    err = _login_wall()
    if err:
        return err
    base = _draft_api_base()
    if not base:
        return jsonify({"message": "未配置 AICHECKWORD_DRAFT_API_BASE 或 QUIZ_API_BASE_URL"}), 503
    collection = (request.args.get("collection") or "regulations").strip()
    bc = request.args.get("base_case_id")
    params: dict[str, Any] = {"collection": collection}
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
            headers=_upstream_headers(for_multipart=False),
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
    uid = str(session["user_id"])
    rows = (
        DraftGenerationJob.query.filter_by(user_id=uid)
        .order_by(desc(DraftGenerationJob.created_at))
        .limit(100)
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
            }
        )
    return jsonify({"jobs": out})


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


@draft_gen_bp.post("/api/jobs")
def api_jobs_submit():
    err = _login_wall()
    if err:
        return err
    uid = str(session["user_id"])
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

    ok_key, key_msg = _personal_key_ready(uid)
    if not ok_key:
        return jsonify({"message": key_msg}), 400

    cred = _load_user_credential(uid)
    p = _normalized_draft_provider(cred) if cred else None
    if p:
        payload_obj["provider"] = p

    payload_obj["aiword_user_id"] = uid

    base_ids_ordered = _collect_base_upload_record_ids(payload_obj)
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

    job = DraftGenerationJob(
        user_id=uid,
        status="pending",
        collection=str(payload_obj.get("collection") or "regulations")[:64],
        base_case_id=payload_obj.get("base_case_id"),
        template_names_json=payload_obj.get("template_file_names"),
        input_display_names_json=display_names,
        payload_snapshot_json=snap,
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
        **_upstream_headers(for_multipart=True),
        **_draft_personal_key_headers(),
        **_client_llm_headers(uid),
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
    uid = str(session["user_id"])
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
    hdr = {**_upstream_headers(for_multipart=True), **_client_llm_headers(uid)}
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
    uid = str(session["user_id"])
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
        **_upstream_headers(for_multipart=True),
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

