# -*- coding: utf-8 -*-
"""考试训练中心：公司 / 项目组作用域（各角色统一解析）。

隔离原则（全站一致）：
- **知识库 / collection / 下发考试任务（ExamCenterAssignment）**：按 **所属公司**（organization_id）隔离；
  历史与空值默认回填 **南京鱼跃软件技术有限公司**（organizations.is_default）。
- **人员相关记录**（ExamCenterActivity、学员统计、练习/考试作答等）：按 **人员所属项目组**
  （UserTeamMembership）隔离，并叠加当前公司的 organization_id 过滤。
- **项目组 ↔ 公司**：多对多（project_team_organizations）；学员/项目管理员可见公司来自项目组关联。
"""
from __future__ import annotations

from flask import has_request_context, session

from .models import ProjectTeam, UserTeamMembership


def exam_org_scoping_enabled() -> bool:
    from .tenant_context import _strict_org_scope

    return bool(_strict_org_scope())


def allowed_organization_ids() -> list[str]:
    """当前会话在考试中心可见/可选的公司 id（与 tenant_context 角色规则一致）。"""
    from .tenant_context import user_allowed_organization_ids

    return user_allowed_organization_ids()


def resolve_active_organization_id(*, write_session: bool = True) -> str:
    """解析考试中心当前公司 id；必要时回写 session.active_organization_id。"""
    if not exam_org_scoping_enabled():
        return ""
    from .authz import is_page13_super_admin, is_project_admin, is_normal_user
    from .tenant_context import default_organization

    allowed = allowed_organization_ids()
    if allowed:
        active = str(session.get("active_organization_id") or "").strip() if has_request_context() else ""
        if active not in allowed:
            active = allowed[0]
            if write_session and has_request_context():
                session["active_organization_id"] = active
        elif write_session and has_request_context() and active:
            session["active_organization_id"] = active
        return active
    if is_page13_super_admin():
        d = default_organization()
        oid = str(getattr(d, "id", "") or "").strip()
        if oid and write_session and has_request_context():
            session["active_organization_id"] = oid
        return oid


def project_admin_team_ids_for_org(org_id: str) -> set[str]:
    """项目管理员：当前公司下可见的所属项目组 id。"""
    from .authz import is_page13_super_admin, is_project_admin, user_team_ids
    from .team_organizations import organization_ids_for_team

    if is_page13_super_admin() or not is_project_admin():
        return set()
    oid = str(org_id or "").strip()
    out: set[str] = set()
    for tid in user_team_ids():
        s = str(tid or "").strip()
        if not s:
            continue
        if oid:
            linked = organization_ids_for_team(s)
            if linked and oid not in linked:
                continue
        t = ProjectTeam.query.get(s)
        if not t or not bool(getattr(t, "is_active", True)):
            continue
        out.add(s)
    if not out and not oid:
        out = {str(x).strip() for x in user_team_ids() if str(x).strip()}
    return out


def resolve_project_admin_filter_team_ids(org_id: str | None = None) -> set[str]:
    """项目管理员数据过滤用项目组（仅当前选中的一个组，禁止多组并集）。"""
    from .authz import is_page13_super_admin, is_project_admin

    if is_page13_super_admin() or not is_project_admin():
        return set()
    oid = str(org_id or "").strip()
    if not oid:
        oid = resolve_active_organization_id(write_session=False)
    scoped = project_admin_team_ids_for_org(oid)
    if not scoped:
        return set()
    active = str(session.get("active_exam_team_id") or "").strip() if has_request_context() else ""
    if active and active in scoped:
        return {active}
    if len(scoped) == 1:
        return scoped
    return set()


def default_exam_team_id_for_org(org_id: str) -> str:
    """默认项目组：互联网产品部（优先匹配当前公司绑定）。"""
    from .team_data_migration import DEFAULT_TEAM_NAME
    from .team_organizations import teams_for_organization

    oid = str(org_id or "").strip()
    scoped = teams_for_organization(oid, active_only=True) if oid else []
    for team in scoped:
        if str(team.name or "").strip() == DEFAULT_TEAM_NAME:
            return str(team.id or "").strip()
    row = ProjectTeam.query.filter_by(name=DEFAULT_TEAM_NAME, is_active=True).first()
    return str(row.id or "").strip() if row else ""


