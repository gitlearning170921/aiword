# -*- coding: utf-8 -*-
"""分级角色 + 页面4 访问密码超级管理员（见 is_page13_super_admin）。"""
from __future__ import annotations

from datetime import date, datetime
from functools import wraps
from typing import Any, Callable

from flask import g, has_request_context, jsonify, redirect, render_template, request, session, url_for

from .app_settings import _parse_flag, get_setting, is_multi_tenant_enabled
from .models import (
    ADMIN_ROLE_COMPANY,
    ADMIN_ROLE_NONE,
    ADMIN_ROLE_PROJECT,
    ADMIN_ROLES,
    CompanyProject,
    Project,
    ProjectTeam,
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
    if has_request_context():
        cached = getattr(g, "_company_registry_enabled", None)
        if cached is not None:
            return bool(cached)
    val = _parse_flag(get_setting("FEATURE_COMPANY_REGISTRY", default=""))
    if has_request_context():
        g._company_registry_enabled = val
    return val


def is_page13_super_admin() -> bool:
    """已通过页面4 访问密码验证：等同超级管理员，可免账号登录进入全站页面。"""
    return bool(session.get("page13_authenticated"))


def current_admin_role() -> str:
    if has_request_context():
        cached = getattr(g, "_current_admin_role", None)
        if cached is not None:
            return cached
    uid = session.get("user_id")
    role = ADMIN_ROLE_NONE
    if uid:
        u = User.query.get(uid)
        if u:
            role = (getattr(u, "admin_role", None) or ADMIN_ROLE_NONE).strip()
            if role not in ADMIN_ROLES:
                role = ADMIN_ROLE_NONE
    else:
        role = (session.get("admin_role") or "").strip()
        if role not in ADMIN_ROLES:
            role = ADMIN_ROLE_NONE
    if has_request_context():
        g._current_admin_role = role
        session["admin_role"] = role
    return role


def is_company_admin() -> bool:
    return current_admin_role() == ADMIN_ROLE_COMPANY


def is_project_admin() -> bool:
    return current_admin_role() == ADMIN_ROLE_PROJECT


def is_exam_center_staff() -> bool:
    """考试训练中心老师端/统计端：页面4 超管、或已登录的项目管理员（无需再输访问密码）。"""
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
    if has_request_context():
        cached = getattr(g, "_user_team_ids", None)
        if cached is not None:
            return list(cached)
    uid = session.get("user_id")
    if not uid:
        return []
    ids = [
        str(m.team_id).strip()
        for m in UserTeamMembership.query.filter_by(user_id=uid).all()
        if str(m.team_id).strip()
    ]
    session["team_ids"] = ids
    if has_request_context():
        g._user_team_ids = ids
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
    if has_request_context():
        cached = getattr(g, "_rbac_enforced", None)
        if cached is not None:
            return bool(cached)
    enforced = False
    if not is_page13_super_admin() and company_registry_enabled() and session.get("user_id"):
        if is_company_admin():
            enforced = True
        else:
            enforced = current_admin_role() in (ADMIN_ROLE_PROJECT, ADMIN_ROLE_NONE)
    if has_request_context():
        g._rbac_enforced = enforced
    return enforced


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


def page13_password_configured() -> bool:
    """是否已配置页面4 访问密码（全站统一入口）。"""
    return _page13_password_configured()


def gate_next_url() -> str:
    if not has_request_context():
        return "/"
    next_url = request.full_path if request.query_string else request.path
    if next_url.endswith("?"):
        next_url = next_url[:-1]
    return next_url or "/"


def super_admin_password_gate_response(
    *,
    gate_title: str = "页面4 · 超级管理员",
    gate_description: str = "请输入访问密码以进入该页面（超级管理员无需账号登录）。",
):
    return render_template(
        "page13_gate.html",
        next_url=gate_next_url(),
        gate_page=True,
        gate_title=gate_title,
        gate_description=gate_description,
    )


def block_until_super_admin_or_user_id(*, for_api: bool | None = None):
    """已验证访问密码或已登录 → None；否则密码门 / 登录 / API 401。"""
    if is_page13_super_admin():
        return None
    if session.get("user_id"):
        return None
    is_api = for_api if for_api is not None else _is_api_request()
    if page13_password_configured():
        if is_api:
            return (
                jsonify(
                    {
                        "message": "需要输入访问密码",
                        "needsPage13Auth": True,
                    }
                ),
                401,
            )
        return super_admin_password_gate_response()
    if is_api:
        return jsonify({"message": "请先登录", "needsLogin": True}), 401
    return redirect(url_for("pages.login_page"))


def super_admin_required(fn: Callable):
    """仅页面4 访问密码超级管理员可调用（页面4 维护类 API）。"""
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
        if not page13_password_configured():
            return fn(*args, **kwargs)
        return super_admin_password_gate_response(
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


def _project_lookup_maps() -> tuple[dict[str, Project], dict[str, Project], dict[str, Project]]:
    """单次请求内缓存项目索引，避免 upload 列表过滤时 N 次 Project.query.all()。"""
    if has_request_context():
        cached = getattr(g, "_project_lookup_maps", None)
        if cached is not None:
            return cached
    by_id: dict[str, Project] = {}
    by_label: dict[str, Project] = {}
    by_name: dict[str, Project] = {}
    for p in Project.query.all():
        pid = str(getattr(p, "id", "") or "").strip()
        if pid:
            by_id[pid] = p
        label = project_display_label(
            getattr(p, "name", None),
            getattr(p, "registered_country", None),
            getattr(p, "registered_category", None),
        )
        if label:
            by_label[label] = p
        name = (getattr(p, "name", None) or "").strip()
        if name:
            by_name[name] = p
    maps = (by_id, by_label, by_name)
    if has_request_context():
        g._project_lookup_maps = maps
    return maps


def _invalidate_project_lookup_maps() -> None:
    if has_request_context():
        g.pop("_project_lookup_maps", None)


def resolve_project_for_upload(rec: UploadRecord) -> Project | None:
    by_id, by_label, by_name = _project_lookup_maps()
    pid = (getattr(rec, "project_id", None) or "").strip()
    if pid:
        return by_id.get(pid)
    label = (getattr(rec, "project_name", None) or "").strip()
    if not label:
        return None
    return by_label.get(label) or by_name.get(label)


def project_in_scope(
    project: Project | None,
    *,
    team_ids: set[str] | None = None,
) -> bool:
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
    if not tid:
        return True
    tids = team_ids if team_ids is not None else set(user_team_ids())
    return tid in tids


def upload_in_scope(rec: UploadRecord | None) -> bool:
    if rec is None:
        return False
    if not rbac_enforced():
        return True
    if is_company_admin():
        return False
    proj = resolve_project_for_upload(rec)
    if proj is None:
        return is_project_admin()
    return project_in_scope(proj)


def _project_visible_for_team(project: Project | None, team_ids: set[str]) -> bool:
    if project is None:
        return True
    tid = (getattr(project, "assigned_team_id", None) or "").strip()
    return not tid or tid in team_ids


def project_label_in_page3_scope(project_name: str | None) -> bool:
    """页面3 统计/催办：项目管理员仅可操作所属项目组下的项目。"""
    if is_page13_super_admin() or not rbac_enforced():
        return True
    if not is_project_admin():
        return False
    label = (project_name or "").strip()
    if not label:
        return False
    by_id, by_label, by_name = _project_lookup_maps()
    proj = by_label.get(label) or by_name.get(label)
    if proj is None:
        return True
    return project_in_scope(proj)


def exam_team_scoped_user_ids() -> frozenset[str] | None:
    """考试中心老师/统计：按当前选中的项目组过滤学员；超管「全部项目组」时不按组过滤。"""
    from .exam_scope import resolve_active_exam_filter_team_id, user_ids_for_team_ids

    team_id = resolve_active_exam_filter_team_id()
    if team_id is None:
        return None
    if not team_id:
        return frozenset()
    return user_ids_for_team_ids({team_id})


def exam_row_organization_id_matches(row_org_id: str | None, scope_org_id: str) -> bool:
    """当前公司作用域是否匹配记录 organization_id（空值视为默认公司历史数据，与查询 SQL 一致）。"""
    oid = str(scope_org_id or "").strip()
    if not oid:
        return True
    row_oid = str(row_org_id or "").strip()
    if not row_oid:
        return True
    return row_oid == oid


def user_in_exam_team_scope(user_id: str | None) -> bool:
    scoped = exam_team_scoped_user_ids()
    if scoped is None:
        return True
    uid = str(user_id or "").strip()
    if not uid:
        return False
    if uid in scoped:
        return True
    from .exam_display_labels import resolve_user_record

    u = resolve_user_record(uid)
    if u and str(getattr(u, "id", "") or "").strip() in scoped:
        return True
    return False


def filter_upload_records_in_scope(records: list[UploadRecord]) -> list[UploadRecord]:
    """批量过滤 upload 列表（页面1）；避免逐条重复查库导致接口长时间 pending。"""
    if not records:
        return []
    if not rbac_enforced():
        return list(records)
    if is_company_admin():
        return []
    if not is_project_admin():
        return []
    by_id, by_label, by_name = _project_lookup_maps()
    team_ids = set(user_team_ids())
    out: list[UploadRecord] = []
    for rec in records:
        pid = (getattr(rec, "project_id", None) or "").strip()
        proj = by_id.get(pid) if pid else None
        if proj is None:
            label = (getattr(rec, "project_name", None) or "").strip()
            if label:
                proj = by_label.get(label) or by_name.get(label)
        if proj is None:
            out.append(rec)
            continue
        if _project_visible_for_team(proj, team_ids):
            out.append(rec)
    return out


def filter_upload_records_visible_to_user(records: list[UploadRecord]) -> list[UploadRecord]:
    """页面2 my-tasks 批量可见性过滤。"""
    if not records:
        return []
    if is_page13_super_admin():
        return list(records)
    if is_company_admin():
        return []
    by_id, by_label, by_name = _project_lookup_maps()
    team_ids = set(user_team_ids())
    enforced = rbac_enforced()
    is_pa = is_project_admin()
    is_nu = is_normal_user()
    out: list[UploadRecord] = []
    for rec in records:
        pid = (getattr(rec, "project_id", None) or "").strip()
        proj = by_id.get(pid) if pid else None
        if proj is None:
            label = (getattr(rec, "project_name", None) or "").strip()
            if label:
                proj = by_label.get(label) or by_name.get(label)
        if is_nu:
            if not _record_assigned_to_current_user(rec):
                continue
            if enforced and team_ids and proj is not None:
                if not _project_visible_for_team(proj, team_ids):
                    continue
            out.append(rec)
            continue
        if is_pa:
            if not enforced:
                out.append(rec)
                continue
            if not team_ids:
                continue
            if _project_visible_for_team(proj, team_ids):
                out.append(rec)
    return out


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
    if is_project_admin() and rbac_enforced():
        if not user_team_ids():
            return False
        return upload_in_scope(rec)
    return False


def _refresh_session_from_user(user: User) -> None:
    """从数据库刷新 session 中的角色/归属，不写入数据库。"""
    session["user_id"] = user.id
    session["username"] = user.username
    session["display_name"] = user.display_name or user.username
    session["is_admin"] = False
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
    if role == ADMIN_ROLE_PROJECT:
        from .team_organizations import organization_ids_for_teams

        team_ids = [
            str(m.team_id).strip()
            for m in UserTeamMembership.query.filter_by(user_id=user.id).all()
            if str(m.team_id).strip()
        ]
        for oid in organization_ids_for_teams(team_ids):
            if oid and oid not in org_ids:
                org_ids.append(oid)
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


def sync_user_session(user: User) -> None:
    _refresh_session_from_user(user)


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
                    "message": "仅公司管理员账号或页面4 访问密码（超级管理员）可访问页面0",
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
                    message="公司项目总览模块未启用。可在页面4 · 系统与钉钉「系统配置」中开启 FEATURE_COMPANY_REGISTRY。",
                    hide_main_nav=True,
                    gate_page=True,
                ),
                403,
            )
        if is_page13_super_admin():
            return fn(*args, **kwargs)
        blocked = block_until_super_admin_or_user_id()
        if blocked is not None:
            return blocked
        if not is_company_admin():
            return (
                render_template(
                    "error.html",
                    title="无访问权限",
                    message="仅「公司管理员」账号或页面4 访问密码（超级管理员）可访问页面0。",
                    back_url=url_for("pages.login_page"),
                    back_label="重新登录",
                    hide_main_nav=True,
                    gate_page=True,
                ),
                403,
            )
        return fn(*args, **kwargs)

    return wrapper
