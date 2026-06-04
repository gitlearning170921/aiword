# -*- coding: utf-8 -*-
"""分级角色 + 页面1·3 访问密码超级管理员（见 is_page13_super_admin）。"""
from __future__ import annotations

from datetime import date, datetime
from functools import wraps
from typing import Any, Callable

from flask import jsonify, redirect, request, session, url_for

from .app_settings import _parse_flag, get_setting
from .models import (
    ADMIN_ROLE_COMPANY,
    ADMIN_ROLE_NONE,
    ADMIN_ROLE_PROJECT,
    ADMIN_ROLES,
    CompanyProject,
    Project,
    UploadRecord,
    User,
    UserOrganizationMembership,
    UserTeamMembership,
)


def project_display_label(
    name: str | None,
    registered_country: str | None,
    registered_category: str | None,
) -> str:
    n = (name or "").strip()
    c = (registered_country or "").strip()
    cat = (registered_category or "").strip()
    if not c and not cat:
        return n
    return f"{n}（{c or '—'} / {cat or '—'}）"


def company_registry_enabled() -> bool:
    return _parse_flag(get_setting("FEATURE_COMPANY_REGISTRY", default=""))


def is_page13_super_admin() -> bool:
    """已通过页面1·3 访问密码验证：等同超级管理员，全页面全项目。"""
    return bool(session.get("page13_authenticated"))


def current_admin_role() -> str:
    role = (session.get("admin_role") or "").strip()
    if role in ADMIN_ROLES:
        return role
    uid = session.get("user_id")
    if uid:
        u = User.query.get(uid)
        if u:
            role = (getattr(u, "admin_role", None) or ADMIN_ROLE_NONE).strip()
            if role in ADMIN_ROLES:
                session["admin_role"] = role
                return role
    return ADMIN_ROLE_NONE


def is_company_admin() -> bool:
    return current_admin_role() == ADMIN_ROLE_COMPANY


def is_project_admin() -> bool:
    return current_admin_role() == ADMIN_ROLE_PROJECT


def is_exam_center_staff() -> bool:
    """考试训练中心老师端/统计端：超管、page13 密码，或已登录的项目管理员（无需再输访问密码）。"""
    if is_page13_super_admin():
        return True
    if session.get("page13_authenticated"):
        return True
    return bool(session.get("user_id")) and is_project_admin()


def is_normal_user() -> bool:
    return bool(session.get("user_id")) and current_admin_role() == ADMIN_ROLE_NONE


def is_company_registry_user() -> bool:
    return bool(session.get("user_id")) and is_company_admin()


def user_team_ids() -> list[str]:
    cached = session.get("team_ids")
    if isinstance(cached, list) and cached:
        return [str(x).strip() for x in cached if str(x).strip()]
    uid = session.get("user_id")
    if not uid:
        return []
    ids = [
        str(m.team_id).strip()
        for m in UserTeamMembership.query.filter_by(user_id=uid).all()
        if str(m.team_id).strip()
    ]
    session["team_ids"] = ids
    return ids


def user_country_scopes() -> list[str] | None:
    if not is_company_registry_user():
        return None
    if is_page13_super_admin():
        return None
    uid = session.get("user_id")
    if not uid:
        return None
    from .user_access import user_country_scope_list

    scopes = user_country_scope_list(uid)
    session["country_scopes"] = scopes
    if not scopes:
        return None
    return scopes


def registered_country_in_scope(registered_country: str | None) -> bool:
    scopes = user_country_scopes()
    if scopes is None:
        return True
    c = (registered_country or "").strip()
    return c in scopes


def rbac_enforced() -> bool:
    if is_page13_super_admin():
        return False
    if not company_registry_enabled():
        return False
    if not session.get("user_id"):
        return False
    if is_company_admin():
        return True
    return current_admin_role() in (ADMIN_ROLE_PROJECT, ADMIN_ROLE_NONE)


def role_home_url() -> str:
    if is_page13_super_admin():
        return url_for("admin.admin_page")
    if is_company_admin():
        return url_for("company.company_registry_page")
    if is_project_admin():
        return url_for("pages.upload_page")
    return url_for("pages.generate_page")


def _normalize_next_path(next_url: str | None) -> str:
    """将 next 参数规范为站内路径（不含 query）。"""
    s = (next_url or "").strip()
    if not s:
        return ""
    if s.startswith("http://") or s.startswith("https://"):
        from urllib.parse import urlparse

        s = urlparse(s).path or ""
    if "?" in s:
        s = s.split("?", 1)[0]
    s = s.strip()
    if s.endswith("/") and len(s) > 1:
        s = s.rstrip("/")
    return s


