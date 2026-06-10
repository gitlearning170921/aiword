# -*- coding: utf-8 -*-
"""项目组字典：页面0 维护，引用检查。"""
from __future__ import annotations

from typing import Any, Optional

from . import db
from .models import CompanyProject, Project, ProjectTeam, UploadRecord, UserTeamMembership


def _project_name_keys_for_upload_lookup(project: Project) -> list[str]:
    """上传记录 project_name 可能为原始名或三字段展示键，查询时需两者兼顾。"""
    raw = (getattr(project, "name", None) or "").strip()
    keys: list[str] = []
    if raw:
        keys.append(raw)
    c = (getattr(project, "registered_country", None) or "").strip()
    cat = (getattr(project, "registered_category", None) or "").strip()
    if raw and (c or cat):
        display = f"{raw}（{c or '—'} / {cat or '—'}）"
        if display not in keys:
            keys.append(display)
    return keys


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
    for name in _project_name_keys_for_upload_lookup(row):
        if UploadRecord.query.filter(UploadRecord.project_name == name).limit(1).first():
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
    names: set[str] = set()
    for p in linked:
        for key in _project_name_keys_for_upload_lookup(p):
            names.add(key)
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
    for name in _project_name_keys_for_upload_lookup(project):
        UploadRecord.query.filter(UploadRecord.project_name == name).update(
            {"organization_id": organization_id},
            synchronize_session=False,
        )


def apply_project_organization_id(project: Project, organization_id: str | None) -> None:
    from .models import CompanyProject
    from .reference_cascade import sync_project_organization_cascade

    project.organization_id = organization_id
    cp_id = (getattr(project, "company_project_id", None) or "").strip()
    if cp_id:
        cp = CompanyProject.query.get(cp_id)
        if cp:
            cp.organization_id = organization_id
            db.session.add(cp)
    sync_project_organization_cascade(project, organization_id)
    db.session.add(project)


def validate_project_assigned_team_change(
    project: Project, new_team_id: str | None
) -> str | None:
    """页面1 已有任务后，仅超级管理员可改所属项目组。"""
    from .authz import is_page13_super_admin

    if is_page13_super_admin():
        return None
    old = (getattr(project, "assigned_team_id", None) or "").strip() or None
    new = (new_team_id or "").strip() or None
    if old == new:
        return None
    if project_has_page1_upload_tasks(project.id):
        return ASSIGNED_TEAM_LOCKED_MSG
    return None


def apply_project_assigned_team_id(project: Project, team_id: str | None) -> None:
    """页面1 项目组变更：同步关联公司总览（若已关联）。"""
    tid = str(team_id or "").strip() or None
    project.assigned_team_id = tid
    cp_id = (getattr(project, "company_project_id", None) or "").strip()
    if cp_id:
        from .models import CompanyProject

        cp = CompanyProject.query.get(cp_id)
        if cp:
            cp.assigned_team_id = tid
            db.session.add(cp)
    db.session.add(project)


def apply_company_project_organization_id(
    cp: CompanyProject, organization_id: str | None
) -> None:
    cp.organization_id = organization_id
    for p in Project.query.filter(Project.company_project_id == cp.id).all():
        p.organization_id = organization_id
        from .reference_cascade import sync_project_organization_cascade

        sync_project_organization_cascade(p, organization_id)
        db.session.add(p)
    db.session.add(cp)


def apply_company_project_assigned_team_id(
    cp: CompanyProject, team_id: str | None
) -> None:
    """公司总览项目组变更：同步关联页面1 项目。"""
    cp.assigned_team_id = team_id
    tid = str(team_id or "").strip() or None
    for p in Project.query.filter(Project.company_project_id == cp.id).all():
        p.assigned_team_id = tid
        db.session.add(p)
    db.session.add(cp)


def resolve_organization_id_for_project_upload(
    *,
    project_id: str | None = None,
    project: Project | None = None,
) -> str | None:
    """新建/更新上传记录时写入 organization_id（多租户集成与筛选依赖）。"""
    row = project
    if row is None and project_id:
        row = Project.query.get(project_id)
    if row is not None:
        oid = str(getattr(row, "organization_id", "") or "").strip()
        if oid:
            return oid
    try:
        from .tenant_context import resolve_organization_context

        oid, _ = resolve_organization_context()
        return str(oid or "").strip() or None
    except Exception:
        return None


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


def _normalize_dingtalk_webhook_url(url: str) -> str:
    return str(url or "").strip().rstrip("/")


