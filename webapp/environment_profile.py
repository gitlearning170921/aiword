# -*- coding: utf-8 -*-
"""仅 aiword 在 FEATURE_ENV_SEPARATION=1 时按 AIWORD_ENV 隔离；aicheckword/aiprintword 库不分环境。"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

_ENV_KEY = "AIWORD_ENV"
_SEPARATION_KEY = "FEATURE_ENV_SEPARATION"
_TEST_ALIASES = frozenset({"test", "testing", "dev"})


def _parse_flag(raw: str) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def is_env_separation_enabled() -> bool:
    """全局开关：默认关闭，与引入环境分离前的行为一致。"""
    return _parse_flag(os.environ.get(_SEPARATION_KEY) or "0")


def get_deploy_env() -> str:
    if not is_env_separation_enabled():
        return "prod"
    raw = (os.environ.get(_ENV_KEY) or "prod").strip().lower()
    return "test" if raw in _TEST_ALIASES else "prod"


def _profile_enabled() -> bool:
    return (os.environ.get("AIWORD_USE_PROFILE_DB") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _setdefault(key: str, value: str) -> None:
    if value and not (os.environ.get(key) or "").strip():
        os.environ[key] = value


def _apply_path_defaults(is_test: bool) -> None:
    """仅隔离 aiword 本机产生的数据；aicheckword/aiprintword 始终走生产服务，URL 须在 .env 手写。"""
    if is_test:
        _setdefault("AIWORD_INSTANCE_DIR", "instance_test")
        _setdefault("AIWORD_UPLOADS_DIR", "uploads_test")
        _setdefault("AIWORD_OUTPUTS_DIR", "outputs_test")
        _setdefault("FTP_BASE_DIR", "/upload/test")
        _setdefault("BASE_URL", "http://127.0.0.1:5000")
        _setdefault("SCHEDULER_INSTANCE_ID", "aiword-test-local")
        _setdefault("DINGTALK_WEBHOOK", "")
        _setdefault("DINGTALK_SECRET", "")
    else:
        _setdefault("AIWORD_INSTANCE_DIR", "instance")
        _setdefault("AIWORD_UPLOADS_DIR", "uploads")
        _setdefault("AIWORD_OUTPUTS_DIR", "outputs")
        _setdefault("SCHEDULER_INSTANCE_ID", "aiword-prod")


def _default_db_name(is_test: bool) -> str:
    explicit = (os.environ.get("AIWORD_DB_NAME") or "").strip()
    if explicit:
        return explicit
    return "aiword_test" if is_test else "aiword"


def _build_mysql_bootstrap_uri(is_test: bool) -> str | None:
    host = (os.environ.get("MYSQL_HOST") or "").strip()
    if not host:
        return None
    port = (os.environ.get("MYSQL_PORT") or "3306").strip() or "3306"
    user = (os.environ.get("MYSQL_USER") or "").strip()
    password = os.environ.get("MYSQL_PASSWORD") or ""
    charset = (os.environ.get("MYSQL_CHARSET") or "utf8mb4").strip() or "utf8mb4"
    db_name = _default_db_name(is_test)
    user_q = quote_plus(user) if user else ""
    pass_q = quote_plus(password) if password else ""
    auth = f"{user_q}:{pass_q}@" if user or password else ""
    return (
        f"mysql+pymysql://{auth}{host}:{port}/{db_name}"
        f"?charset={charset}"
    )


def apply_environment_profile(project_root: Path | None = None) -> str:
    """
    FEATURE_ENV_SEPARATION=1 时，按 AIWORD_ENV 隔离 aiword 本机数据（库名、目录等）。
    未开启时不改写任何配置，保持改前单环境行为。
    """
    _ = project_root  # 预留
    if not is_env_separation_enabled():
        logger.info(
            "环境分离已关闭（%s=0），不应用 AIWORD_ENV 配置差异",
            _SEPARATION_KEY,
        )
        return "prod"

    env = get_deploy_env()
    is_test = env == "test"
    _apply_path_defaults(is_test)

    if _profile_enabled():
        if not (os.environ.get("AIWORD_BOOTSTRAP_DATABASE_URL") or "").strip():
            uri = _build_mysql_bootstrap_uri(is_test)
            if uri:
                os.environ["AIWORD_BOOTSTRAP_DATABASE_URL"] = uri

    label = "测试" if is_test else "生产"
    logger.info(
        "环境分离已开启，AIWORD_ENV=%s（%s）",
        env,
        label,
    )
    return env
