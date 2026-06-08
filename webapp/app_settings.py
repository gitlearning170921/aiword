# -*- coding: utf-8 -*-
"""
系统级配置：优先从数据库 app_configs 读取，兼容环境变量（库中无值时回退）。
页面4 · 系统与钉钉「系统配置」维护；敏感项 GET 时脱敏。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from flask import Flask

# 与历史环境变量名一致，便于迁移
SYSTEM_CONFIG_KEYS: list[tuple[str, str, bool]] = [
    (
        "DATABASE_URL",
        "数据库连接 URI（仅在页面4 · 系统与钉钉「系统配置」维护，存入 app_configs；保存时同步 instance/database_url.txt 供冷启动；修改后需重启服务）",
        True,
    ),
    ("SECRET_KEY", "Flask Session 密钥", True),
    ("BASE_URL", "对外访问根地址（勿以 / 结尾；调试填穿透地址、正式填域名；用于催办链接与生成钉钉回调 URL）", False),
    ("DINGTALK_WEBHOOK", "催办/定时通知·群机器人 Webhook（全局默认；项目组未配时使用）", True),
    ("DINGTALK_SECRET", "催办/定时通知·加签 Secret", True),
    ("DINGTALK_TRIGGER_KEYWORDS", "钉钉自动回复触发关键词（英文逗号分隔）", False),
    ("CHATBOT_ENABLED_GROUPS", "钉钉自动回复生效群 ID（英文逗号分隔，空=不限制）", False),
    ("CHATBOT_REPLY_COOLDOWN_SECONDS", "钉钉自动回复单群冷却秒数（默认 10）", False),
    ("CHATBOT_CONFIDENCE_THRESHOLD", "钉钉自动回复最低置信度阈值（默认 0.65）", False),
    ("CHATBOT_ENABLE", "体系记录机器人·自动回复总开关（1=启用，0/空=关闭）", False),
    (
        "CHATBOT_DINGTALK_WEBHOOK",
        "体系记录机器人·群 Webhook（无 sessionWebhook 时发回复用；可与催办填相同地址）",
        True,
    ),
    ("CHATBOT_DINGTALK_SECRET", "体系记录机器人·加签 Secret（与上方 Webhook 配对）", True),
    (
        "CHATBOT_LLM_PROVIDER",
        "钉钉机器人/联调调用 aicheckword 的 LLM 提供方（deepseek / tongyi / ollama / openai / lingyi；"
        "留空=deepseek）。若当前浏览器会话已登录页面2并配置个人 Key，将优先透传个人凭据。",
        False,
    ),
    ("DINGTALK_APP_KEY", "钉钉工作通知 AppKey", False),
    ("DINGTALK_APP_SECRET", "钉钉工作通知 AppSecret", True),
    ("DINGTALK_AGENT_ID", "钉钉工作通知 AgentId", False),
    (
        "DINGTALK_CALLBACK_TOKEN",
        "钉钉 HTTP 回调 Token（开放平台机器人/事件订阅「签名 Token」，3～32 位英文或数字）",
        True,
    ),
    (
        "DINGTALK_CALLBACK_AES_KEY",
        "钉钉 HTTP 回调 EncodingAESKey（43 位，开放平台自动生成）",
        True,
    ),
    (
        "DINGTALK_CALLBACK_OWNER_KEY",
        "钉钉回调 OwnerKey（企业内部应用填 AppKey/ClientId；留空则复用 DINGTALK_APP_KEY）",
        False,
    ),
    ("PAGE13_ACCESS_PASSWORD", "页面4 访问密码（超级管理员）", True),
    ("INTEGRATION_SECRET", "开放接口校验密钥（INTEGRATION_SECRET）", True),
    ("QUIZ_API_BASE_URL", "考试训练中心后端地址（如 http://127.0.0.1:8000）", False),
    (
        "AICHECKWORD_DRAFT_API_BASE",
        "aicheckword 文档初稿 API 根地址（如 http://127.0.0.1:8000；勿以 / 结尾）。"
        "可与 QUIZ_API_BASE_URL 指向同一实例，也可单独地址/端口以便与考试中心后端独立启停。",
        False,
    ),
    (
        "AICHECKWORD_DRAFT_TIMEOUT_SECONDS",
        "初稿任务提交/下载 ZIP 等上游 HTTP 读超时（秒，默认 600；上限 72h=259200；"
        "状态轮询单次请求仍 capped 在 min(120, 配置值)。与下方「连接超时」分离）",
        False,
    ),
    (
        "AICHECKWORD_DRAFT_CONNECT_TIMEOUT_SECONDS",
        "初稿对接 aicheckword 的 TCP 连接超时（秒，默认 8；上限 120）。"
        "上游已停时应尽快失败，避免拖住 aiword 线程或影响本进程与其它服务一并停止。",
        False,
    ),
    (
        "AICHECKWORD_AUDIT_TIMEOUT_SECONDS",
        "审核任务上游 HTTP 读超时（秒，默认 600；上限 72h=259200）。与初稿超时分离便于独立调整。",
        False,
    ),
    (
        "AICHECKWORD_TRANSLATION_TIMEOUT_SECONDS",
        "翻译任务上游 HTTP 读超时（秒，默认 600；上限 72h=259200）。",
        False,
    ),
    (
        "AICHECKWORD_DRAFT_COLLECTION_IDS",
        "初稿页「知识库名称」下拉：英文逗号分隔的 collection id（默认仅 regulations；与 aicheckword 侧栏知识库名称一致）",
        False,
    ),
    (
        "AICHECKWORD_CHAT_API_BASE",
        "aicheckword 聊天回复 API 根地址（勿以 / 结尾）。留空则默认复用上方「考试训练中心后端地址」QUIZ_API_BASE_URL，与考试中心共用同一 aicheckword 实例。",
        False,
    ),
    (
        "AICHECKWORD_CHAT_API_KEY",
        "aicheckword 聊天回复 API Bearer Token（可选）",
        True,
    ),
    (
        "AICHECKWORD_CHAT_TIMEOUT_SECONDS",
        "钉钉机器人联调/回调调用 aicheckword 聊天接口的 HTTP 读超时（秒，默认 120；上限 600）。"
        "含意图分类+检索+生成两次 LLM，勿用考试中心默认 20～30 秒。",
        False,
    ),
    (
        "AIPRINTWORD_BASE_URL",
        "aiprintword 服务根地址（如 http://127.0.0.1:5050，勿以 / 结尾）；页面1「去签字/去打印」服务端交接用",
        False,
    ),
    (
        "AIPRINTWORD_HANDOFF_SECRET",
        "与 aiprintword 环境变量 AIWORD_HANDOFF_SECRET 相同的密钥（敏感）；用于服务端一次性文件交接",
        True,
    ),
    ("QUIZ_API_BEARER_TOKEN", "考试训练中心后端 Bearer Token（可选）", True),
    ("QUIZ_API_SECRET", "考试训练中心后端集成密钥（X-Integration-Secret，可选）", True),
    (
        "QUIZ_API_TIMEOUT_SECONDS",
        "考试训练中心后端超时时间（秒，默认 20；上限 600。法规/类 LLM 接口建议 ≥180）",
        False,
    ),
    ("EXAM_PASS_SCORE", "考试及格线（分，默认 80；统计端及格率与老师端「考试与录题配置」均可维护）", False),
    ("EXAM_INGEST_TARGET_COUNT", "每批 AI 录题题量（正整数，默认 50；上限 200）", False),
    (
        "EXAM_INGEST_KNOWLEDGE_WEIGHTS",
        "录题知识来源占比（英文逗号分隔四个小数：项目案例、审核点、法规标准、程序文件；和约 1；默认 0.3,0.3,0.2,0.2）",
        False,
    ),
    (
        "EXAM_INGEST_QUESTION_TYPE_WEIGHTS",
        "录题题型占比（英文逗号分隔：单选、多选、判断、案例分析；和约 1；默认 0.3,0.1,0.1,0.5）",
        False,
    ),
    ("EXAM_INGEST_MAX_SIMILAR_FRAC", "录题同一考点近似重复上限比例（0～1，默认 0.1 即 10%）", False),
    ("UPLOAD_FOLDER", "上传文件目录（绝对路径，留空用默认 uploads）", False),
    ("OUTPUT_FOLDER", "文档生成输出目录（绝对路径，留空用默认 outputs）", False),
    (
        "SCHEDULER_INSTANCE_ID",
        "定时任务实例标识（多套部署共库时填不同值则各发一条钉钉；单套部署留空）",
        False,
    ),
    # 功能开关：1=开启入口；0/空=隐藏入口。
    # 默认全部关闭（首次升级后入口隐藏），管理员在页面4 · 系统与钉钉「系统配置」中按需启用。
    # 「上传/替换」「初稿生成」「审核后修改」「翻译」对应页面2 任务列表中的功能按钮；
    # 「考试训练中心」对应页面1/2/3 顶部「进入考试训练中心」按钮。
    (
        "FEATURE_PAGE2_UPLOAD_REPLACE",
        "页面2功能开关 · 上传/替换（1=显示按钮；空或0=隐藏。默认隐藏）",
        False,
    ),
    (
        "FEATURE_PAGE2_DRAFT_GEN",
        "页面2功能开关 · 初稿生成（同时控制顶部「初稿生成」入口；1=显示；空或0=隐藏。默认隐藏）",
        False,
    ),
    (
        "FEATURE_PAGE2_AUDIT_MODIFY",
        "页面2功能开关 · 审核后修改（1=显示；空或0=隐藏。默认隐藏）",
        False,
    ),
    (
        "FEATURE_PAGE2_TRANSLATE",
        "页面2功能开关 · 翻译（1=显示；空或0=隐藏。默认隐藏）",
        False,
    ),
    (
        "FEATURE_EXAM_CENTER",
        "考试训练中心入口开关（页面1/2/3 顶部「进入考试训练中心」按钮；1=显示；空或0=隐藏。默认隐藏）",
        False,
    ),
    (
        "FEATURE_COMPANY_REGISTRY",
        "公司项目总览模块（页面0 与 /api/company/*；1=开启；空或0=关闭。访问密码调试模式不受此项限制）",
        False,
    ),
    (
        "FEATURE_MULTI_TENANT",
        "多公司租户开关（1=启用公司维度隔离；空或0=关闭并保持现网单租户行为）",
        False,
    ),
]


# 功能开关键集合（前端 feature_flags 注入用）。顺序与含义同 SYSTEM_CONFIG_KEYS 中的注释。
FEATURE_FLAG_KEYS: tuple[str, ...] = (
    "FEATURE_PAGE2_UPLOAD_REPLACE",
    "FEATURE_PAGE2_DRAFT_GEN",
    "FEATURE_PAGE2_AUDIT_MODIFY",
    "FEATURE_PAGE2_TRANSLATE",
    "FEATURE_EXAM_CENTER",
    "FEATURE_COMPANY_REGISTRY",
    "FEATURE_MULTI_TENANT",
)

# 页面4 · 系统与钉钉「系统配置」弹窗分区：顺序即展示顺序；keys 须覆盖 SYSTEM_CONFIG_KEYS 全集且无重复。
# defaultExpanded=True 的分区默认展开，其余折叠（details 无 open 属性）。
SYSTEM_CONFIG_SECTIONS: list[dict[str, Any]] = [
    {
        "id": "feature_flags",
        "title": "功能开关",
        "hint": "控制页面2 操作按钮与考试训练中心入口；填 1 开启，留空或 0 关闭。",
        "defaultExpanded": True,
        "keys": FEATURE_FLAG_KEYS,
    },
    {
        "id": "core",
        "title": "基础与安全",
        "hint": "部署、访问控制与对外地址；修改数据库连接后需重启服务。",
        "defaultExpanded": True,
        "keys": (
            "DATABASE_URL",
            "SECRET_KEY",
            "BASE_URL",
            "PAGE13_ACCESS_PASSWORD",
            "INTEGRATION_SECRET",
            "UPLOAD_FOLDER",
            "OUTPUT_FOLDER",
            "SCHEDULER_INSTANCE_ID",
        ),
    },
    {
        "id": "dingtalk_notify",
        "title": "催办与定时通知",
        "hint": "自动催办、定时统计、工作通知用；可与「体系记录机器人」填不同 Webhook，填相同地址则实际为同一机器人。",
        "defaultExpanded": True,
        "keys": (
            "DINGTALK_WEBHOOK",
            "DINGTALK_SECRET",
            "DINGTALK_APP_KEY",
            "DINGTALK_APP_SECRET",
            "DINGTALK_AGENT_ID",
        ),
    },
    {
        "id": "dingtalk_chatbot",
        "title": "体系记录机器人",
        "hint": "HTTP 回调接收群消息并自动回复。下方「钉钉回调 URL」由 BASE_URL 自动生成，复制到开放平台即可（钉钉不支持变量）。",
        "defaultExpanded": True,
        "keys": (
            "DINGTALK_CALLBACK_TOKEN",
            "DINGTALK_CALLBACK_AES_KEY",
            "DINGTALK_CALLBACK_OWNER_KEY",
            "CHATBOT_DINGTALK_WEBHOOK",
            "CHATBOT_DINGTALK_SECRET",
            "CHATBOT_ENABLE",
            "DINGTALK_TRIGGER_KEYWORDS",
            "CHATBOT_ENABLED_GROUPS",
            "CHATBOT_REPLY_COOLDOWN_SECONDS",
            "CHATBOT_CONFIDENCE_THRESHOLD",
            "CHATBOT_LLM_PROVIDER",
            "AICHECKWORD_CHAT_API_BASE",
            "AICHECKWORD_CHAT_API_KEY",
            "AICHECKWORD_CHAT_TIMEOUT_SECONDS",
        ),
    },
    {
        "id": "exam_center",
        "title": "考试训练中心",
        "hint": "考试中心后端地址、鉴权与录题/及格线等业务参数。",
        "defaultExpanded": False,
        "keys": (
            "QUIZ_API_BASE_URL",
            "QUIZ_API_BEARER_TOKEN",
            "QUIZ_API_SECRET",
            "QUIZ_API_TIMEOUT_SECONDS",
            "EXAM_PASS_SCORE",
            "EXAM_INGEST_TARGET_COUNT",
            "EXAM_INGEST_KNOWLEDGE_WEIGHTS",
            "EXAM_INGEST_QUESTION_TYPE_WEIGHTS",
            "EXAM_INGEST_MAX_SIMILAR_FRAC",
        ),
    },
    {
        "id": "aicheckword",
        "title": "aicheckword 集成",
        "hint": "初稿、审核、翻译等对接地址与超时；可与考试中心使用不同端口。",
        "defaultExpanded": False,
        "keys": (
            "AICHECKWORD_DRAFT_API_BASE",
            "AICHECKWORD_DRAFT_TIMEOUT_SECONDS",
            "AICHECKWORD_DRAFT_CONNECT_TIMEOUT_SECONDS",
            "AICHECKWORD_AUDIT_TIMEOUT_SECONDS",
            "AICHECKWORD_TRANSLATION_TIMEOUT_SECONDS",
            "AICHECKWORD_DRAFT_COLLECTION_IDS",
        ),
    },
    {
        "id": "aiprintword",
        "title": "aiprintword 签字/打印",
        "hint": "页面1「去签字/去打印」服务端交接用。",
        "defaultExpanded": False,
        "keys": (
            "AIPRINTWORD_BASE_URL",
            "AIPRINTWORD_HANDOFF_SECRET",
        ),
    },
]

_sections_validated = False


def _validate_system_config_sections() -> None:
    """开发期校验：分区键与 SYSTEM_CONFIG_KEYS 一致，避免漏配或重复。"""
    global _sections_validated
    if _sections_validated:
        return
    all_keys = {k for k, _, _ in SYSTEM_CONFIG_KEYS}
    seen: set[str] = set()
    for sec in SYSTEM_CONFIG_SECTIONS:
        for key in sec.get("keys") or ():
            if key in seen:
                raise ValueError(f"系统配置分区重复键: {key}")
            seen.add(key)
    missing = all_keys - seen
    extra = seen - all_keys
    if missing or extra:
        raise ValueError(
            f"系统配置分区与 SYSTEM_CONFIG_KEYS 不一致: missing={sorted(missing)} extra={sorted(extra)}"
        )
    _sections_validated = True


def system_config_sections_for_api() -> list[dict[str, Any]]:
    """供 GET /api/system-settings 返回的分区元数据。"""
    _validate_system_config_sections()
    out: list[dict[str, Any]] = []
    for sec in SYSTEM_CONFIG_SECTIONS:
        keys = sec.get("keys") or ()
        out.append(
            {
                "id": str(sec["id"]),
                "title": str(sec["title"]),
                "hint": str(sec.get("hint") or ""),
                "defaultExpanded": bool(sec.get("defaultExpanded", False)),
                "keys": list(keys),
            }
        )
    return out


CHATBOT_CALLBACK_API_PATH = "/api/dingtalk/chatbot/callback"


def chatbot_callback_url_info(base_url: str = "") -> dict[str, Any]:
    """由 BASE_URL 生成钉钉 HTTP 回调完整 URL（供页面展示与复制）。"""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return {
            "ready": False,
            "baseUrl": "",
            "url": "",
            "path": CHATBOT_CALLBACK_API_PATH,
            "hint": "请先在「基础与安全」填写 BASE_URL（调试填穿透地址，正式填域名）",
        }
    return {
        "ready": True,
        "baseUrl": base,
        "url": f"{base}{CHATBOT_CALLBACK_API_PATH}",
        "path": CHATBOT_CALLBACK_API_PATH,
        "hint": "复制到钉钉开放平台机器人/事件订阅的回调 URL；切换环境时修改 BASE_URL 后重新复制",
    }


def _parse_flag(raw: Optional[str]) -> bool:
    """解析功能开关字符串：仅当值为 1/true/yes/on（忽略大小写）时视为开启。"""
    if raw is None:
        return False
    s = str(raw).replace("\ufeff", "").replace("\u200b", "").strip().lower()
    return s in {"1", "true", "yes", "on", "y", "t"}


def feature_flags_for_template(app: Optional["Flask"] = None) -> dict[str, bool]:
    """返回当前数据库内 5 个功能开关的布尔值，便于注入 Jinja / 前端。"""
    out: dict[str, bool] = {}
    for key in FEATURE_FLAG_KEYS:
        out[key] = _parse_flag(get_setting(key, default="", app=app))
    return out


def is_feature_admin_viewer() -> bool:
    """页面2 功能开关管理员视角：页面1/3 已验证，或管理员/分级管理员账号。"""
    try:
        from flask import has_request_context, session
    except Exception:
        return False
    if not has_request_context():
        return False
    if session.get("page13_authenticated"):
        return True
    uid = session.get("user_id")
    if not uid:
        return False
    try:
        from .models import User, ADMIN_ROLE_COMPANY, ADMIN_ROLE_PROJECT

        u = User.query.get(uid)
        if not u:
            return False
        if getattr(u, "is_admin", False):
            return True
        role = (getattr(u, "admin_role", None) or "none").strip()
        return role in (ADMIN_ROLE_COMPANY, ADMIN_ROLE_PROJECT)
    except Exception:
        return False


def effective_feature_flags_for_request(app: Optional["Flask"] = None) -> dict[str, bool]:
    """当前请求生效的功能开关（管理员始终视为全开）。"""
    if is_feature_admin_viewer():
        return {k: True for k in FEATURE_FLAG_KEYS}
    return feature_flags_for_template(app)


def is_multi_tenant_enabled(app: Optional["Flask"] = None) -> bool:
    """多公司租户总开关（默认关闭，关闭时保持现网行为）。"""
    return _parse_flag(get_setting("FEATURE_MULTI_TENANT", default="", app=app))


SENSITIVE_KEYS = {k for k, _, sens in SYSTEM_CONFIG_KEYS if sens}

# 老师端考试中心「考试与录题配置」弹窗展示的键（须为 SYSTEM_CONFIG_KEYS 的子集，顺序即展示顺序）
EXAM_CENTER_TEACHER_SETTINGS_KEYS: tuple[str, ...] = (
    "EXAM_PASS_SCORE",
    "EXAM_INGEST_TARGET_COUNT",
    "EXAM_INGEST_KNOWLEDGE_WEIGHTS",
    "EXAM_INGEST_QUESTION_TYPE_WEIGHTS",
    "EXAM_INGEST_MAX_SIMILAR_FRAC",
)

# config.json 中可能出现的别名（键名不一致时仍能读到）
CONFIG_JSON_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "DINGTALK_WEBHOOK": (
        "DINGTALK_WEBHOOK",
        "dingtalk_webhook",
        "dingtalkWebhook",
        "DINGTALK_ROBOT_WEBHOOK",
    ),
    "DINGTALK_SECRET": ("DINGTALK_SECRET", "dingtalk_secret", "dingtalkSecret"),
    "CHATBOT_DINGTALK_WEBHOOK": (
        "CHATBOT_DINGTALK_WEBHOOK",
        "chatbot_dingtalk_webhook",
        "chatbotDingtalkWebhook",
    ),
    "CHATBOT_DINGTALK_SECRET": (
        "CHATBOT_DINGTALK_SECRET",
        "chatbot_dingtalk_secret",
        "chatbotDingtalkSecret",
    ),
    "PAGE13_ACCESS_PASSWORD": (
        "PAGE13_ACCESS_PASSWORD",
        "page13_access_password",
        "page13AccessPassword",
        "PAGE13_PASSWORD",
        "page13_password",
        "page1_password",
        "page13Password",
    ),
    "INTEGRATION_SECRET": ("INTEGRATION_SECRET", "integration_secret", "integrationSecret"),
    "BASE_URL": ("BASE_URL", "base_url", "baseUrl"),
    "SECRET_KEY": ("SECRET_KEY", "secret_key", "secretKey"),
    "DINGTALK_APP_KEY": ("DINGTALK_APP_KEY", "dingtalk_app_key"),
    "DINGTALK_APP_SECRET": ("DINGTALK_APP_SECRET", "dingtalk_app_secret"),
    "DINGTALK_AGENT_ID": ("DINGTALK_AGENT_ID", "dingtalk_agent_id"),
    "DINGTALK_CALLBACK_TOKEN": ("DINGTALK_CALLBACK_TOKEN", "dingtalk_callback_token"),
    "DINGTALK_CALLBACK_AES_KEY": ("DINGTALK_CALLBACK_AES_KEY", "dingtalk_callback_aes_key"),
    "DINGTALK_CALLBACK_OWNER_KEY": ("DINGTALK_CALLBACK_OWNER_KEY", "dingtalk_callback_owner_key"),
    "QUIZ_API_BASE_URL": ("QUIZ_API_BASE_URL", "quiz_api_base_url", "quizApiBaseUrl"),
    "AICHECKWORD_DRAFT_API_BASE": (
        "AICHECKWORD_DRAFT_API_BASE",
        "aicheckword_draft_api_base",
        "aicheckwordDraftApiBase",
    ),
    "AICHECKWORD_DRAFT_TIMEOUT_SECONDS": (
        "AICHECKWORD_DRAFT_TIMEOUT_SECONDS",
        "aicheckword_draft_timeout_seconds",
        "aicheckwordDraftTimeoutSeconds",
    ),
    "AICHECKWORD_DRAFT_CONNECT_TIMEOUT_SECONDS": (
        "AICHECKWORD_DRAFT_CONNECT_TIMEOUT_SECONDS",
        "aicheckword_draft_connect_timeout_seconds",
        "aicheckwordDraftConnectTimeoutSeconds",
    ),
    "AICHECKWORD_AUDIT_TIMEOUT_SECONDS": (
        "AICHECKWORD_AUDIT_TIMEOUT_SECONDS",
        "aicheckword_audit_timeout_seconds",
        "aicheckwordAuditTimeoutSeconds",
    ),
    "AICHECKWORD_TRANSLATION_TIMEOUT_SECONDS": (
        "AICHECKWORD_TRANSLATION_TIMEOUT_SECONDS",
        "aicheckword_translation_timeout_seconds",
        "aicheckwordTranslationTimeoutSeconds",
    ),
    "AICHECKWORD_DRAFT_COLLECTION_IDS": (
        "AICHECKWORD_DRAFT_COLLECTION_IDS",
        "aicheckword_draft_collection_ids",
        "aicheckwordDraftCollectionIds",
    ),
    "AICHECKWORD_CHAT_API_BASE": (
        "AICHECKWORD_CHAT_API_BASE",
        "aicheckword_chat_api_base",
        "aicheckwordChatApiBase",
    ),
    "AICHECKWORD_CHAT_TIMEOUT_SECONDS": (
        "AICHECKWORD_CHAT_TIMEOUT_SECONDS",
        "aicheckword_chat_timeout_seconds",
        "aicheckwordChatTimeoutSeconds",
    ),
    "AICHECKWORD_CHAT_API_KEY": (
        "AICHECKWORD_CHAT_API_KEY",
        "aicheckword_chat_api_key",
        "aicheckwordChatApiKey",
    ),
    "AIPRINTWORD_BASE_URL": (
        "AIPRINTWORD_BASE_URL",
        "aiprintword_base_url",
        "aiprintwordBaseUrl",
    ),
    "AIPRINTWORD_HANDOFF_SECRET": (
        "AIPRINTWORD_HANDOFF_SECRET",
        "aiprintword_handoff_secret",
        "aiprintwordHandoffSecret",
    ),
    "QUIZ_API_BEARER_TOKEN": ("QUIZ_API_BEARER_TOKEN", "quiz_api_bearer_token", "quizApiBearerToken"),
    "QUIZ_API_SECRET": ("QUIZ_API_SECRET", "quiz_api_secret", "quizApiSecret"),
    "QUIZ_API_TIMEOUT_SECONDS": ("QUIZ_API_TIMEOUT_SECONDS", "quiz_api_timeout_seconds", "quizApiTimeoutSeconds"),
}

# 每个 config.json 绝对路径 -> (mtime_ns, data)
_config_json_per_file: dict[str, tuple[int, dict[str, Any]]] = {}

# 环境变量名（可多选）；部分键再做大写不敏感匹配
ENV_VAR_NAMES: dict[str, tuple[str, ...]] = {
    "DINGTALK_WEBHOOK": (
        "DINGTALK_WEBHOOK",
        "dingtalk_webhook",
        "DINGTALK_ROBOT_WEBHOOK",
    ),
    "DINGTALK_SECRET": ("DINGTALK_SECRET", "dingtalk_secret"),
    "PAGE13_ACCESS_PASSWORD": ("PAGE13_ACCESS_PASSWORD", "PAGE13_PASSWORD"),
    "INTEGRATION_SECRET": ("INTEGRATION_SECRET",),
    "BASE_URL": ("BASE_URL", "base_url"),
    "SECRET_KEY": ("SECRET_KEY", "SECRET_KEY_FLASK"),
    "QUIZ_API_BASE_URL": ("QUIZ_API_BASE_URL",),
    "QUIZ_API_BEARER_TOKEN": ("QUIZ_API_BEARER_TOKEN",),
    "QUIZ_API_SECRET": ("QUIZ_API_SECRET",),
    "QUIZ_API_TIMEOUT_SECONDS": ("QUIZ_API_TIMEOUT_SECONDS",),
    "AICHECKWORD_DRAFT_API_BASE": ("AICHECKWORD_DRAFT_API_BASE",),
    "AICHECKWORD_DRAFT_TIMEOUT_SECONDS": ("AICHECKWORD_DRAFT_TIMEOUT_SECONDS",),
    "AICHECKWORD_DRAFT_CONNECT_TIMEOUT_SECONDS": ("AICHECKWORD_DRAFT_CONNECT_TIMEOUT_SECONDS",),
    "AICHECKWORD_AUDIT_TIMEOUT_SECONDS": ("AICHECKWORD_AUDIT_TIMEOUT_SECONDS",),
    "AICHECKWORD_TRANSLATION_TIMEOUT_SECONDS": ("AICHECKWORD_TRANSLATION_TIMEOUT_SECONDS",),
    "AICHECKWORD_DRAFT_COLLECTION_IDS": ("AICHECKWORD_DRAFT_COLLECTION_IDS",),
    "AICHECKWORD_CHAT_API_BASE": ("AICHECKWORD_CHAT_API_BASE",),
    "AICHECKWORD_CHAT_API_KEY": ("AICHECKWORD_CHAT_API_KEY",),
    "AICHECKWORD_CHAT_TIMEOUT_SECONDS": ("AICHECKWORD_CHAT_TIMEOUT_SECONDS",),
    "AIPRINTWORD_BASE_URL": ("AIPRINTWORD_BASE_URL",),
    "AIPRINTWORD_HANDOFF_SECRET": ("AIPRINTWORD_HANDOFF_SECRET", "AIWORD_HANDOFF_SECRET"),
}

# 这些键在 os.environ 里按「名称大写相等」再扫一遍（解决 Windows 等环境下变量名不一致）
_ENV_CASEFOLD_KEYS = frozenset(
    {
        "DINGTALK_WEBHOOK",
        "DINGTALK_SECRET",
        "PAGE13_ACCESS_PASSWORD",
        "INTEGRATION_SECRET",
        "BASE_URL",
        "SECRET_KEY",
        "QUIZ_API_BASE_URL",
        "QUIZ_API_BEARER_TOKEN",
        "QUIZ_API_SECRET",
        "QUIZ_API_TIMEOUT_SECONDS",
        "AICHECKWORD_DRAFT_CONNECT_TIMEOUT_SECONDS",
        "AIPRINTWORD_HANDOFF_SECRET",
    }
)


def _db_value_blocks_fallback(raw: Optional[str]) -> bool:
    """库里有「有效内容」时不再用环境变量/config.json 覆盖。"""
    if raw is None:
        return False
    s = (
        str(raw)
        .replace("\ufeff", "")
        .replace("\u200b", "")
        .replace("\r", "")
        .strip()
    )
    if not s:
        return False
    if s in ("(不变)", "***", "******", "(未改)"):
        return False
    return True


def _read_config_json_at(root: Path) -> dict[str, Any]:
    p = (root / "config.json").resolve()
    if not p.is_file():
        return {}
    key = str(p)
    try:
        mtime = p.stat().st_mtime_ns
    except OSError:
        return {}
    hit = _config_json_per_file.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        import json

        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
        data = raw if isinstance(raw, dict) else {}
        _config_json_per_file[key] = (mtime, data)
        return data
    except Exception:
        return {}


def _config_search_roots(app: Optional["Flask"], project_root: Optional[Path]) -> list[Path]:
    """可能放置 config.json 的目录（项目根、webapp 上级、当前工作目录等）。"""
    seen: set[Path] = set()
    out: list[Path] = []
    extra = (os.environ.get("AIWORD_PROJECT_ROOT") or "").strip()
    if extra:
        try:
            ep = Path(extra).resolve()
            if ep not in seen:
                seen.add(ep)
                out.append(ep)
        except Exception:
            pass
    candidates: list[Optional[Path]] = []
    if project_root:
        candidates.append(project_root)
        try:
            candidates.append(project_root.parent)
        except Exception:
            pass
    if app:
        try:
            rp = Path(app.root_path).resolve()
            candidates.append(rp)
            candidates.append(rp.parent)
        except Exception:
            pass
    try:
        candidates.append(Path.cwd().resolve())
    except Exception:
        pass
    for r in candidates:
        if r is None:
            continue
        try:
            rp = Path(r).resolve()
        except Exception:
            continue
        if rp in seen:
            continue
        seen.add(rp)
        out.append(rp)
    return out


def _value_from_config_json_in_roots(roots: list[Path], key: str) -> str:
    names: tuple[str, ...] = (key,) + CONFIG_JSON_KEY_ALIASES.get(key, ())
    for root in roots:
        data = _read_config_json_at(root)
        if not data:
            continue
        for nk in names:
            if nk not in data:
                continue
            val = data.get(nk)
            if val is not None and str(val).strip():
                return str(val).strip()
    return ""


def _first_env_value(key: str) -> str:
    names = ENV_VAR_NAMES.get(key, (key,))
    for n in names:
        v = os.environ.get(n)
        if v is not None and str(v).strip():
            return str(v).strip()
    if key not in _ENV_CASEFOLD_KEYS:
        return ""
    want = {n.upper() for n in names}
    for ek, ev in os.environ.items():
        if not ev or not str(ev).strip():
            continue
        if ek.upper() in want:
            return str(ev).strip()
    return ""


def _merged_external_value(key: str, roots: list[Path]) -> str:
    """
    库为空时要展示/同步的值：钉钉类优先环境变量；页面密码等优先 config.json。
    """
    if key in ("DINGTALK_WEBHOOK", "DINGTALK_SECRET", "CHATBOT_DINGTALK_WEBHOOK", "CHATBOT_DINGTALK_SECRET"):
        v = _first_env_value(key)
        if v:
            return v
        return _value_from_config_json_in_roots(roots, key)
    if key == "PAGE13_ACCESS_PASSWORD":
        v = _value_from_config_json_in_roots(roots, key)
        if v:
            return v
        return _first_env_value(key)
    v = _value_from_config_json_in_roots(roots, key)
    if v:
        return v
    return _first_env_value(key)


def _value_from_config_json(project_root: Path, key: str) -> str:
    roots = _config_search_roots(None, project_root)
    return _value_from_config_json_in_roots(roots, key)


def _project_root_from_app(app: Optional["Flask"]) -> Optional[Path]:
    if app is None:
        return None
    try:
        return Path(app.root_path).resolve().parent
    except Exception:
        return None


def _bootstrap_database_url_file(project_root: Path) -> Optional[str]:
    p = project_root / "instance" / "database_url.txt"
    if not p.exists():
        return None
    try:
        line = p.read_text(encoding="utf-8").strip().split("\n")[0].strip()
        return line or None
    except OSError:
        return None


def normalize_database_uri_for_engine(uri: str, connect_timeout: int = 10) -> str:
    """
    规范 MySQL 连接 URI 的查询参数。
    重复 connect_timeout（如页面4 已带 + 启动代码再拼）会被解析为 tuple，导致 db.init_app 失败。
    """
    u = (uri or "").strip()
    if not u.startswith("mysql"):
        return u
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(u)
    q: dict[str, str] = {}
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        q[k] = v
    q["connect_timeout"] = str(max(1, int(connect_timeout)))
    return urlunparse(parsed._replace(query=urlencode(q)))


def _persist_database_url_bootstrap_file(project_root: Path, uri: str) -> None:
    """将页面4 保存的 URI 写入启动缓存（仅由 save_system_settings / resolve 同步，非环境变量）。"""
    val = (uri or "").strip()
    if not val or "****" in val:
        return
    inst = project_root / "instance"
    inst.mkdir(parents=True, exist_ok=True)
    (inst / "database_url.txt").write_text(val + "\n", encoding="utf-8")


def _fetch_database_url_from_config_table(database_uri: str) -> Optional[str]:
    """
    从指定库连接读取 app_configs.DATABASE_URL（页面4 系统配置落库值）。
    用于冷启动：先用启动缓存 URI 连库，再以库内配置为准。
    """
    uri = (database_uri or "").strip()
    if not uri:
        return None
    try:
        from sqlalchemy import create_engine, text

        eng = create_engine(normalize_database_uri_for_engine(uri))
        try:
            with eng.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT config_value FROM app_configs "
                        "WHERE config_key = :k LIMIT 1"
                    ),
                    {"k": "DATABASE_URL"},
                ).fetchone()
        finally:
            eng.dispose()
        if not row or row[0] is None:
            return None
        v = str(row[0]).replace("\ufeff", "").strip()
        if not v or "****" in v:
            return None
        return v
    except Exception:
        return None


def resolve_database_uri(project_root: Path, default_uri: str) -> str:
    """
    冷启动解析数据库 URI：以页面4 写入 app_configs 的 DATABASE_URL 为唯一业务来源。

    顺序：先「内置默认 URI」、再「启动缓存 database_url.txt」尝试连库并读 app_configs
    （避免启动缓存指向测试库时，抢先读到测试库内错误配置而永远连不上正式库）；
    读到则采用并回写启动缓存；否则用启动缓存；再否则用内置默认（仅首次无配置）。
    不读取环境变量 DATABASE_URL。
    """
    import logging

    log = logging.getLogger(__name__)
    boot = _bootstrap_database_url_file(project_root)
    default_uri = (default_uri or "").strip()
    tried: list[str] = []
    for uri in (default_uri, boot):
        u = (uri or "").strip()
        if not u or u in tried:
            continue
        tried.append(u)
        from_db = _fetch_database_url_from_config_table(u)
        if from_db:
            from_db = normalize_database_uri_for_engine(from_db)
            _persist_database_url_bootstrap_file(project_root, from_db)
            log.info("数据库 URI 来自页面4 系统配置 (app_configs)")
            return from_db
    if boot:
        log.warning(
            "启动缓存 database_url.txt 指向的库中未找到 DATABASE_URL 配置项，"
            "暂用该缓存连接；请在页面4 系统配置保存正确 URI 后重启"
        )
        return normalize_database_uri_for_engine(boot)
    if default_uri:
        log.warning(
            "未在 app_configs 中找到 DATABASE_URL，使用内置默认连接；"
            "请在页面4 系统配置填写并保存数据库连接 URI"
        )
        return normalize_database_uri_for_engine(default_uri)
    return ""


def get_setting(key: str, default: str = "", app: Optional["Flask"] = None) -> str:
    """读取配置：有效库值 > 环境变量/config.json（按项合并，见 _merged_external_value）。"""
    from . import db
    from .models import AppConfig

    flask_app = app
    if flask_app is None:
        try:
            from flask import current_app
            flask_app = current_app._get_current_object()
        except RuntimeError:
            flask_app = None

    if key == "DATABASE_URL":
        # 仅页面4 系统配置（app_configs）；不回落环境变量或启动缓存文件
        if flask_app is not None:
            try:
                with flask_app.app_context():
                    row = AppConfig.query.filter_by(config_key=key).first()
                    if row and row.config_value is not None:
                        v = str(row.config_value).replace("\ufeff", "").strip()
                        if v and "****" not in v:
                            return v
            except Exception:
                pass
        return default

    if flask_app is not None:
        try:
            with flask_app.app_context():
                row = AppConfig.query.filter_by(config_key=key).first()
                raw = row.config_value if row and row.config_value is not None else None
                if _db_value_blocks_fallback(raw):
                    return str(raw).replace("\ufeff", "").strip()
        except Exception:
            pass

    pr = _project_root_from_app(flask_app)
    if pr is None and flask_app is None:
        try:
            from flask import current_app as ca

            pr = _project_root_from_app(ca._get_current_object())
        except RuntimeError:
            pass
    roots = _config_search_roots(flask_app, pr)
    ext = _merged_external_value(key, roots)
    if ext:
        return ext
    return default


def get_setting_for_scheduler(key: str, default: str = "", app: Optional["Flask"] = None) -> str:
    """供无 request 上下文的后台线程使用，须传入 app。"""
    return get_setting(key, default=default, app=app)


def _upsert_config(key: str, value: str) -> None:
    from . import db
    from .models import AppConfig

    row = AppConfig.query.filter_by(config_key=key).first()
    if row:
        row.config_value = value or ""
        db.session.add(row)
    else:
        db.session.add(AppConfig(config_key=key, config_value=value or ""))


def save_system_settings(
    updates: dict[str, str],
    project_root: Path,
    skip_unchanged_sensitive: bool = True,
) -> list[str]:
    """
    保存系统配置。若某敏感项前端传占位符 *** 或 (不变) 且 skip_unchanged_sensitive，则保留原值。
    非敏感项传空字符串时不覆盖库内已有值（避免表单未带出默认值时误清空）。
    """
    from . import db
    from .models import AppConfig

    written = []
    for key, raw in updates.items():
        if key not in {k for k, _, _ in SYSTEM_CONFIG_KEYS}:
            continue
        val = (raw or "").strip()
        if key == "DATABASE_URL":
            if not val:
                continue
            # 表单展示为脱敏串，勿写回库
            if "****" in val:
                continue
            val = normalize_database_uri_for_engine(val)
            _upsert_config(key, val)
            written.append(key)
            _persist_database_url_bootstrap_file(project_root, val)
            continue
        if key in SENSITIVE_KEYS and skip_unchanged_sensitive and (
            val == "***" or val == "(不变)" or val == "******"
        ):
            continue
        # 允许清空，便于从「多实例」恢复为默认全库去重
        if key == "SCHEDULER_INSTANCE_ID":
            _upsert_config(key, val)
            written.append(key)
            continue
        # 功能开关：允许清空以关闭功能（默认即关闭），不能因「非敏感空串不覆盖」而锁住
        if key in FEATURE_FLAG_KEYS:
            _upsert_config(key, val)
            written.append(key)
            continue
        if key not in SENSITIVE_KEYS and not val:
            row = AppConfig.query.filter_by(config_key=key).first()
            if row and _db_value_blocks_fallback(row.config_value):
                continue
        _upsert_config(key, val)
        written.append(key)

    db.session.commit()
    return written


def sync_authoritative_sources_into_db(project_root: Path, flask_app: Optional["Flask"] = None) -> None:
    """
    仅在库中对应项为空时，用环境变量 / config.json 补全（首次部署、迁移）。
    库中已有有效值时不再覆盖，避免「已在库里更新」却被每次打开配置页用 env/json 旧值冲掉。
    """
    from . import db
    from .models import AppConfig

    def _db_raw(key: str) -> Optional[str]:
        row = AppConfig.query.filter_by(config_key=key).first()
        return row.config_value if row and row.config_value is not None else None

    changed = False
    w = (_first_env_value("DINGTALK_WEBHOOK") or "").strip()
    if w and not _db_value_blocks_fallback(_db_raw("DINGTALK_WEBHOOK")):
        _upsert_config("DINGTALK_WEBHOOK", w)
        changed = True
    s = (_first_env_value("DINGTALK_SECRET") or "").strip()
    if s and not _db_value_blocks_fallback(_db_raw("DINGTALK_SECRET")):
        _upsert_config("DINGTALK_SECRET", s)
        changed = True

    roots = _config_search_roots(flask_app, project_root)
    p = (_value_from_config_json_in_roots(roots, "PAGE13_ACCESS_PASSWORD") or "").strip()
    if p and not _db_value_blocks_fallback(_db_raw("PAGE13_ACCESS_PASSWORD")):
        _upsert_config("PAGE13_ACCESS_PASSWORD", p)
        changed = True

    if changed:
        db.session.commit()


MIGRATION_FLAG_KEY = "ENV_TO_DB_MIGRATED"


def seed_system_settings_from_environment(
    project_root: Path,
    startup_database_uri: str = "",
    flask_app: Optional["Flask"] = None,
) -> None:
    """已迁移后：库中某项仍为空时，用环境变量 / config.json / 当前库连接补全。"""
    from . import db
    from .models import AppConfig

    for key, _, _ in SYSTEM_CONFIG_KEYS:
        row = AppConfig.query.filter_by(config_key=key).first()
        raw = row.config_value if row and row.config_value is not None else None
        if _db_value_blocks_fallback(raw):
            continue
        if key == "DATABASE_URL":
            val = (startup_database_uri or "").strip()
        else:
            val = _first_env_value(key)
        if not val:
            continue
        _upsert_config(key, val)

    persist_config_json_into_empty_db_keys(project_root, flask_app)


def ensure_environment_variables_migrated_to_db(
    project_root: Path,
    startup_database_uri: str = "",
    flask_app: Optional["Flask"] = None,
) -> None:
    """
    首次启动：将当前进程环境变量（含 .env 加载后）中已有的配置写入 app_configs，实现自动迁移。
    仅当库中 ENV_TO_DB_MIGRATED 未为 1 时执行整包写入；之后仅对空项补全。
    """
    from . import db
    from .models import AppConfig

    flag_row = AppConfig.query.filter_by(config_key=MIGRATION_FLAG_KEY).first()
    already_done = flag_row and (flag_row.config_value or "").strip() == "1"

    if already_done:
        seed_system_settings_from_environment(
            project_root, startup_database_uri, flask_app
        )
        return

    for key, _, _ in SYSTEM_CONFIG_KEYS:
        if key == "DATABASE_URL":
            val = (startup_database_uri or "").strip()
        else:
            val = _first_env_value(key)
        if val:
            _upsert_config(key, val)

    persist_config_json_into_empty_db_keys(project_root, flask_app)

    _upsert_config(MIGRATION_FLAG_KEY, "1")
    db.session.commit()

    db_v = (startup_database_uri or "").strip()
    if db_v:
        _persist_database_url_bootstrap_file(project_root, db_v)


def sync_database_url_bootstrap_from_app_configs(
    app: "Flask", project_root: Path
) -> None:
    """运行期：将 app_configs 中的 DATABASE_URL 同步到启动缓存文件（与页面4 保存一致）。"""
    v = (get_setting("DATABASE_URL", default="", app=app) or "").strip()
    if v:
        _persist_database_url_bootstrap_file(project_root, v)


def apply_system_settings_to_flask(app: "Flask", project_root: Path) -> None:
    """将数据库中的配置同步到 app.config（启动时及保存后调用）。"""
    import logging

    _log = logging.getLogger(__name__)
    for key, _, _ in SYSTEM_CONFIG_KEYS:
        if key == "DATABASE_URL":
            continue
        v = get_setting(key, default="", app=app)
        if key in ("UPLOAD_FOLDER", "OUTPUT_FOLDER"):
            if v:
                try:
                    Path(v).mkdir(parents=True, exist_ok=True)
                    app.config[key] = v
                except OSError as e:
                    # 迁机后库中仍为旧盘符路径（如无 D: 盘）会导致启动失败，保留 create_app 已设的默认目录
                    _log.warning(
                        "系统配置 %s=%r 无法创建或使用，已忽略并沿用项目默认目录: %s",
                        key,
                        v[:80] + ("…" if len(v) > 80 else ""),
                        e,
                    )
            continue
        if v:
            app.config[key] = v

    sk = get_setting("SECRET_KEY", default="", app=app)
    if sk:
        app.config["SECRET_KEY"] = sk
    else:
        app.config.setdefault("SECRET_KEY", "aiword-dev-secret-key-change-in-production")

    app.config["DINGTALK_WEBHOOK"] = get_setting("DINGTALK_WEBHOOK", default="", app=app)
    app.config["DINGTALK_SECRET"] = get_setting("DINGTALK_SECRET", default="", app=app)
    app.config["BASE_URL"] = get_setting("BASE_URL", default="", app=app)
    app.config["PAGE13_ACCESS_PASSWORD"] = get_setting("PAGE13_ACCESS_PASSWORD", default="", app=app) or None
    app.config["INTEGRATION_SECRET"] = get_setting("INTEGRATION_SECRET", default="", app=app)


def persist_config_json_into_empty_db_keys(
    project_root: Path, flask_app: Optional["Flask"] = None
) -> bool:
    """
    库中无有效值时，用环境变量 + 多路径 config.json 写入数据库（钉钉优先 env，页面密码优先 json）。
    """
    from . import db
    from .models import AppConfig

    roots = _config_search_roots(flask_app, project_root)
    changed = False
    for key, _, _ in SYSTEM_CONFIG_KEYS:
        if key == "DATABASE_URL":
            continue
        row = AppConfig.query.filter_by(config_key=key).first()
        raw = row.config_value if row and row.config_value is not None else None
        if _db_value_blocks_fallback(raw):
            continue
        nv = _merged_external_value(key, roots)
        if nv:
            _upsert_config(key, nv)
            changed = True
    if changed:
        db.session.commit()
    return changed


def _effective_database_url(app: "Flask", project_root: Path) -> str:
    """页面4 系统配置中的 DATABASE_URL；未配置时展示当前进程实际连接 URI。"""
    v = (get_setting("DATABASE_URL", default="", app=app) or "").strip()
    if v:
        return v
    running = (app.config.get("SQLALCHEMY_DATABASE_URI") or "").strip()
    if running:
        return running
    return (_bootstrap_database_url_file(project_root) or "").strip()


def get_database_uri(app: Optional["Flask"] = None, project_root: Optional[Path] = None) -> str:
    """
    供业务/脚本读取：优先 app_configs（页面4 系统配置），无 Flask 上下文时用 resolve_database_uri。
    """
    if app is not None:
        v = (get_setting("DATABASE_URL", default="", app=app) or "").strip()
        if v:
            return v
    pr = project_root or _project_root_from_app(app)
    if pr is not None:
        return resolve_database_uri(pr, (app.config.get("SQLALCHEMY_DATABASE_URI") if app else "") or "")
    return ""


def system_settings_for_api_get(app: "Flask", project_root: Path) -> dict[str, Any]:
    """供 GET：以 app_configs 为准；接口已要求页面1/3 访问校验，敏感项直接返回库内值便于展示与修改（DATABASE_URL 仍脱敏）。"""
    from . import db
    from .models import AppConfig

    try:
        db.session.expire_all()
    except Exception:
        pass

    out: dict[str, Any] = {}
    effective_db = _effective_database_url(app, project_root)
    for key, label, sensitive in SYSTEM_CONFIG_KEYS:
        if key == "DATABASE_URL":
            out[key] = _mask_db_uri(effective_db) if effective_db else ""
            continue
        row = AppConfig.query.filter_by(config_key=key).first()
        db_v = ""
        if row is not None and row.config_value is not None:
            db_v = str(row.config_value).replace("\ufeff", "").strip()

        if sensitive:
            out[key] = db_v if _db_value_blocks_fallback(db_v) else ""
            continue

        if db_v:
            out[key] = db_v
            continue

        v = (get_setting(key, default="", app=app) or "").strip()
        if key in ("UPLOAD_FOLDER", "OUTPUT_FOLDER") and not v:
            v = (str(app.config.get(key) or "")).strip()
        out[key] = v
    return out


def _mask_db_uri(uri: str) -> str:
    if not uri or len(uri) < 12:
        return "******"
    if "@" in uri:
        try:
            pre, rest = uri.split("@", 1)
            if "://" in pre:
                scheme, auth = pre.split("://", 1)
                if ":" in auth:
                    user = auth.split(":")[0]
                    return f"{scheme}://{user}:****@{rest}"
        except Exception:
            pass
    return uri[:8] + "****" + uri[-6:] if len(uri) > 20 else "******"
