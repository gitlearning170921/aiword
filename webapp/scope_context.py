# -*- coding: utf-8 -*-
"""全站作用域上下文与诊断（公司/项目组/角色/页面过滤说明）。"""
from __future__ import annotations

from typing import Any, Optional

from flask import has_request_context, request, session

from .app_settings import is_multi_tenant_enabled
from .authz import (
    ADMIN_ROLE_COMPANY,
    ADMIN_ROLE_NONE,
    ADMIN_ROLE_PROJECT,
    company_registry_enabled,
    current_admin_role,
    is_company_admin,
    is_company_registry_user,
    is_normal_user,
    is_page13_super_admin,
    is_project_admin,
    rbac_enforced,
    user_country_scopes,
    user_team_ids,
)
from .models import Organization, ProjectTeam, User, UserOrganizationMembership, UserTeamMembership
from .tenant_context import (
    active_organization_id_from_session,
    collection_for_organization,
    integration_org_context_payload,
    integration_organizations_payload,
    user_allowed_organization_ids,
)


_ROLE_LABELS = {
    ADMIN_ROLE_NONE: "普通账号",
    ADMIN_ROLE_PROJECT: "项目管理员",
    ADMIN_ROLE_COMPANY: "公司管理员",
}

_PAGE_LABELS = {
    "page0": "页面0 · 公司总览",
    "page1": "页面1 · 上传",
    "page2": "页面2 · 生成",
    "page3": "页面3 · 统计",
    "page4": "页面4 · 系统管理",
    "exam": "考试训练中心",
    "integration": "文档工具",
}


def infer_page_key(path: str | None = None) -> str:
    p = str(path or "").strip()
    if has_request_context() and not p:
        p = str(request.path or "")
    if "/company" in p:
        return "page0"
    if "/upload" in p:
        return "page1"
    if "/generate" in p:
        return "page2"
    if "/dashboard" in p:
        return "page3"
    if "/admin" in p:
        return "page4"
    if "/exam" in p:
        return "exam"
    if any(x in p for x in ("/audit", "/draft", "/translate")):
        return "integration"
    return "unknown"


def _org_name_map(org_ids: list[str]) -> dict[str, str]:
    ids = [str(x).strip() for x in org_ids if str(x).strip()]
    if not ids:
        return {}
    rows = Organization.query.filter(Organization.id.in_(ids)).all()
    return {
        str(o.id or "").strip(): str(o.name or o.id or "").strip() or str(o.id or "").strip()
        for o in rows
    }


def _team_name_map(team_ids: list[str]) -> dict[str, str]:
    ids = [str(x).strip() for x in team_ids if str(x).strip()]
    if not ids:
        return {}
    rows = ProjectTeam.query.filter(ProjectTeam.id.in_(ids)).all()
    return {
        str(t.id or "").strip(): str(t.name or t.id or "").strip() or str(t.id or "").strip()
        for t in rows
    }


def _teams_payload_for_ids(team_ids: list[str]) -> list[dict[str, str]]:
    names = _team_name_map(team_ids)
    out: list[dict[str, str]] = []
    for tid in team_ids:
        s = str(tid or "").strip()
        if not s:
            continue
        out.append({"id": s, "name": names.get(s, s)})
    return out


def _page_filter_description(page_key: str) -> str:
    if is_page13_super_admin():
        if page_key == "page0":
            return "超级管理员：可见全部注册国家/公司项目（可按所属公司筛选）"
        if page_key == "page1":
            return "超级管理员：可见全部页面1 项目（可按所属公司筛选）"
        if page_key == "exam":
            return "超级管理员：可按公司与项目组切换过滤考试/训练数据"
        return "超级管理员：不受项目组限制"
    if is_company_admin():
        scopes = user_country_scopes()
        if scopes:
            return f"公司管理员：仅可见注册国家为「{'、'.join(scopes)}」的总览项目"
        return "公司管理员：可见全部注册国家的公司总览项目"
    if is_project_admin():
        tids = user_team_ids()
        if page_key == "page0":
            return "项目管理员：页面0 不可访问（请使用页面1/考试中心）"
        if page_key == "page2":
            return "项目管理员：页面2 只读观察（可按项目组筛选历史）"
        if page_key == "exam":
            return "项目管理员：考试中心老师/统计端；项目组内数据可切换查看"
        if not tids:
            return "项目管理员：未分配项目组，列表将为空"
        names = [x["name"] for x in _teams_payload_for_ids(tids)]
        return f"项目管理员：数据限定在所属项目组（{'、'.join(names) or '未命名'}）"
    if is_normal_user():
        if page_key == "page2":
            return "普通账号：页面2 仅本人任务与生成记录"
        if page_key == "exam":
            return "普通账号：考试学生端仅本人练习/考试记录"
        tids = user_team_ids()
        if not tids:
            return "普通账号：未分配项目组，部分列表可能为空"
        return "普通账号：页面1/集成工具按所属项目组关联项目过滤"
    return "按当前角色与绑定公司/项目组过滤"


