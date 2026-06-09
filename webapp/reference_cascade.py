# -*- coding: utf-8 -*-
"""超级管理员：字典级联删除、项目公司/项目组变更级联同步。"""
from __future__ import annotations

from typing import Any, Optional

from . import db
from .models import (
    AuditJob,
    CompanyProject,
    DraftGenerationJob,
    Project,
    RegisteredCountry,
    TranslationJob,
    UploadRecord,
    UserCountryScope,
    UserTeamMembership,
)


def _upload_ids_for_project(project: Project) -> list[str]:
    from .project_teams import _project_name_keys_for_upload_lookup

    pid = str(getattr(project, "id", "") or "").strip()
    ids: set[str] = set()
    if pid:
        for r in UploadRecord.query.filter(UploadRecord.project_id == pid).all():
            uid = str(getattr(r, "id", "") or "").strip()
            if uid:
                ids.add(uid)
    for name in _project_name_keys_for_upload_lookup(project):
        for r in UploadRecord.query.filter(UploadRecord.project_name == name).all():
            uid = str(getattr(r, "id", "") or "").strip()
            if uid:
                ids.add(uid)
    return sorted(ids)


def _job_snapshot_refs_upload(snap: Any, upload_id: str) -> bool:
    """与 _integration_common._job_snapshot_refs_upload 保持一致。"""
    if not isinstance(snap, dict) or not upload_id:
        return False
    bu = str(snap.get("base_upload_id") or "").strip()
    if bu and bu == upload_id:
        return True
    bus = snap.get("base_upload_ids")
    if isinstance(bus, list):
        for x in bus:
            if str(x).strip() == upload_id:
                return True
    uids = snap.get("upload_ids")
    if isinstance(uids, list):
        for x in uids:
            if str(x).strip() == upload_id:
                return True
    return False


def _job_references_upload(job: Any, upload_ids: set[str]) -> bool:
    if not upload_ids:
        return False
    raw = getattr(job, "upload_ids_json", None)
    if isinstance(raw, list):
        for x in raw:
            s = str(x or "").strip()
            if s and s in upload_ids:
                return True
    snap = getattr(job, "payload_snapshot_json", None)
    if isinstance(snap, dict):
        for uid in upload_ids:
            if _job_snapshot_refs_upload(snap, uid):
                return True
    return False


def sync_jobs_organization_for_upload_ids(
    upload_ids: list[str], organization_id: str | None
) -> dict[str, int]:
    """将集成任务（审核/翻译/初稿）organization_id 与上传记录对齐。"""
    uid_set = {str(x or "").strip() for x in (upload_ids or []) if str(x or "").strip()}
    counts = {"auditJobs": 0, "translationJobs": 0, "draftJobs": 0}
    if not uid_set:
        return counts
    oid = str(organization_id or "").strip() or None
    for row in AuditJob.query.all():
        if _job_references_upload(row, uid_set):
            row.organization_id = oid
            db.session.add(row)
            counts["auditJobs"] += 1
    for row in TranslationJob.query.all():
        if _job_references_upload(row, uid_set):
            row.organization_id = oid
            db.session.add(row)
            counts["translationJobs"] += 1
    for row in DraftGenerationJob.query.all():
        if _job_references_upload(row, uid_set):
            row.organization_id = oid
            db.session.add(row)
            counts["draftJobs"] += 1
    return counts


def registered_country_delete_impact(country_id: str) -> dict[str, Any]:
    from .registered_countries import registered_country_usage

    row = RegisteredCountry.query.get(country_id)
    if not row:
        return {"ok": False, "message": "未找到该字典项"}
    name = str(row.name or "").strip()
    usage = registered_country_usage(name)
    parts: list[str] = []
    if usage.get("companyProjects"):
        parts.append(f"{usage['companyProjects']} 个公司总览项目的注册国家")
    if usage.get("projects"):
        parts.append(f"{usage['projects']} 个页面1 项目的注册国家")
    if usage.get("userScopes"):
        parts.append(f"{usage['userScopes']} 条账号国家维度绑定")
    detail = "、".join(parts) if parts else "无关联数据"
    label = f"注册国家「{name}」"
    confirm = f"当前操作{label}及其关联的 {detail} 都会被删除，是否确认？"
    return {
        "ok": True,
        "name": name,
        "usage": usage,
        "requiresCascade": usage.get("total", 0) > 0,
        "confirmMessage": confirm,
    }


def cascade_delete_registered_country(country_id: str) -> tuple[bool, str | None, dict[str, int]]:
    row = RegisteredCountry.query.get(country_id)
    if not row:
        return False, "未找到该字典项", {}
    name = str(row.name or "").strip()
    if not name:
        db.session.delete(row)
        return True, None, {}
    counts = {
        "userScopes": UserCountryScope.query.filter_by(registered_country=name).delete(
            synchronize_session=False
        ),
        "companyProjects": CompanyProject.query.filter_by(registered_country=name).update(
            {"registered_country": None}, synchronize_session=False
        ),
        "projects": Project.query.filter_by(registered_country=name).update(
            {"registered_country": None}, synchronize_session=False
        ),
    }
    db.session.delete(row)
    return True, None, counts