def resolve_active_exam_filter_team_id(*, org_id: str | None = None) -> str | None:
    """人员记录的项目组过滤 id。

    - ``None``：超管选了「全部项目组」，不按组过滤（仍受公司约束）；
    - 非空字符串：仅该组成员；
    - ``""``：无有效选中组，结果应为空。
    """
    if not has_request_context():
        return None
    from .authz import is_page13_super_admin, is_project_admin

    if is_page13_super_admin():
        if session.get("exam_team_scope_all"):
            return None
        tid = str(session.get("active_exam_team_id") or "").strip()
        if tid:
            return tid
        oid = str(org_id or "").strip() or resolve_active_organization_id(write_session=False)
        return default_exam_team_id_for_org(oid)
    if is_project_admin():
        oid = str(org_id or "").strip() or resolve_active_organization_id(write_session=False)
        teams = resolve_project_admin_filter_team_ids(oid)
        if not teams:
            return ""
        if len(teams) == 1:
            return next(iter(teams))
        active = str(session.get("active_exam_team_id") or "").strip()
        return active if active in teams else ""
    return None


def user_ids_for_team_ids(team_ids: set[str]) -> frozenset[str]:
    if not team_ids:
        return frozenset()
    return frozenset(
        str(m.user_id).strip()
        for m in UserTeamMembership.query.filter(
            UserTeamMembership.team_id.in_(list(team_ids))
        ).all()
        if str(m.user_id).strip()
    )


def exam_teacher_assignable_users(*, org_id: str | None = None) -> list:
    """老师端下发考试可选人员：优先按当前项目组；超管「全部组」时再按公司下项目组 ∪ 直绑公司账号。"""
    from .models import ADMIN_ROLE_COMPANY, User, UserOrganizationMembership

    users = User.query.order_by(User.display_name.asc(), User.username.asc()).all()
    scoped = None
    try:
        from .authz import exam_team_scoped_user_ids

        scoped = exam_team_scoped_user_ids()
    except Exception:
        scoped = None
    if scoped is not None:
        return [u for u in users if str(u.id or "").strip() in scoped]

    oid = str(org_id or "").strip()
    if not oid:
        return list(users)

    team_ids = {
        str(t.id).strip()
        for t in teams_for_organization(oid, active_only=True)
        if str(getattr(t, "id", "") or "").strip()
    }
    allowed = set(user_ids_for_team_ids(team_ids))
    allowed |= {
        str(m.user_id).strip()
        for m in UserOrganizationMembership.query.filter_by(organization_id=oid).all()
        if str(m.user_id).strip()
        and (u := User.query.get(str(m.user_id).strip()))
        and (getattr(u, "admin_role", None) or "").strip() == ADMIN_ROLE_COMPANY
    }
    if not allowed:
        return []
    return [u for u in users if str(u.id or "").strip() in allowed]


def activity_user_belongs_to_teams(user_key: str, team_ids: set[str]) -> bool:
    """活动 user_id（可能是 id / username / 中文名）是否属于指定项目组。"""
    from .exam_display_labels import exam_activity_user_id_match_keys, resolve_user_record

    key = str(user_key or "").strip()
    if not key or not team_ids:
        return False
    allowed = user_ids_for_team_ids(set(team_ids))
    if not allowed:
        return False
    keys = exam_activity_user_id_match_keys(key)
    if keys & allowed:
        return True
    u = resolve_user_record(key)
    cid = str(getattr(u, "id", "") or "").strip()
    return bool(cid and cid in allowed)


def organization_id_for_exam_write(explicit: str | None = None) -> str:
    """写入考试任务/活动时使用的 company id（空则当前 scope → 默认南京鱼跃）。"""
    oid = str(explicit or "").strip()
    if oid:
        return oid
    if exam_org_scoping_enabled():
        resolved = resolve_active_organization_id()
        if resolved:
            return resolved
    from .tenant_context import default_organization

    d = default_organization()
    return str(getattr(d, "id", "") or "").strip()
