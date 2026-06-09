# -*- coding: utf-8 -*-
"""页面1 账号：页面0 访问与注册国家项目管理维度。"""
from __future__ import annotations

import re
from typing import Any, Optional

from . import db
from .models import (
    User,
    UserCountryScope,
    UserOrganizationMembership,
    UserTeamMembership,
    ProjectTeam,
    Organization,
)
from .registered_countries import (
    normalize_registered_country,
    resolve_registered_country_selection,
)


def parse_registered_countries_field(data: dict) -> Optional[list[str]]:
    if "registeredCountries" not in data:
        return None
    raw = data.get("registeredCountries")
    parts: list[Any] = []
    if isinstance(raw, list):
        parts = raw
    elif isinstance(raw, str):
        parts = re.split(r"[,，;；\n]+", raw)
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        c = normalize_registered_country(p)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def user_country_scope_list(user_id: str) -> list[str]:
    rows = (
        UserCountryScope.query.filter_by(user_id=user_id)
        .order_by(UserCountryScope.registered_country.asc())
        .all()
    )
    return [str(r.registered_country).strip() for r in rows if str(r.registered_country).strip()]


def set_user_country_scopes(user_id: str, countries: list[str]) -> None:
    UserCountryScope.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    for c in countries:
        norm = resolve_registered_country_selection(c)
        if not norm:
            continue
        db.session.add(
            UserCountryScope(user_id=user_id, registered_country=norm)
        )


def set_user_team_memberships(user_id: str, team_ids: list[str]) -> list[str]:
    new_ids = {str(x).strip() for x in team_ids if str(x).strip()}
    UserTeamMembership.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    applied: list[str] = []
    for tid in sorted(new_ids):
        if not ProjectTeam.query.get(tid):
            continue
        db.session.add(UserTeamMembership(user_id=user_id, team_id=tid))
        applied.append(tid)
    return applied


def set_user_organization_memberships(user_id: str, organization_ids: list[str]) -> list[str]:
    new_ids = {str(x).strip() for x in organization_ids if str(x).strip()}
    UserOrganizationMembership.query.filter_by(user_id=user_id).delete(
        synchronize_session=False
    )
    applied: list[str] = []
    for oid in sorted(new_ids):
        if not Organization.query.get(oid):
            continue
        db.session.add(UserOrganizationMembership(user_id=user_id, organization_id=oid))
        applied.append(oid)
    return applied


def _valid_team_ids(raw_team_ids: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in raw_team_ids:
        tid = str(x).strip()
        if not tid or tid in seen:
            continue
        if not ProjectTeam.query.get(tid):
            continue
        seen.add(tid)
        out.append(tid)
    return out


def ensure_role_team_requirement(user: User, data: dict) -> None:
    """开启公司总览权限体系时，仅项目管理员保存账号时必须有所属项目组。"""
    from .authz import company_registry_enabled
    from .models import ADMIN_ROLE_COMPANY, ADMIN_ROLE_PROJECT

    if not company_registry_enabled():
        return
    role = (getattr(user, "admin_role", None) or "").strip()
    if role != ADMIN_ROLE_PROJECT:
        return
    if "teamIds" in data:
        raw = data.get("teamIds")
        team_ids = raw if isinstance(raw, list) else []
        if not _valid_team_ids(team_ids):
            raise ValueError("项目管理员必须至少选择一个有效的所属项目组")
        return
    existing = UserTeamMembership.query.filter_by(user_id=user.id).first()
    if not existing:
        raise ValueError("项目管理员必须至少选择一个所属项目组")


def serialize_user_access(user: User) -> dict[str, Any]:
    from .user_feature_permissions import serialize_user_feature_permissions

    return {
        "canAccessCompanyRegistry": bool(
            getattr(user, "can_access_company_registry", False)
        ),
        "registeredCountries": user_country_scope_list(user.id),
        "teamIds": [
            str(m.team_id).strip()
            for m in UserTeamMembership.query.filter_by(user_id=user.id).all()
            if str(m.team_id).strip()
        ],
        "organizationIds": [
            str(m.organization_id).strip()
            for m in UserOrganizationMembership.query.filter_by(user_id=user.id).all()
            if str(m.organization_id).strip()
        ],
        **serialize_user_feature_permissions(user),
    }


def apply_user_access_fields(user: User, data: dict) -> None:
    from .models import ADMIN_ROLE_COMPANY

    if "canAccessCompanyRegistry" in data:
        user.can_access_company_registry = bool(data.get("canAccessCompanyRegistry"))
    role = (getattr(user, "admin_role", None) or "").strip()
    if role == ADMIN_ROLE_COMPANY:
        user.can_access_company_registry = True
    countries = parse_registered_countries_field(data)
    if countries is not None:
        set_user_country_scopes(user.id, countries)
    if "teamIds" in data:
        raw = data.get("teamIds")
        if isinstance(raw, list):
            set_user_team_memberships(user.id, raw)
    if "organizationIds" in data:
        raw = data.get("organizationIds")
        if isinstance(raw, list):
            set_user_organization_memberships(user.id, raw)
    from .user_feature_permissions import parse_feature_permissions_field, write_user_feature_permissions

    fp = parse_feature_permissions_field(data)
    if fp is not None:
        write_user_feature_permissions(user, fp or None)


def _serialize_task_author_user(user: User) -> dict[str, Any]:
    dn = (getattr(user, "display_name", None) or "").strip()
    un = (getattr(user, "username", None) or "").strip()
    mobile = (getattr(user, "mobile", None) or "").strip() or None
    return {
        "id": user.id,
        "username": un,
        "displayName": dn or None,
        "mobile": mobile,
    }


def _resolve_project_for_author_pick(project_id: Optional[str]) -> Optional["Project"]:
    from .models import Project

    pid = (project_id or "").strip()
    if not pid:
        return None
    proj = Project.query.get(pid)
    if proj is not None:
        return proj
    return Project.query.filter_by(name=pid).first()


def list_task_author_candidates(
    *,
    project_id: Optional[str] = None,
    team_id: Optional[str] = None,
    current_user_id: Optional[str] = None,
) -> list[User]:
    """任务录入「编写人员」候选：项目绑定项目组成员，并始终包含当前登录用户。"""
    from flask import session

    from .authz import is_page13_super_admin, user_team_ids

    uid = (current_user_id or session.get("user_id") or "").strip()
    resolved_team = (team_id or "").strip()
    if project_id:
        proj = _resolve_project_for_author_pick(project_id)
        if proj is not None:
            tid = (getattr(proj, "assigned_team_id", None) or "").strip()
            if tid:
                resolved_team = tid

    user_ids: set[str] = set()
    if uid:
        user_ids.add(uid)

    if resolved_team:
        rows = UserTeamMembership.query.filter_by(team_id=resolved_team).all()
        for m in rows:
            mid = str(getattr(m, "user_id", "") or "").strip()
            if mid:
                user_ids.add(mid)
    elif is_page13_super_admin():
        return (
            User.query.order_by(User.display_name.asc(), User.username.asc()).all()
        )
    else:
        for tid in user_team_ids():
            for m in UserTeamMembership.query.filter_by(team_id=tid).all():
                mid = str(getattr(m, "user_id", "") or "").strip()
                if mid:
                    user_ids.add(mid)

    if not user_ids:
        if uid:
            u = User.query.get(uid)
            return [u] if u is not None else []
        return []

    return (
        User.query.filter(User.id.in_(sorted(user_ids)))
        .order_by(User.display_name.asc(), User.username.asc())
        .all()
    )
