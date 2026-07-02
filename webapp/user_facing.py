# -*- coding: utf-8 -*-
"""面向用户的提示文案（与 tenant_context / 集成模块解耦，避免循环 import）。"""

from __future__ import annotations

from typing import Any


def user_sees_debug_messaging() -> bool:
    """是否展示调试/集成类提示（等同页面4 超管访问密码）。"""
    from .authz import is_page13_super_admin

    return is_page13_super_admin()


def api_debug_fields(**fields: Any) -> dict[str, Any]:
    """API 响应中的 detail/upstream/diagnostics 等调试字段，仅超管下发。"""
    if not user_sees_debug_messaging():
        return {}
    return {k: v for k, v in fields.items() if v is not None}


def integration_error_message(msg: str | None) -> str:
    """内部集成错误串 → 按角色脱敏（超管保留原文）。"""
    m = (msg or "").strip() or "操作失败"
    if user_sees_debug_messaging():
        return m
    return user_facing_upstream_error(m)


def user_facing_text(admin_text: str, user_text: str) -> str:
    """超级管理员看 admin 文案，其余角色看 user 文案。"""
    from .authz import is_page13_super_admin

    return admin_text if is_page13_super_admin() else user_text


def user_facing_upstream_error(admin_text: str, user_text: str | None = None) -> str:
    """集成 API 错误提示：普通用户隐藏上游/aicheckword/页面编号等内部用语。"""
    from .authz import is_page13_super_admin

    if is_page13_super_admin():
        return admin_text
    if user_text:
        return user_text
    t = admin_text
    for old, new in (
        ("上游请求失败", "服务请求失败"),
        ("上游 HTTP", "服务请求失败（HTTP"),
        ("上游返回", "服务返回"),
        ("上游响应", "服务响应"),
        ("上游未", "服务未"),
        ("上游不可达", "服务不可达"),
        ("上游", "服务"),
        ("aicheckword", "系统"),
        ("AICHECKWORD_DRAFT_API_BASE", "文档服务地址"),
        ("QUIZ_API_BASE_URL", "考试/文档服务地址"),
        ("页面4 · 系统与钉钉「系统配置」", "系统管理"),
        ("页面4", "系统管理"),
        ("页面1", "任务列表"),
        ("页面2", "我的任务"),
        ("页面0", "公司总览"),
    ):
        t = t.replace(old, new)
    return t.strip()