def _empty_reason_hints(page_key: str, *, org_count: int, team_count: int) -> list[str]:
    hints: list[str] = []
    if is_page13_super_admin():
        if page_key in ("page0", "page1") and org_count > 1:
            hints.append("若列表为空，可尝试切换「所属公司」或选择「全部公司（并集）」")
        return hints
    if not org_count and not is_company_admin():
        hints.append("账号未绑定任何公司，请联系管理员在页面4「账号管理」配置所属公司")
    if rbac_enforced() and is_project_admin() and not team_count:
        hints.append("账号未分配项目组，请联系管理员在页面4「账号管理」配置所属项目组")
    if rbac_enforced() and is_normal_user() and not team_count:
        hints.append("账号未分配项目组，页面1 项目与任务可能无法显示")
    if page_key == "page0" and is_company_admin():
        scopes = user_country_scopes()
        if scopes:
            hints.append(f"当前仅显示注册国家：{'、'.join(scopes)}；其它国家项目不会出现")
    if page_key == "page1" and org_count > 1:
        hints.append("绑定多家公司时，可在项目列表区切换「所属公司」筛选")
    if page_key == "exam":
        if is_normal_user() and not team_count:
            hints.append("学生端需先分配项目组并关联公司，否则无法加载考试任务")
        elif is_project_admin() and team_count > 1:
            hints.append("可在考试中心顶部切换项目组查看不同组的数据")
    if page_key == "page2" and is_normal_user():
        hints.append("若为空，请确认已在页面1 创建/分配任务，且编写人与当前账号一致")
    return hints


def scope_context_payload(*, page_key: str | None = None) -> dict[str, Any]:
    page = str(page_key or infer_page_key() or "unknown").strip() or "unknown"
    role = current_admin_role()
    role_label = "超级管理员" if is_page13_super_admin() else _ROLE_LABELS.get(role, role or "未知")

    org_payload = integration_org_context_payload()
    orgs = org_payload.get("organizations") or integration_organizations_payload()
    allowed_org_ids = user_allowed_organization_ids()
    org_names = _org_name_map(allowed_org_ids)

    active_org_id = str(org_payload.get("activeOrganizationId") or active_organization_id_from_session() or "").strip()
    active_org_name = org_names.get(active_org_id, "")
    if not active_org_name and active_org_id:
        active_org_name = active_org_id
    for o in orgs:
        if str(o.get("id") or "").strip() == active_org_id:
            active_org_name = str(o.get("name") or active_org_name).strip() or active_org_name
            break

    team_ids = user_team_ids()
    teams = _teams_payload_for_ids(team_ids)
    active_team_id = str(session.get("active_exam_team_id") or "").strip()
    if active_team_id and active_team_id not in {t["id"] for t in teams}:
        if is_page13_super_admin() or (is_project_admin() and active_team_id in set(team_ids)):
            extra = _teams_payload_for_ids([active_team_id])
            if extra:
                teams = extra + [t for t in teams if t["id"] != active_team_id]
        else:
            active_team_id = ""
    if not active_team_id and teams and page == "exam":
        if is_project_admin() and not is_page13_super_admin():
            active_team_id = teams[0]["id"]
    active_team_name = _team_name_map([active_team_id]).get(active_team_id, "") if active_team_id else ""

    coll = str(org_payload.get("activeKnowledgeCollection") or collection_for_organization(active_org_id) or "regulations")

    warnings: list[str] = []
    msg = str(org_payload.get("message") or "").strip()
    if msg:
        warnings.append(msg)

    scope_summary_parts: list[str] = [f"角色：{role_label}"]
    if allowed_org_ids:
        if len(allowed_org_ids) == 1:
            scope_summary_parts.append(f"公司：{org_names.get(allowed_org_ids[0], allowed_org_ids[0])}")
        else:
            scope_summary_parts.append(f"可见 {len(allowed_org_ids)} 家公司")
    elif not is_page13_super_admin() and not is_company_admin():
        scope_summary_parts.append("未绑定公司")
    if teams:
        if active_team_name:
            scope_summary_parts.append(f"项目组：{active_team_name}")
        elif len(teams) == 1:
            scope_summary_parts.append(f"项目组：{teams[0]['name']}")
        else:
            scope_summary_parts.append(f"{len(teams)} 个项目组")
    elif rbac_enforced() and role in (ADMIN_ROLE_PROJECT, ADMIN_ROLE_NONE):
        scope_summary_parts.append("未分配项目组")

    if active_org_id and len(allowed_org_ids) > 1:
        scope_summary_parts.append(f"当前公司：{active_org_name or active_org_id}")

    page_mode = "standard"
    if page in ("page0", "page1") and len(allowed_org_ids) > 1:
        page_mode = "union"
    elif page == "page2" and is_project_admin() and not is_page13_super_admin():
        page_mode = "readonly_observer"
    elif page == "exam" and is_normal_user():
        page_mode = "student_self"

    return {
        "ok": True,
        "pageKey": page,
        "pageLabel": _PAGE_LABELS.get(page, page),
        "role": role,
        "roleLabel": role_label,
        "page13SuperAdmin": is_page13_super_admin(),
        "multiTenantEnabled": bool(is_multi_tenant_enabled()),
        "companyRegistryEnabled": bool(company_registry_enabled()),
        "rbacEnforced": bool(rbac_enforced()),
        "organizations": orgs,
        "allowedOrganizationIds": allowed_org_ids,
        "activeOrganizationId": active_org_id or None,
        "activeOrganizationName": active_org_name or None,
        "activeKnowledgeCollection": coll,
        "teams": teams,
        "activeTeamId": active_team_id or None,
        "activeTeamName": active_team_name or None,
        "scopeAllTeams": bool(session.get("exam_team_scope_all")),
        "scopeSummary": " · ".join(scope_summary_parts),
        "scopeHint": _page_filter_description(page),
        "pageMode": page_mode,
        "emptyReasons": _empty_reason_hints(page, org_count=len(allowed_org_ids), team_count=len(team_ids)),
        "warnings": warnings,
        "canSwitchOrganization": len(orgs) > 1 or is_page13_super_admin(),
        "canSwitchTeam": bool(is_page13_super_admin() or (is_project_admin() and len(teams) > 1)),
        "diagnosticsAvailable": bool(is_page13_super_admin()),
        "countryScopes": user_country_scopes() if is_company_registry_user() else None,
    }


