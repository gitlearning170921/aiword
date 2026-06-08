# -*- coding: utf-8 -*-
"""项目组字典：页面0 维护，引用检查。"""
from __future__ import annotations

from typing import Any, Optional

from . import db
from .models import CompanyProject, Project, ProjectTeam, UploadRecord, UserTeamMembership


def project_has_page1_upload_tasks(project_id: str) -> bool:
    """单个页面1 项目是否已有上传/任务记录。"""
    pid = (project_id or "").strip()
    if not pid:
        return False
    if UploadRecord.query.filter(UploadRecord.project_id == pid).limit(1).first():
        return True
    row = Project.query.get(pid)
    if not row:
        return False
    name = (row.name or "").strip()
    if name and UploadRecord.query.filter(UploadRecord.project_name == name).limit(1).first():
        return True
    return False


def company_project_has_page1_upload_tasks(company_project_id: str) -> bool:
    """关联的页面1 项目是否已有上传/任务记录（页面1 已向项目组下发任务）。"""
    cp_id = (company_project_id or "").strip()
    if not cp_id:
        return False
    linked = Project.query.filter(Project.company_project_id == cp_id).all()
    if not linked:
        return False
    pids = [p.id for p in linked if (p.id or "").strip()]
    if pids:
        if UploadRecord.query.filter(UploadRecord.project_id.in_(pids)).limit(1).first():
            return True
    names = {(p.name or "").strip() for p in linked if (p.name or "").strip()}
    if names:
        if UploadRecord.query.filter(UploadRecord.project_name.in_(list(names))).limit(1).first():
            return True
    return False


ASSIGNED_TEAM_LOCKED_MSG = (
    "关联的页面1 已下发任务，公司管理员不可再修改所属项目组；请联系超级管理员（页面4 访问密码）处理。"
)

PROJECT_STATUS_LOCKED_MSG = (
    "关联的页面1 已下发任务，公司管理员不可在页面0 修改项目状态；"
    "请由项目管理员在页面1 修改，或联系超级管理员（页面4 访问密码）处理。"
)

ORGANIZATION_ID_LOCKED_MSG = (
    "该项目已绑定页面1 任务，不可修改所属公司；"
    "请联系超级管理员（页面4 访问密码）处理。"
)


def validate_organization_id_change(
    *,
    old_org_id: str | None,
    new_org_id: str | None,
    upload_tasks_locked: bool,
) -> str | None:
    """已有上传任务时，仅超级管理员可改所属公司。"""
    from .authz import is_page13_super_admin

    if is_page13_super_admin():
        return None
    old = (old_org_id or "").strip() or None
    new = (new_org_id or "").strip() or None
    if old == new:
        return None
    if upload_tasks_locked:
        return ORGANIZATION_ID_LOCKED_MSG
    return None


def sync_upload_records_organization_for_project(
    project: Project, organization_id: str | None
) -> None:
    """将页面1 项目关联的上传记录 organization_id 与项目对齐。"""
    pid = (getattr(project, "id", None) or "").strip()
    if pid:
        UploadRecord.query.filter(UploadRecord.project_id == pid).update(
            {"organization_id": organization_id},
            synchronize_session=False,
        )
    name = (getattr(project, "name", None) or "").strip()
    if name:
        UploadRecord.query.filter(UploadRecord.project_name == name).update(
            {"organization_id": organization_id},
            synchronize_session=False,
        )


def apply_project_organization_id(project: Project, organization_id: str | None) -> None:
    from .models import CompanyProject

    project.organization_id = organization_id
    cp_id = (getattr(project, "company_project_id", None) or "").strip()
    if cp_id:
        cp = CompanyProject.query.get(cp_id)
        if cp:
            cp.organization_id = organization_id
            db.session.add(cp)
    sync_upload_records_organization_for_project(project, organization_id)
    db.session.add(project)


def apply_company_project_organization_id(
    cp: CompanyProject, organization_id: str | None
) -> None:
    cp.organization_id = organization_id
    for p in Project.query.filter(Project.company_project_id == cp.id).all():
        p.organization_id = organization_id
        sync_upload_records_organization_for_project(p, organization_id)
        db.session.add(p)
    db.session.add(cp)


def normalize_team_name(raw: Any) -> Optional[str]:
    s = ("" if raw is None else str(raw)).strip()
    return s if s else None


def team_usage(team_id: str) -> dict[str, int]:
    tid = (team_id or "").strip()
    if not tid:
        return {"companyProjects": 0, "projects": 0, "userMemberships": 0, "total": 0}
    cp = CompanyProject.query.filter(CompanyProject.assigned_team_id == tid).count()
    pr = Project.query.filter(Project.assigned_team_id == tid).count()
    um = UserTeamMembership.query.filter(UserTeamMembership.team_id == tid).count()
    return {
        "companyProjects": cp,
        "projects": pr,
        "userMemberships": um,
        "total": cp + pr + um,
    }


def serialize_team_item(team: ProjectTeam) -> dict[str, Any]:
    from .team_organizations import organization_ids_for_team, organization_labels_for_team

    usage = team_usage(team.id)
    webhook = (getattr(team, "dingtalk_webhook", None) or "").strip()
    secret = (getattr(team, "dingtalk_secret", None) or "").strip()
    org_ids = organization_ids_for_team(team.id)
    org_labels = organization_labels_for_team(team.id)
    return {
        "id": team.id,
        "name": team.name,
        "organizationId": org_ids[0] if org_ids else None,
        "organizationIds": org_ids,
        "organizations": org_labels,
        "sortOrder": team.sort_order,
        "isActive": bool(team.is_active),
        "dingtalkWebhook": webhook or None,
        "dingtalkSecretMasked": "******" if secret else None,
        "hasDingtalkSecret": bool(secret),
        "usageCount": usage["total"],
        "usage": usage,
        "canDelete": usage["total"] == 0,
    }


def update_team_name(team_id: str, new_name_raw: Any) -> tuple[ProjectTeam | None, str | None]:
    t = ProjectTeam.query.get(team_id)
    if not t:
        return None, "未找到该项目组"
    new_name = normalize_team_name(new_name_raw)
    if not new_name:
        return None, "组名不能为空"
    if new_name == (t.name or "").strip():
        return t, None
    other = ProjectTeam.query.filter(
        ProjectTeam.id != team_id, ProjectTeam.name == new_name
    ).first()
    if other:
        return None, "组名已存在"
    t.name = new_name
    db.session.add(t)
    return t, None


def delete_team(team_id: str) -> tuple[bool, str | None]:
    from .models import ProjectTeamOrganization

    t = ProjectTeam.query.get(team_id)
    if not t:
        return False, "未找到该项目组"
    usage = team_usage(team_id)
    if usage["total"] > 0:
        parts = []
        if usage["companyProjects"]:
            parts.append(f"公司总览 {usage['companyProjects']} 项")
        if usage["projects"]:
            parts.append(f"页面1 项目 {usage['projects']} 项")
        if usage["userMemberships"]:
            parts.append(f"账号绑定 {usage['userMemberships']} 项")
        detail = "、".join(parts) if parts else f"{usage['total']} 处"
        return False, f"该项目组已被引用（{detail}），无法删除"
    ProjectTeamOrganization.query.filter_by(team_id=team_id).delete(synchronize_session=False)
    db.session.delete(t)
    return True, None
