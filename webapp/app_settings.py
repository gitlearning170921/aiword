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
    (
        "SCHEDULER_INSTANCE_ID",
        "定时任务实例标识（多套部署共库时填不同值则各发一条钉钉；单套部署留空）",
        False,
    ),
]

SENSITIVE_KEYS = {k for k, _, sens in SYSTEM_CONFIG_KEYS if sens}

# config.json 中可能出现的别名（键名不一致时仍能读到）
CONFIG_JSON_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "DINGTALK_WEBHOOK": (
        "DINGTALK_WEBHOOK",
        "dingtalk_webhook",
        "dingtalkWebhook",
        "DINGTALK_ROBOT_WEBHOOK",
    ),
    "DINGTALK_SECRET": ("DINGTALK_SECRET", "dingtalk_secret", "dingtalkSecret"),
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
    if key in ("DINGTALK_WEBHOOK", "DINGTALK_SECRET"):
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
        ev = (os.environ.get("DATABASE_URL") or "").strip()
        if ev:
            return ev
        pr = _project_root_from_app(flask_app)
        if pr is None and flask_app is None:
            try:
                from flask import current_app as ca

                pr = _project_root_from_app(ca._get_current_object())
            except RuntimeError:
                pass
        if pr:
            boot = _bootstrap_database_url_file(pr)
            if boot:
                return boot
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
            _upsert_config(key, val)
            written.append(key)
            inst = project_root / "instance"
            inst.mkdir(parents=True, exist_ok=True)
            (inst / "database_url.txt").write_text(val + "\n", encoding="utf-8")
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
            env_v = (os.environ.get("DATABASE_URL") or "").strip()
            val = env_v or (startup_database_uri or "").strip()
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
            val = (os.environ.get("DATABASE_URL") or "").strip()
            if not val:
                val = (startup_database_uri or "").strip()
        else:
            val = _first_env_value(key)
        if val:
            _upsert_config(key, val)

    persist_config_json_into_empty_db_keys(project_root, flask_app)

    _upsert_config(MIGRATION_FLAG_KEY, "1")
    db.session.commit()

    env_db = (os.environ.get("DATABASE_URL") or "").strip()
    if env_db:
        inst = project_root / "instance"
        inst.mkdir(parents=True, exist_ok=True)
        (inst / "database_url.txt").write_text(env_db + "\n", encoding="utf-8")


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
    """当前实际使用的数据库 URI（库配置 > instance/database_url.txt）。"""
    v = (get_setting("DATABASE_URL", default="", app=app) or "").strip()
    if v:
        return v
    return (_bootstrap_database_url_file(project_root) or "").strip()


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