def team_delete_impact(team_id: str) -> dict[str, Any]:
    from .project_teams import team_usage
    from .models import ProjectTeam

    t = ProjectTeam.query.get(team_id)
    if not t:
        return {"ok": False, "message": "未找到该项目组"}
    usage = team_usage(team_id)
    name = str(t.name or team_id).strip()
    parts: list[str] = []
    if usage.get("companyProjects"):
        parts.append(f"{usage['companyProjects']} 个公司总览项目的项目组归属")
    if usage.get("projects"):
        parts.append(f"{usage['projects']} 个页面1 项目的项目组归属")
    if usage.get("userMemberships"):
        parts.append(f"{usage['userMemberships']} 条账号项目组绑定")
    detail = "、".join(parts) if parts else "无关联数据"
    label = f"项目组「{name}」"
    confirm = f"当前操作{label}及其关联的 {detail} 都会被删除，是否确认？"
    return {
        "ok": True,
        "name": name,
        "usage": usage,
        "requiresCascade": usage.get("total", 0) > 0,
        "confirmMessage": confirm,
    }


def cascade_delete_team(team_id: str) -> tuple[bool, str | None, dict[str, int]]:
    from .models import ProjectTeam, ProjectTeamOrganization

    t = ProjectTeam.query.get(team_id)
    if not t:
        return False, "未找到该项目组", {}
    tid = str(team_id or "").strip()
    counts = {
        "userMemberships": UserTeamMembership.query.filter_by(team_id=tid).delete(
            synchronize_session=False
        ),
        "companyProjects": CompanyProject.query.filter_by(assigned_team_id=tid).update(
            {"assigned_team_id": None}, synchronize_session=False
        ),
        "projects": Project.query.filter_by(assigned_team_id=tid).update(
            {"assigned_team_id": None}, synchronize_session=False
        ),
        "teamOrganizations": ProjectTeamOrganization.query.filter_by(team_id=tid).delete(
            synchronize_session=False
        ),
    }
    db.session.delete(t)
    return True, None, counts


def project_organization_change_impact(
    project: Project, new_org_id: str | None
) -> dict[str, Any]:
    old = str(getattr(project, "organization_id", "") or "").strip() or None
    new = str(new_org_id or "").strip() or None
    if old == new:
        return {"ok": True, "changed": False, "confirmMessage": ""}
    upload_ids = _upload_ids_for_project(project)
    upload_count = len(upload_ids)
    parts: list[str] = []
    if upload_count:
        parts.append(f"{upload_count} 条任务记录")
    linked_cp = str(getattr(project, "company_project_id", "") or "").strip()
    if linked_cp:
        parts.append("关联的总览项目所属公司")
    job_hint = ""
    if upload_ids:
        job_hint = "及关联的审核/翻译/初稿任务"
    detail = "、".join(parts) if parts else "项目所属公司"
    confirm = f"当前操作将同步更新{detail}{job_hint}，是否确认？"
    return {
        "ok": True,
        "changed": True,
        "oldOrganizationId": old,
        "newOrganizationId": new,
        "uploadCount": upload_count,
        "confirmMessage": confirm,
    }


def company_project_organization_change_impact(
    cp: CompanyProject, new_org_id: str | None
) -> dict[str, Any]:
    old = str(getattr(cp, "organization_id", "") or "").strip() or None
    new = str(new_org_id or "").strip() or None
    if old == new:
        return {"ok": True, "changed": False, "confirmMessage": ""}
    linked = Project.query.filter(Project.company_project_id == cp.id).all()
    upload_total = 0
    for p in linked:
        upload_total += len(_upload_ids_for_project(p))
    parts = [f"公司总览项目及 {len(linked)} 个关联页面1 项目的所属公司"]
    if upload_total:
        parts.append(f"{upload_total} 条任务记录")
    detail = "、".join(parts)
    confirm = f"当前操作将同步更新{detail}及相关集成任务，是否确认？"
    return {
        "ok": True,
        "changed": True,
        "linkedPage1Count": len(linked),
        "uploadCount": upload_total,
        "confirmMessage": confirm,
    }


def company_project_team_change_impact(
    cp: CompanyProject, new_team_id: str | None
) -> dict[str, Any]:
    old = str(getattr(cp, "assigned_team_id", "") or "").strip() or None
    new = str(new_team_id or "").strip() or None
    if old == new:
        return {"ok": True, "changed": False, "confirmMessage": ""}
    linked = Project.query.filter(Project.company_project_id == cp.id).count()
    confirm = (
        f"当前操作将同步更新公司总览项目及 {linked} 个关联页面1 项目的所属项目组，是否确认？"
    )
    return {
        "ok": True,
        "changed": True,
        "linkedPage1Count": linked,
        "confirmMessage": confirm,
    }


def sync_project_organization_cascade(project: Project, organization_id: str | None) -> dict[str, int]:
    """扩展 organization 同步：上传记录 + 集成任务。"""
    from .project_teams import sync_upload_records_organization_for_project

    sync_upload_records_organization_for_project(project, organization_id)
    upload_ids = _upload_ids_for_project(project)
    job_counts = sync_jobs_organization_for_upload_ids(upload_ids, organization_id)
    return {
        "uploadRecords": len(upload_ids),
        **job_counts,
    }