def path_allowed_for_current_user(path: str) -> bool:
    """登录后 next 跳转：仅允许进入与当前角色匹配的页面。"""
    p = _normalize_next_path(path)
    if not p or p in ("/login", "/"):
        return False
    if is_page13_super_admin():
        return True
    if p == "/admin" or p.startswith("/admin/"):
        return False
    role = current_admin_role()
    if role == ADMIN_ROLE_COMPANY:
        return p == "/company" or p.startswith("/company/")
    if role == ADMIN_ROLE_PROJECT:
        if company_registry_enabled() and not user_team_ids():
            return False
        return (
            p in ("/upload", "/dashboard", "/exam-center")
            or p.startswith("/upload/")
            or p.startswith("/dashboard/")
            or p.startswith("/exam-center")
        )
    return p == "/generate" or p.startswith("/generate/")


def resolve_login_redirect(next_url: str | None = None) -> str:
    """登录成功后的跳转地址：优先合法 next，否则按账号分级角色首页。"""
    path = _normalize_next_path(next_url)
    if path and path_allowed_for_current_user(path):
        return path
    return role_home_url()


def nav_show_page0() -> bool:
    if is_page13_super_admin():
        return company_registry_enabled()
    return company_registry_enabled() and is_company_registry_user()


def nav_show_page123_staff() -> bool:
    """页面1/3：超级管理员密码，或已登录的项目管理员。"""
    if is_page13_super_admin():
        return True
    return is_project_admin() and bool(user_team_ids())


def nav_show_page2() -> bool:
    """页面2：超级管理员、普通账号、项目管理员；公司管理员仅页面0。"""
    if is_page13_super_admin():
        return True
    return bool(session.get("user_id")) and not is_company_admin()


def nav_show_page4() -> bool:
    """页面4 · 系统管理：仅超级管理员（访问密码）。"""
    return is_page13_super_admin()


def _page13_password_configured() -> bool:
    from .app_settings import get_setting

    p = get_setting("PAGE13_ACCESS_PASSWORD", default="")
    return bool(p and str(p).strip())


def super_admin_required(fn: Callable):
    """仅页面1·3 访问密码超级管理员可调用（页面4 维护类 API）。"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if is_page13_super_admin():
            return fn(*args, **kwargs)
        if _is_api_request():
            return (
                jsonify(
                    {
                        "message": "仅超级管理员可访问，请先在页面4 完成访问密码验证",
                        "needsPage13Auth": True,
                    }
                ),
                403,
            )
        return redirect(url_for("admin.admin_page"))

    return wrapper


def page4_access_required(fn: Callable):
    """页面4 HTML：未验证访问密码时展示 gate。"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if is_page13_super_admin():
            return fn(*args, **kwargs)
        if not _page13_password_configured():
            return fn(*args, **kwargs)
        next_url = request.full_path if request.query_string else request.path
        if next_url.endswith("?"):
            next_url = next_url[:-1]
        return render_template(
            "page13_gate.html",
            next_url=next_url or "/admin",
            gate_page=True,
            gate_title="页面4 · 超级管理员",
            gate_description="请输入访问密码以进入系统管理台（字典、账号、配置、系统与钉钉）。",
        )

    return wrapper


def _is_api_request() -> bool:
    return bool(
        request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or (request.path or "").startswith("/api/")
    )


def _company_admin_blocked_response():
    if _is_api_request():
        return (
            jsonify(
                {
                    "message": "公司管理员仅可访问页面0 · 公司总览",
                    "needsCompanyAdmin": True,
                    "redirect": url_for("company.company_registry_page"),
                }
            ),
            403,
        )
    return redirect(url_for("company.company_registry_page"))


def company_registry_write_allowed() -> bool:
    if is_page13_super_admin():
        return True
    return is_company_registry_user()


def company_project_in_scope(cp: CompanyProject | None) -> bool:
    if cp is None:
        return False
    if is_page13_super_admin():
        return True
    if not company_registry_enabled():
        return True
    if not is_company_registry_user():
        return False
    scopes = user_country_scopes()
    if scopes is not None:
        return registered_country_in_scope(getattr(cp, "registered_country", None))
    return True


def project_in_scope(project: Project | None) -> bool:
    if project is None:
        return False
    if not rbac_enforced():
        return True
    if is_company_admin():
        scopes = user_country_scopes()
        if scopes is not None:
            return registered_country_in_scope(
                getattr(project, "registered_country", None)
            )
        return True
    if not is_project_admin():
        return False
    tid = (getattr(project, "assigned_team_id", None) or "").strip()
    return bool(tid) and tid in user_team_ids()


def resolve_project_for_upload(rec: UploadRecord) -> Project | None:
    pid = (getattr(rec, "project_id", None) or "").strip()
    if pid:
        return Project.query.get(pid)
    label = (getattr(rec, "project_name", None) or "").strip()
    if not label:
        return None
    for p in Project.query.all():
        if project_display_label(p.name, p.registered_country, p.registered_category) == label:
            return p
    return None


