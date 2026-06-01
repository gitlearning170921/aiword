# -*- coding: utf-8 -*-
"""项目组字典：页面0 维护，引用检查。"""
from __future__ import annotations

from typing import Any, Optional

from . import db
from .models import CompanyProject, Project, ProjectTeam, UploadRecord, UserTeamMembership


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
    "关联的页面1 已下发任务，公司管理员不可再修改所属项目组；请联系超级管理员（页面1·3 访问密码）处理。"
)

PROJECT_STATUS_LOCKED_MSG = (
    "关联的页面1 已下发任务，公司管理员不可在页面0 修改项目状态；"
    "请由项目管理员在页面1 修改，或联系超级管理员（页面1·3 访问密码）处理。"
)


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
    usage = team_usage(team.id)
    webhook = (getattr(team, "dingtalk_webhook", None) or "").strip()
    secret = (getattr(team, "dingtalk_secret", None) or "").strip()
    return {
        "id": team.id,
        "name": team.name,
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
    db.session.delete(t)
    return True, None
