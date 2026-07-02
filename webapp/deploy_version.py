# -*- coding: utf-8 -*-
"""部署镜像版本号：与 Docker 镜像 tag / .env IMAGE_VERSION 一致。"""
from __future__ import annotations

import os
from typing import Any


def _parse_docker_image_tag(image_ref: str | None) -> str:
    s = (image_ref or "").strip()
    if not s or s.endswith(":"):
        return ""
    if "@" in s:
        return ""
    if ":" not in s:
        return ""
    return s.rsplit(":", 1)[-1].strip()


def resolve_aiword_version() -> str:
    for key in ("AIWORD_APP_VERSION", "IMAGE_VERSION"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    tag = _parse_docker_image_tag(os.environ.get("AIWORD_IMAGE"))
    return tag or "unknown"


def resolve_aicheckword_version() -> str:
    for key in ("AICHECKWORD_APP_VERSION",):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    tag = _parse_docker_image_tag(os.environ.get("AICHECKWORD_IMAGE"))
    if tag:
        return tag
    v = (os.environ.get("IMAGE_VERSION") or "").strip()
    return v or "unknown"


def deploy_version_payload() -> dict[str, Any]:
    return {
        "aiword": resolve_aiword_version(),
        "aicheckword": resolve_aicheckword_version(),
    }


def current_feedback_versions() -> tuple[str, str]:
    p = deploy_version_payload()
    return str(p.get("aiword") or "unknown"), str(p.get("aicheckword") or "unknown")
