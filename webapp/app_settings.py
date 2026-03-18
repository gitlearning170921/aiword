# -*- coding: utf-8 -*-
"""
系统级配置：优先从数据库 app_configs 读取，兼容环境变量（库中无值时回退）。
页面3「系统配置」维护；敏感项 GET 时脱敏。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from flask import Flask

# 与历史环境变量名一致，便于迁移
SYSTEM_CONFIG_KEYS: list[tuple[str, str, bool]] = [
    ("DATABASE_URL", "数据库连接 URI（保存后写入 instance/database_url.txt，重启后生效；也可继续用环境变量 DATABASE_URL）", True),
    ("SECRET_KEY", "Flask Session 密钥", True),
    ("BASE_URL", "对外访问根地址（催办链接等，勿以 / 结尾）", False),
    ("DINGTALK_WEBHOOK", "钉钉群机器人 Webhook", True),
    ("DINGTALK_SECRET", "钉钉机器人加签 Secret", True),
    ("DINGTALK_APP_KEY", "钉钉工作通知 AppKey", False),
    ("DINGTALK_APP_SECRET", "钉钉工作通知 AppSecret", True),
    ("DINGTALK_AGENT_ID", "钉钉工作通知 AgentId", False),
    ("PAGE13_ACCESS_PASSWORD", "页面1/3 访问密码", True),
    ("INTEGRATION_SECRET", "开放接口校验密钥（INTEGRATION_SECRET）", True),
    ("UPLOAD_FOLDER", "上传文件目录（绝对路径，留空用默认 uploads）", False),
    ("OUTPUT_FOLDER", "文档生成输出目录（绝对路径，留空用默认 outputs）", False),
]

SENSITIVE_KEYS = {k for k, _, sens in SYSTEM_CONFIG_KEYS if sens}


def _bootstrap_database_url_file(project_root: Path) -> Optional[str]:
    p = project_root / "instance" / "database_url.txt"
    if not p.exists():
        return None
    try:
        line = p.read_text(encoding="utf-8").strip().split("\n")[0].strip()
        return line or None
    except OSError:
        return None


def resolve_database_uri(project_root: Path, default_uri: str) -> str:
    """启动时解析数据库 URI：环境变量 > instance/database_url.txt > 默认值"""
    env = (os.environ.get("DATABASE_URL") or "").strip()
    if env:
        return env
    boot = _bootstrap_database_url_file(project_root)
    if boot:
        return boot
    return default_uri


def get_setting(key: str, default: str = "", app: Optional["Flask"] = None) -> str:
    """读取配置：数据库优先，其次环境变量。"""
    from . import db
    from .models import AppConfig

    flask_app = app
    if flask_app is None:
        try:
            from flask import current_app
            flask_app = current_app._get_current_object()
        except RuntimeError:
            flask_app = None

    if flask_app is not None:
        try:
            with flask_app.app_context():
                row = AppConfig.query.filter_by(config_key=key).first()
                if row and row.config_value is not None:
                    v = str(row.config_value).replace("\ufeff", "").strip()
                    if v:
                        return v
        except Exception:
            pass

    env_v = os.environ.get(key)
    if env_v is not None and str(env_v).strip():
        return str(env_v).strip()
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
    返回已写入的键名列表（用于提示）。
    """
    from . import db

    written = []
    for key, raw in updates.items():
        if key not in {k for k, _, _ in SYSTEM_CONFIG_KEYS}:
            continue
        val = (raw or "").strip()
        if key == "DATABASE_URL" and not val:
            continue
        if key in SENSITIVE_KEYS and skip_unchanged_sensitive and (
            val == "***" or val == "(不变)" or val == "******"
        ):
            continue
        _upsert_config(key, val)
        written.append(key)

    db.session.commit()

    if "DATABASE_URL" in updates:
        uri = (updates.get("DATABASE_URL") or "").strip()
        if uri and uri not in ("***", "(不变)", "******"):
            inst = project_root / "instance"
            inst.mkdir(parents=True, exist_ok=True)
            (inst / "database_url.txt").write_text(uri + "\n", encoding="utf-8")

    return written


MIGRATION_FLAG_KEY = "ENV_TO_DB_MIGRATED"