def scope_diagnostics_payload() -> dict[str, Any]:
    if not is_page13_super_admin():
        return {"ok": False, "message": "仅超级管理员可查看作用域诊断"}

    uid = str(session.get("user_id") or "").strip()
    user_row: User | None = User.query.get(uid) if uid else None
    bound_org_ids = [
        str(m.organization_id).strip()
        for m in UserOrganizationMembership.query.filter_by(user_id=uid).all()
        if str(m.organization_id).strip()
    ] if uid else []
    bound_team_ids = [
        str(m.team_id).strip()
        for m in UserTeamMembership.query.filter_by(user_id=uid).all()
        if str(m.team_id).strip()
    ] if uid else []

    org_names = _org_name_map(bound_org_ids + user_allowed_organization_ids())
    team_names = _team_name_map(bound_team_ids + user_team_ids())

    ctx = scope_context_payload()

    api_filters: dict[str, str] = {
        "page0_projects": "GET /api/company/projects ?organizationId=（可选单公司；默认可见公司并集）",
        "page1_projects": "GET /api/projects → project_in_scope（项目组/超管）",
        "page1_uploads": "GET /api/uploads → upload_in_scope",
        "exam_activities": "exam scope：active_organization_id + active_exam_team_id",
        "integration": "resolve_organization_context → session active_organization_id",
    }

    return {
        "ok": True,
        "user": {
            "id": uid or None,
            "username": str(getattr(user_row, "username", "") or "").strip() or None,
            "displayName": str(getattr(user_row, "display_name", "") or "").strip() or None,
            "adminRole": current_admin_role(),
            "adminRoleLabel": ctx.get("roleLabel"),
        },
        "session": {
            "page13Authenticated": bool(session.get("page13_authenticated")),
            "activeOrganizationId": str(session.get("active_organization_id") or "").strip() or None,
            "activeExamTeamId": str(session.get("active_exam_team_id") or "").strip() or None,
            "examTeamScopeAll": bool(session.get("exam_team_scope_all")),
            "organizationIds": list(session.get("organization_ids") or []),
            "teamIds": list(session.get("team_ids") or []),
        },
        "bindings": {
            "organizationIds": bound_org_ids,
            "organizationNames": [org_names.get(i, i) for i in bound_org_ids],
            "teamIds": bound_team_ids,
            "teamNames": [team_names.get(i, i) for i in bound_team_ids],
        },
        "effective": {
            "allowedOrganizationIds": ctx.get("allowedOrganizationIds") or [],
            "activeOrganizationId": ctx.get("activeOrganizationId"),
            "activeKnowledgeCollection": ctx.get("activeKnowledgeCollection"),
            "teams": ctx.get("teams") or [],
            "activeTeamId": ctx.get("activeTeamId"),
            "scopeSummary": ctx.get("scopeSummary"),
            "scopeHint": ctx.get("scopeHint"),
        },
        "apiFilters": api_filters,
        "emptyReasons": ctx.get("emptyReasons") or [],
        "warnings": ctx.get("warnings") or [],
    }