def upload_in_scope(rec: UploadRecord | None) -> bool:
    if rec is None:
        return False
    if not rbac_enforced():
        return True
    if is_company_admin():
        return False
    proj = resolve_project_for_upload(rec)
    if proj is None:
        return False
    return project_in_scope(proj)


def _record_assigned_to_current_user(rec: Any) -> bool:
    username = (session.get("username") or "").strip()
    display_name = (session.get("display_name") or "").strip()
    an = (getattr(rec, "assignee_name", None) or "").strip()
    au = (getattr(rec, "author", None) or "").strip()
    if username and (an == username or au == username):
        return True
    if display_name and (an == display_name or au == display_name):
        return True
    return False


def upload_record_visible_to_user(rec: Any) -> bool:
    if rec is None:
        return False
    if is_page13_super_admin():
        return True
    if is_company_admin():
        return False
    if is_normal_user():
        if not _record_assigned_to_current_user(rec):
            return False
        if rbac_enforced() and user_team_ids():
            return upload_in_scope(rec)
        return True
    if is_project_admin() and user_team_ids() and rbac_enforced():
        return upload_in_scope(rec)
    return False


def sync_user_session(user: User) -> None:
    session["user_id"] = user.id
    session["username"] = user.username
    session["display_name"] = user.display_name or user.username
    session["is_admin"] = bool(getattr(user, "is_admin", False))
    role = (getattr(user, "admin_role", None) or ADMIN_ROLE_NONE).strip()
    session["admin_role"] = role if role in ADMIN_ROLES else ADMIN_ROLE_NONE
    session["team_ids"] = [
        str(m.team_id).strip()
        for m in UserTeamMembership.query.filter_by(user_id=user.id).all()
        if str(m.team_id).strip()
    ]
    org_ids = [
        str(m.organization_id).strip()
        for m in UserOrganizationMembership.query.filter_by(user_id=user.id).all()
        if str(m.organization_id).strip()
    ]
    session["organization_ids"] = org_ids
    active_org = str(session.get("active_organization_id") or "").strip()
    if org_ids:
        if active_org not in org_ids:
            session["active_organization_id"] = org_ids[0]
    else:
        session.pop("active_organization_id", None)
    from .user_access import user_country_scope_list

    scopes = user_country_scope_list(user.id)
    session["country_scopes"] = scopes
    session.pop("country_scopes_stale", None)
    session["country_scope_active"] = bool(scopes) and role == ADMIN_ROLE_COMPANY
    session["can_access_company_registry"] = role == ADMIN_ROLE_COMPANY


def parse_optional_date(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    s = str(raw).strip()[:10]
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def company_registry_api_required(fn: Callable):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not company_registry_enabled():
            return jsonify({"message": "公司项目总览模块未启用"}), 403
        if is_page13_super_admin():
            return fn(*args, **kwargs)
        if not session.get("user_id"):
            return jsonify({"message": "请先登录", "needsLogin": True}), 401
        if not is_company_admin():
            return jsonify(
                {
                    "message": "仅公司管理员账号或页面1·3 访问密码可访问页面0",
                    "needsCompanyAdmin": True,
                }
            ), 403
        return fn(*args, **kwargs)

    return wrapper


def company_admin_write_required(fn: Callable):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not company_registry_enabled():
            return jsonify({"message": "公司项目总览模块未启用"}), 403
        if is_page13_super_admin():
            return fn(*args, **kwargs)
        if not session.get("user_id"):
            return jsonify({"message": "请先登录", "needsLogin": True}), 401
        if not company_registry_write_allowed():
            return jsonify({"message": "需要公司管理员权限"}), 403
        return fn(*args, **kwargs)

    return wrapper


def company_registry_page_required(fn: Callable):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        from flask import render_template

        if not company_registry_enabled():
            return (
                render_template(
                    "error.html",
                    title="公司总览未启用",
                    message="公司项目总览模块未启用。可在页面3 系统配置中开启 FEATURE_COMPANY_REGISTRY。",
                    hide_main_nav=True,
                    gate_page=True,
                ),
                403,
            )
        if is_page13_super_admin():
            return fn(*args, **kwargs)
        if not session.get("user_id"):
            next_url = request.full_path if request.query_string else request.path
            if next_url.endswith("?"):
                next_url = next_url[:-1]
            return redirect(url_for("pages.login_page", next=next_url or "/company"))
        if not is_company_admin():
            return (
                render_template(
                    "error.html",
                    title="无访问权限",
                    message="仅「公司管理员」账号或页面1·3 访问密码可访问页面0。",
                    back_url=url_for("pages.login_page"),
                    back_label="重新登录",
                    hide_main_nav=True,
                    gate_page=True,
                ),
                403,
            )
        return fn(*args, **kwargs)

    return wrapper