def seed_system_settings_from_environment(project_root: Path, startup_database_uri: str = "") -> None:
    """已迁移后：库中某项仍为空时，用环境变量 / config.json / 当前库连接补全。"""
    from . import db
    from .models import AppConfig

    for key, _, _ in SYSTEM_CONFIG_KEYS:
        row = AppConfig.query.filter_by(config_key=key).first()
        existing = (row.config_value or "").strip() if row else ""
        if existing:
            continue
        if key == "DATABASE_URL":
            env_v = (os.environ.get("DATABASE_URL") or "").strip()
            val = env_v or (startup_database_uri or "").strip()
        else:
            val = (os.environ.get(key) or "").strip()
        if not val:
            continue
        _upsert_config(key, val)

    _cfg = project_root / "config.json"
    if _cfg.exists():
        try:
            import json
            with open(_cfg, "r", encoding="utf-8") as f:
                jdata = json.load(f)
            for jk in ("PAGE13_ACCESS_PASSWORD", "INTEGRATION_SECRET", "DINGTALK_WEBHOOK", "DINGTALK_SECRET", "BASE_URL"):
                row = AppConfig.query.filter_by(config_key=jk).first()
                if row and (row.config_value or "").strip():
                    continue
                jv = jdata.get(jk)
                if jv is not None and str(jv).strip():
                    _upsert_config(jk, str(jv).strip())
        except Exception:
            pass
    db.session.commit()


def ensure_environment_variables_migrated_to_db(project_root: Path, startup_database_uri: str = "") -> None:
    """
    首次启动：将当前进程环境变量（含 .env 加载后）中已有的配置写入 app_configs，实现自动迁移。
    仅当库中 ENV_TO_DB_MIGRATED 未为 1 时执行整包写入；之后仅对空项补全。
    """
    from . import db
    from .models import AppConfig

    flag_row = AppConfig.query.filter_by(config_key=MIGRATION_FLAG_KEY).first()
    already_done = flag_row and (flag_row.config_value or "").strip() == "1"

    if already_done:
        seed_system_settings_from_environment(project_root, startup_database_uri)
        return

    for key, _, _ in SYSTEM_CONFIG_KEYS:
        if key == "DATABASE_URL":
            val = (os.environ.get("DATABASE_URL") or "").strip()
            if not val:
                val = (startup_database_uri or "").strip()
        else:
            val = (os.environ.get(key) or "").strip()
        if val:
            _upsert_config(key, val)

    _cfg = project_root / "config.json"
    if _cfg.exists():
        try:
            import json
            with open(_cfg, "r", encoding="utf-8") as f:
                jdata = json.load(f)
            for jk in (
                "PAGE13_ACCESS_PASSWORD",
                "INTEGRATION_SECRET",
                "DINGTALK_WEBHOOK",
                "DINGTALK_SECRET",
                "BASE_URL",
                "SECRET_KEY",
                "DINGTALK_APP_KEY",
                "DINGTALK_APP_SECRET",
                "DINGTALK_AGENT_ID",
            ):
                row = AppConfig.query.filter_by(config_key=jk).first()
                if row and (row.config_value or "").strip():
                    continue
                jv = jdata.get(jk)
                if jv is not None and str(jv).strip():
                    _upsert_config(jk, str(jv).strip())
        except Exception:
            pass

    _upsert_config(MIGRATION_FLAG_KEY, "1")
    db.session.commit()

    env_db = (os.environ.get("DATABASE_URL") or "").strip()
    if env_db:
        inst = project_root / "instance"
        inst.mkdir(parents=True, exist_ok=True)
        (inst / "database_url.txt").write_text(env_db + "\n", encoding="utf-8")


def apply_system_settings_to_flask(app: "Flask", project_root: Path) -> None:
    """将数据库中的配置同步到 app.config（启动时及保存后调用）。"""
    for key, _, _ in SYSTEM_CONFIG_KEYS:
        if key == "DATABASE_URL":
            continue
        v = get_setting(key, default="", app=app)
        if key in ("UPLOAD_FOLDER", "OUTPUT_FOLDER"):
            if v:
                app.config[key] = v
                Path(v).mkdir(parents=True, exist_ok=True)
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


def system_settings_for_api_get(app: "Flask") -> dict[str, Any]:
    """供 GET API：敏感字段非空时返回占位符。"""
    out = {}
    for key, label, sensitive in SYSTEM_CONFIG_KEYS:
        v = get_setting(key, default="", app=app)
        if key == "DATABASE_URL":
            # 不在表单中展示当前连接串，避免误保存脱敏后的值；留空表示不修改
            out[key] = ""
            continue
        if sensitive and v:
            out[key] = "******"
        else:
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