def _system_dingtalk_webhook_urls() -> set[str]:
    """全局催办/体系机器人 Webhook（用于识别误写入项目组的同 URL）。"""
    import os

    from .app_settings import get_setting

    out: set[str] = set()
    keys = ("DINGTALK_WEBHOOK", "CHATBOT_DINGTALK_WEBHOOK")
    for key in keys:
        for raw in (
            (get_setting(key) or "").strip(),
            (os.environ.get(key) or "").strip(),
        ):
            if raw:
                out.add(_normalize_dingtalk_webhook_url(raw))
    try:
        from flask import current_app

        app = current_app._get_current_object()
        for key in keys:
            cfg = (app.config.get(key) or "").strip()
            if cfg:
                out.add(_normalize_dingtalk_webhook_url(cfg))
    except Exception:
        pass
    w = (get_setting("DINGTALK_WEBHOOK") or "").strip()
    c = (get_setting("CHATBOT_DINGTALK_WEBHOOK") or "").strip()
    if not c and w:
        out.add(_normalize_dingtalk_webhook_url(w))
    return out


def normalize_team_dingtalk_webhook_for_storage(raw: str | None) -> str | None:
    """入库：空值或与本系统全局/体系机器人相同则存 None（发送时走回退）。"""
    url = (raw or "").strip() or None
    if not url:
        return None
    if _normalize_dingtalk_webhook_url(url) in _system_dingtalk_webhook_urls():
        return None
    return url


def scrub_team_dingtalk_global_echo(*, commit: bool = False) -> int:
    """清除项目组库内与全局/体系机器人相同的 Webhook（展示与发送均走回退逻辑）。"""
    system_urls = _system_dingtalk_webhook_urls()
    if not system_urls:
        return 0
    changed = 0
    for team in ProjectTeam.query.all():
        raw = (getattr(team, "dingtalk_webhook", None) or "").strip()
        if not raw:
            continue
        if _normalize_dingtalk_webhook_url(raw) in system_urls:
            team.dingtalk_webhook = None
            db.session.add(team)
            changed += 1
    if commit and changed:
        db.session.commit()
    return changed


def team_dingtalk_webhook_for_settings(team: ProjectTeam) -> str | None:
    """设置页展示项目组独立 Webhook（与全局相同视为未单独配置）。"""
    webhook = (getattr(team, "dingtalk_webhook", None) or "").strip()
    if not webhook:
        return None
    if _normalize_dingtalk_webhook_url(webhook) in _system_dingtalk_webhook_urls():
        return None
    return webhook


def apply_team_dingtalk_settings(team: ProjectTeam, data: dict) -> dict[str, bool]:
    """写入项目组钉钉配置；返回 {webhookEchoesGlobal, secretUpdated}。"""
    flags = {"webhookEchoesGlobal": False, "secretUpdated": False}
    if "dingtalkWebhook" in data:
        requested = (data.get("dingtalkWebhook") or "").strip()
        stored = normalize_team_dingtalk_webhook_for_storage(data.get("dingtalkWebhook"))
        team.dingtalk_webhook = stored
        flags["webhookEchoesGlobal"] = bool(requested and not stored)
    if "dingtalkSecret" in data:
        raw_secret = data.get("dingtalkSecret")
        if raw_secret is None:
            pass
        else:
            stripped = (raw_secret or "").strip()
            if stripped:
                team.dingtalk_secret = stripped
                flags["secretUpdated"] = True
            # 空串表示「保持不变」，不覆盖原 secret
    db.session.add(team)
    return flags


def serialize_team_item(team: ProjectTeam) -> dict[str, Any]:
    from .team_organizations import organization_ids_for_team, organization_labels_for_team

    usage = team_usage(team.id)
    webhook = team_dingtalk_webhook_for_settings(team)
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
        "dingtalkUsesGlobalFallback": not bool(webhook),
        "dingtalkSecretMasked": "******" if secret else None,
        "hasDingtalkSecret": bool(secret),
        "usageCount": usage["total"],
        "usage": usage,
        "canDelete": True,
        "requiresCascadeConfirm": usage["total"] > 0,
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


def delete_team(team_id: str, *, cascade: bool = False) -> tuple[bool, str | None]:
    from .models import ProjectTeamOrganization

    t = ProjectTeam.query.get(team_id)
    if not t:
        return False, "未找到该项目组"
    usage = team_usage(team_id)
    if usage["total"] > 0 and not cascade:
        parts = []
        if usage["companyProjects"]:
            parts.append(f"公司总览 {usage['companyProjects']} 项")
        if usage["projects"]:
            parts.append(f"页面1 项目 {usage['projects']} 项")
        if usage["userMemberships"]:
            parts.append(f"账号绑定 {usage['userMemberships']} 项")
        detail = "、".join(parts) if parts else f"{usage['total']} 处"
        return False, f"该项目组已被引用（{detail}），无法删除"
    if usage["total"] > 0 and cascade:
        from .reference_cascade import cascade_delete_team

        ok, err, _ = cascade_delete_team(team_id)
        return ok, err
    ProjectTeamOrganization.query.filter_by(team_id=team_id).delete(synchronize_session=False)
    db.session.delete(t)
    return True, None
