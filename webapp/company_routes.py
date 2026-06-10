# -*- coding: utf-8 -*-
"""公司级项目总览：独立 company_projects 表，与页面1 projects 一对多关联。"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

import requests
from flask import Blueprint, current_app, jsonify, render_template, request, session
from sqlalchemy import or_

from . import db
from ._integration_common import integration_api_base, integration_requests_timeout, upstream_headers
from .app_settings import is_multi_tenant_enabled
from .authz import (
    company_admin_write_required,
    company_registry_api_required,
    company_registry_enabled,
    company_registry_page_required,
    is_company_admin,
    is_page13_super_admin,
    parse_optional_date,
    project_display_label,
    super_admin_required,
    user_country_scopes,
)
from .models import (
    AuditJob,
    CompanyProject,
    DraftGenerationJob,
    ExamAttempt,
    ExamCenterActivity,
    ExamCenterAssignment,
    Organization,
    Project,
    ProjectTeam,
    REGISTRATION_SCOPE_COMPANY,
    REGISTRATION_SCOPE_LEGACY,
    TranslationJob,
    UploadRecord,
    User,
    UserOrganizationMembership,
    UserTeamMembership,
    now_local,
)
from .tenant_context import collection_for_organization, default_organization, resolve_organization_context

company_bp = Blueprint("company", __name__)


def _visible_organization_ids_for_session() -> list[str]:
    from .tenant_context import user_allowed_organization_ids

    if is_page13_super_admin():
        rows = Organization.query.order_by(Organization.created_at.asc()).all()
        return [str(r.id or "").strip() for r in rows if str(r.id or "").strip()]
    ids = user_allowed_organization_ids()
    if ids:
        return ids
    if session.get("user_id"):
        return []
    d = default_organization()
    did = str(getattr(d, "id", "") or "").strip()
    return [did] if did else []


def _visible_organizations_payload() -> list[dict[str, Any]]:
    ids = _visible_organization_ids_for_session()
    if not ids:
        return []
    rows = (
        Organization.query.filter(Organization.id.in_(ids))
        .order_by(Organization.created_at.asc())
        .all()
    )
    by_id = {str(r.id or "").strip(): r for r in rows}
    out: list[dict[str, Any]] = []
    for oid in ids:
        r = by_id.get(oid)
        if not r:
            continue
        out.append(
            {
                "id": oid,
                "name": str(r.name or "").strip() or oid,
                "knowledgeCollection": str(r.knowledge_collection or "").strip() or "regulations",
                "isDefault": bool(getattr(r, "is_default", False)),
                "isActive": bool(getattr(r, "is_active", True)),
            }
        )
    return out


def _current_company_scope_org_id() -> str:
    oid, _ = resolve_organization_context()
    return str(oid or "").strip()


def _requested_company_scope_org_ids() -> tuple[list[str], str | None]:
    """列表/候选接口：默认按账号可见公司并集，支持按 query.organizationId 单公司过滤。"""
    visible = [str(x).strip() for x in _visible_organization_ids_for_session() if str(x).strip()]
    if not is_multi_tenant_enabled():
        return visible, None
    raw = str(request.args.get("organizationId") or request.args.get("organization_id") or "").strip()
    if not raw or raw in {"__all__", "all", "*"}:
        return visible, None
    if raw not in set(visible):
        return [], "无权筛选该公司"
    return [raw], None


def _company_project_in_active_org(cp: CompanyProject | None) -> bool:
    if cp is None:
        return False
    if not is_multi_tenant_enabled():
        return True
    oid = _current_company_scope_org_id()
    if not oid:
        return True
    return str(getattr(cp, "organization_id", "") or "").strip() == oid


def _sync_org_to_aicheckword(*, org: Organization, delete: bool = False) -> None:
    """把 aiword organization 映射同步到 aicheckword companies（失败仅记录日志，不阻断主流程）。"""
    base = integration_api_base()
    if not base:
        return
    oid = str(getattr(org, "id", "") or "").strip()
    if not oid:
        return
    try:
        if delete:
            requests.delete(
                f"{base.rstrip('/')}/admin/companies/sync/{oid}",
                headers=upstream_headers(for_multipart=False, organization_id=oid),
                timeout=integration_requests_timeout(read_seconds=30),
            )
            return
        requests.post(
            f"{base.rstrip('/')}/admin/companies/sync",
            json={
                "aiword_company_id": oid,
                "name": str(org.name or "").strip(),
                "slug": str(org.slug or "").strip(),
                "knowledge_collection": str(org.knowledge_collection or "").strip() or "regulations",
                "is_active": bool(getattr(org, "is_active", True)),
                "is_default": bool(getattr(org, "is_default", False)),
            },
            headers=upstream_headers(for_multipart=False, organization_id=oid),
            timeout=integration_requests_timeout(read_seconds=30),
        )
    except Exception:
        try:
            current_app.logger.exception("sync organization to aicheckword failed org=%s", oid)
        except Exception:
            pass


def _normalize_org_slug(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:64]


def _slug_from_name(name: str) -> str:
    base = _normalize_org_slug(name)
    if base:
        return base
    return f"company-{uuid.uuid4().hex[:8]}"


def _normalize_collection(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "_", s)
    s = re.sub(r"_{2,}", "_", s).strip("_")
    return s[:128]


def _serialize_organization(org: Organization) -> dict[str, Any]:
    from .team_organizations import count_teams_for_organization

    oid = str(org.id or "").strip()
    usage = {
        "users": UserOrganizationMembership.query.filter_by(organization_id=oid).count(),
        "projectTeams": count_teams_for_organization(oid),
        "companyProjects": CompanyProject.query.filter_by(organization_id=oid).count(),
        "projects": Project.query.filter_by(organization_id=oid).count(),
        "uploads": UploadRecord.query.filter_by(organization_id=oid).count(),
        "draftJobs": DraftGenerationJob.query.filter_by(organization_id=oid).count(),
        "auditJobs": AuditJob.query.filter_by(organization_id=oid).count(),
        "translationJobs": TranslationJob.query.filter_by(organization_id=oid).count(),
        "examAssignments": ExamCenterAssignment.query.filter_by(organization_id=oid).count(),
        "examActivities": ExamCenterActivity.query.filter_by(organization_id=oid).count(),
        "examAttempts": ExamAttempt.query.filter_by(organization_id=oid).count(),
    }
    return {
        "id": oid,
        "name": org.name,
        "slug": org.slug,
        "knowledgeCollection": org.knowledge_collection,
        "isActive": bool(getattr(org, "is_active", True)),
        "isDefault": bool(getattr(org, "is_default", False)),
        "usage": usage,
        "usageCount": int(sum(int(v or 0) for v in usage.values())),
        "createdAt": org.created_at.isoformat() if org.created_at else None,
        "updatedAt": org.updated_at.isoformat() if org.updated_at else None,
    }


def _organization_delete_block_reason(org_id: str) -> str:
    from .team_organizations import organization_has_team

    if UserOrganizationMembership.query.filter_by(organization_id=org_id).first():
        return "已有账号绑定该公司，无法删除"
    if organization_has_team(org_id):
        return "已有项目组绑定该公司，无法删除"
    if CompanyProject.query.filter_by(organization_id=org_id).first():
        return "已有页面0 项目绑定该公司，无法删除"
    if Project.query.filter_by(organization_id=org_id).first():
        return "已有页面1 项目绑定该公司，无法删除"
    if UploadRecord.query.filter_by(organization_id=org_id).first():
        return "已有上传记录绑定该公司，无法删除"
    if DraftGenerationJob.query.filter_by(organization_id=org_id).first():
        return "已有初稿任务绑定该公司，无法删除"
    if AuditJob.query.filter_by(organization_id=org_id).first():
        return "已有审核任务绑定该公司，无法删除"
    if TranslationJob.query.filter_by(organization_id=org_id).first():
        return "已有翻译任务绑定该公司，无法删除"
    if ExamCenterAssignment.query.filter_by(organization_id=org_id).first():
        return "已有考试任务绑定该公司，无法删除"
    if ExamCenterActivity.query.filter_by(organization_id=org_id).first():
        return "已有考试记录绑定该公司，无法删除"
    if ExamAttempt.query.filter_by(organization_id=org_id).first():
        return "已有作答记录绑定该公司，无法删除"
    return ""


def _team_name_map() -> dict[str, str]:
    return {t.id: t.name for t in ProjectTeam.query.all()}


def _migrate_scope_company_to_company_projects(scope_org_ids: list[str] | None = None) -> int:
    """历史数据：registration_scope=company 的页面1 行迁入 company_projects 并改回 legacy。"""
    q = Project.query.filter(Project.registration_scope == REGISTRATION_SCOPE_COMPANY)
    if is_multi_tenant_enabled():
        ids = scope_org_ids if scope_org_ids is not None else [_current_company_scope_org_id()]
        ids = [str(x).strip() for x in (ids or []) if str(x).strip()]
        if ids:
            q = q.filter(Project.organization_id.in_(ids))
        else:
            from sqlalchemy import false as sql_false

            q = q.filter(sql_false())
    rows = q.all()
    n = 0
    for p in rows:
        if (getattr(p, "company_project_id", None) or "").strip():
            p.registration_scope = REGISTRATION_SCOPE_LEGACY
            db.session.add(p)
            continue
        cp = CompanyProject(
            organization_id=str(getattr(p, "organization_id", "") or "").strip() or None,
            name=p.name,
            product_type=getattr(p, "product_type", None),
            registered_country=getattr(p, "registered_country", None),
            registered_category=getattr(p, "registered_category", None),
            assigned_team_id=getattr(p, "assigned_team_id", None),
            expected_certification_date=getattr(p, "expected_certification_date", None),
            expected_submission_date=getattr(p, "expected_submission_date", None),
            progress_description=getattr(p, "progress_description", None),
            priority=int(p.priority or CompanyProject.PRIORITY_MEDIUM),
            status=p.status or CompanyProject.STATUS_ACTIVE,
            created_by_user_id=getattr(p, "created_by_user_id", None),
            updated_by=getattr(p, "updated_by", None),
            progress_updated_at=getattr(p, "progress_updated_at", None),
        )
        db.session.add(cp)
        db.session.flush()
        p.company_project_id = cp.id
        p.registration_scope = REGISTRATION_SCOPE_LEGACY
        db.session.add(p)
        n += 1
    if n:
        db.session.commit()
    return n


def _sync_unlinked_page1_one_to_one(scope_org_ids: list[str] | None = None) -> int:
    """为尚未关联公司总览的页面1 项目各建一条公司项目（初始一对一，可在页面0 改绑为多对一）。"""
    _migrate_scope_company_to_company_projects(scope_org_ids=scope_org_ids)
    q = Project.query.filter(
        or_(
            Project.company_project_id.is_(None),
            Project.company_project_id == "",
        )
    )
    if is_multi_tenant_enabled():
        ids = scope_org_ids if scope_org_ids is not None else [_current_company_scope_org_id()]
        ids = [str(x).strip() for x in (ids or []) if str(x).strip()]
        if ids:
            q = q.filter(Project.organization_id.in_(ids))
        else:
            from sqlalchemy import false as sql_false

            q = q.filter(sql_false())
    rows = q.all()
    n = 0
    for p in rows:
        cp = CompanyProject(
            organization_id=str(getattr(p, "organization_id", "") or "").strip() or None,
            name=p.name,
            registered_country=getattr(p, "registered_country", None),
            registered_category=getattr(p, "registered_category", None),
            product_type=getattr(p, "product_type", None),
            assigned_team_id=getattr(p, "assigned_team_id", None),
            expected_certification_date=getattr(p, "expected_certification_date", None),
            expected_submission_date=getattr(p, "expected_submission_date", None),
            progress_description=getattr(p, "progress_description", None),
            progress_updated_at=getattr(p, "progress_updated_at", None),
            updated_by=getattr(p, "updated_by", None),
            priority=int(p.priority or CompanyProject.PRIORITY_MEDIUM),
            status=p.status or CompanyProject.STATUS_ACTIVE,
            created_by_user_id=session.get("user_id"),
        )
        db.session.add(cp)
        db.session.flush()
        p.company_project_id = cp.id
        db.session.add(p)
        n += 1
    if n:
        db.session.commit()
    return n


def _parse_project_ids(data: dict) -> list[str]:
    raw = data.get("projectIds") or data.get("ids") or data.get("companyProjectIds") or []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _parse_page1_project_ids(data: dict) -> list[str]:
    raw = data.get("page1ProjectIds") or data.get("linkedProjectIds") or []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _linked_page1_rows(company_project_id: str) -> list[Project]:
    return (
        Project.query.filter(Project.company_project_id == company_project_id)
        .order_by(Project.name.asc())
        .all()
    )


def _serialize_page1_link(p: Project) -> dict:
    from .routes import _project_priority_label, _project_status_label

    return {
        "id": p.id,
        "name": p.name,
        "registeredCountry": getattr(p, "registered_country", None),
        "registeredCategory": getattr(p, "registered_category", None),
        "projectKey": project_display_label(
            p.name, p.registered_country, p.registered_category
        ),
        "priority": int(p.priority or Project.PRIORITY_MEDIUM),
        "priorityLabel": _project_priority_label(p.priority),
        "status": p.status or Project.STATUS_ACTIVE,
        "statusLabel": _project_status_label(p.status),
    }


def _company_is_starred(cp: CompanyProject) -> bool:
    return bool(getattr(cp, "is_starred", False))


def _organization_name_map(org_ids: set[str] | list[str] | None = None) -> dict[str, str]:
    ids = {str(x or "").strip() for x in (org_ids or []) if str(x or "").strip()}
    if not ids:
        return {}
    rows = Organization.query.filter(Organization.id.in_(list(ids))).all()
    return {
        str(r.id or "").strip(): str(r.name or "").strip() or str(r.id or "").strip()
        for r in rows
    }


def _resolve_assignable_organization_id(raw: Any) -> tuple[str | None, str | None]:
    oid = str(raw or "").strip()
    if not oid:
        return None, "请选择所属公司"
    allowed = {str(x.get("id") or "").strip() for x in _visible_organizations_payload()}
    if oid not in allowed:
        return None, "无权将项目分配到该公司"
    return oid, None


def _validate_assigned_team_change(cp: CompanyProject, new_team_id: str | None) -> str | None:
    """页面1 已有任务后，仅超级管理员可改公司总览上的项目组归属。"""
    from .authz import is_page13_super_admin
    from .project_teams import ASSIGNED_TEAM_LOCKED_MSG, company_project_has_page1_upload_tasks

    if is_page13_super_admin():
        return None
    old = (getattr(cp, "assigned_team_id", None) or "").strip() or None
    new = (new_team_id or "").strip() or None
    if old == new:
        return None
    if company_project_has_page1_upload_tasks(cp.id):
        return ASSIGNED_TEAM_LOCKED_MSG
    return None


def _validate_status_change(cp: CompanyProject, new_status: str | None) -> str | None:
    """页面1 已有任务后，公司管理员不可在页面0 改状态；超级管理员可改，项目管理员在页面1 改。"""
    from .authz import is_page13_super_admin
    from .project_teams import PROJECT_STATUS_LOCKED_MSG, company_project_has_page1_upload_tasks

    if is_page13_super_admin():
        return None
    old = (cp.status or CompanyProject.STATUS_ACTIVE).strip().lower()
    new = (new_status or "").strip().lower()
    if new not in (CompanyProject.STATUS_ACTIVE, CompanyProject.STATUS_ENDED):
        return None
    if old == new:
        return None
    if company_project_has_page1_upload_tasks(cp.id):
        return PROJECT_STATUS_LOCKED_MSG
    return None


def _apply_company_fields(
    row: CompanyProject, data: dict, *, allow_team: bool = True
) -> str | None:
    """应用字段；若注册国家非法返回错误文案。"""
    if "name" in data:
        n = (data.get("name") or "").strip()
        if n:
            row.name = n
    if "registeredCountry" in data:
        from .registered_countries import validate_registered_country_selection

        rc, err = validate_registered_country_selection(data.get("registeredCountry"))
        if err:
            return err
        row.registered_country = rc
    if "registeredCategory" in data:
        row.registered_category = (data.get("registeredCategory") or "").strip() or None
    if "productType" in data:
        row.product_type = (data.get("productType") or "").strip() or None
    if "registrationOwner" in data:
        row.registration_owner = (data.get("registrationOwner") or "").strip() or None
    if allow_team and "assignedTeamId" in data:
        tid = (data.get("assignedTeamId") or "").strip() or None
        team_err = _validate_assigned_team_change(row, tid)
        if team_err:
            return team_err
        old_tid = (getattr(row, "assigned_team_id", None) or "").strip() or None
        if old_tid != tid:
            from .project_teams import apply_company_project_assigned_team_id

            apply_company_project_assigned_team_id(row, tid)
        else:
            row.assigned_team_id = tid
    if "expectedCertificationDate" in data:
        row.expected_certification_date = parse_optional_date(
            data.get("expectedCertificationDate")
        )
    if "expectedSubmissionDate" in data:
        row.expected_submission_date = parse_optional_date(
            data.get("expectedSubmissionDate")
        )
    if "progressDescription" in data:
        row.progress_description = (data.get("progressDescription") or "").strip() or None
        row.progress_updated_at = now_local()
        row.updated_by = session.get("display_name") or session.get("username") or "系统"
    if "priority" in data:
        try:
            pr = int(data.get("priority"))
            row.priority = max(
                CompanyProject.PRIORITY_LOW,
                min(CompanyProject.PRIORITY_HIGH, pr),
            )
        except Exception:
            pass
    if "status" in data:
        s = (data.get("status") or "").strip().lower()
        if s in (CompanyProject.STATUS_ACTIVE, CompanyProject.STATUS_ENDED):
            status_err = _validate_status_change(row, s)
            if status_err:
                return status_err
            row.status = s
    if "isStarred" in data:
        row.is_starred = bool(data.get("isStarred"))
    if "starred" in data and "isStarred" not in data:
        row.is_starred = bool(data.get("starred"))
    if "organizationId" in data or "organization_id" in data:
        from .project_teams import (
            apply_company_project_organization_id,
            company_project_has_page1_upload_tasks,
            validate_organization_id_change,
        )

        raw = (
            data.get("organizationId")
            if "organizationId" in data
            else data.get("organization_id")
        )
        new_oid, oid_err = _resolve_assignable_organization_id(raw)
        if oid_err:
            return oid_err
        old_oid = str(getattr(row, "organization_id", "") or "").strip() or None
        locked = company_project_has_page1_upload_tasks(row.id)
        org_err = validate_organization_id_change(
            old_org_id=old_oid,
            new_org_id=new_oid,
            upload_tasks_locked=locked,
        )
        if org_err:
            return org_err
        if old_oid != new_oid:
            apply_company_project_organization_id(row, new_oid)
    return None


def _sync_company_to_page1_after_update(cp: CompanyProject) -> None:
    from .project_registry_sync import sync_company_to_page1

    sync_company_to_page1(cp.id, push_nulls=True)


def _serialize_company_project(
    cp: CompanyProject, *, org_names: dict[str, str] | None = None
) -> dict:
    from .routes import _project_priority_label, _project_status_label

    from .project_teams import company_project_has_page1_upload_tasks

    teams = _team_name_map()
    tid = (getattr(cp, "assigned_team_id", None) or "").strip()
    linked = _linked_page1_rows(cp.id)
    team_locked = company_project_has_page1_upload_tasks(cp.id)
    org_id = str(getattr(cp, "organization_id", "") or "").strip()
    org_map = org_names or {}
    if org_id and org_id not in org_map:
        org_map = {**org_map, **_organization_name_map([org_id])}
    return {
        "id": cp.id,
        "name": cp.name,
        "organizationId": org_id or None,
        "organizationName": org_map.get(org_id) if org_id else None,
        "organizationIdLocked": team_locked,
        "registeredCountry": getattr(cp, "registered_country", None),
        "registeredCategory": getattr(cp, "registered_category", None),
        "productType": getattr(cp, "product_type", None),
        "assignedTeamId": tid or None,
        "assignedTeamName": teams.get(tid) if tid else None,
        "assignedTeamIdLocked": team_locked,
        "projectStatusLocked": team_locked,
        "page1HasUploadTasks": team_locked,
        "page1UploadTasksLocked": team_locked,
        "expectedCertificationDate": (
            cp.expected_certification_date.strftime("%Y-%m-%d")
            if getattr(cp, "expected_certification_date", None)
            else None
        ),
        "expectedSubmissionDate": (
            cp.expected_submission_date.strftime("%Y-%m-%d")
            if getattr(cp, "expected_submission_date", None)
            else None
        ),
        "progressDescription": getattr(cp, "progress_description", None),
        "priority": int(cp.priority or CompanyProject.PRIORITY_MEDIUM),
        "priorityLabel": _project_priority_label(cp.priority),
        "status": cp.status or CompanyProject.STATUS_ACTIVE,
        "statusLabel": _project_status_label(cp.status),
        "isStarred": _company_is_starred(cp),
        "registrationOwner": getattr(cp, "registration_owner", None),
        "updatedAt": cp.updated_at.isoformat() if cp.updated_at else None,
        "linkedPage1Count": len(linked),
        "linkedPage1Projects": [_serialize_page1_link(p) for p in linked],
    }


def _delete_company_projects(company_project_ids: list[str]) -> int:
    """删除公司总览记录，仅解除页面1 关联，不删页面1 项目行。"""
    n = 0
    for cid in company_project_ids:
        cp = CompanyProject.query.get(cid)
        if not cp:
            continue
        Project.query.filter(Project.company_project_id == cid).update(
            {"company_project_id": None},
            synchronize_session=False,
        )
        db.session.delete(cp)
        n += 1
    if n:
        db.session.commit()
    return n


def _set_page1_links(company_project_id: str, page1_ids: list[str]) -> dict:
    """将页面1 项目绑定到指定公司总览项目（一对多）；先从其它公司总览解绑。"""
    cp = CompanyProject.query.get(company_project_id)
    if not cp:
        return {"error": "未找到该公司总览项目", "code": 404}
    cp_org = str(getattr(cp, "organization_id", "") or "").strip()
    want = set(page1_ids)
    # 从本公司总览移除未勾选的
    for p in _linked_page1_rows(company_project_id):
        if p.id not in want:
            p.company_project_id = None
            db.session.add(p)
    linked = 0
    for pid in want:
        row = Project.query.get(pid)
        if not row:
            continue
        if cp_org:
            p_org = str(getattr(row, "organization_id", "") or "").strip()
            if p_org and p_org != cp_org:
                continue
        row.company_project_id = company_project_id
        if row.registration_scope_effective() == REGISTRATION_SCOPE_COMPANY:
            row.registration_scope = REGISTRATION_SCOPE_LEGACY
        db.session.add(row)
        linked += 1
    from .project_registry_sync import sync_company_to_page1

    sync_company_to_page1(company_project_id, push_nulls=True)
    db.session.commit()
    return {"linked": linked}


@company_bp.route("/company")
@company_registry_page_required
def company_registry_page():
    from .authz import is_page13_super_admin

    if is_page13_super_admin():
        scope_label = "全部（页面4 访问密码 · 超级管理员）"
    else:
        scopes = user_country_scopes()
        scope_label = (
            "、".join(scopes) if scopes else "全部国家（未单独配置国家维度）"
        )
    return render_template(
        "company_registry.html",
        hide_main_nav=False,
        gate_page=False,
        country_scope_label=scope_label,
        page13_super_admin=is_page13_super_admin(),
    )


@company_bp.get("/api/company/context")
@company_registry_api_required
def api_company_context():
    orgs = _visible_organizations_payload()
    active = str(session.get("active_organization_id") or "").strip()
    if orgs and active not in {str(x.get("id") or "").strip() for x in orgs}:
        active = str(orgs[0].get("id") or "").strip()
        session["active_organization_id"] = active
    if not active and orgs:
        active = str(orgs[0].get("id") or "").strip()
        session["active_organization_id"] = active
    return jsonify(
        {
            "multiTenantEnabled": bool(is_multi_tenant_enabled()),
            "activeOrganizationId": active or None,
            "activeKnowledgeCollection": collection_for_organization(active) if active else "regulations",
            "organizations": orgs,
        }
    )


@company_bp.post("/api/company/context/active")
@company_registry_api_required
def api_company_context_set_active():
    data = request.get_json(force=True) or {}
    target = str(data.get("organizationId") or data.get("organization_id") or "").strip()
    allowed = {str(x.get("id") or "").strip() for x in _visible_organizations_payload()}
    if not target:
        return jsonify({"message": "缺少 organizationId"}), 400
    if target not in allowed:
        return jsonify({"message": "无权切换到该公司"}), 403
    session["active_organization_id"] = target
    return jsonify(
        {
            "message": "已切换当前公司",
            "activeOrganizationId": target,
            "activeKnowledgeCollection": collection_for_organization(target),
        }
    )


@company_bp.get("/api/company/training/meta")
@company_registry_api_required
def api_company_training_meta():
    """项目案例训练：拉取 aicheckword 字典与已有案例列表（与 integration bootstrap 同源）。"""
    explicit_org = str(
        request.args.get("organizationId") or request.args.get("organization_id") or ""
    ).strip()
    try:
        organization_id, collection = resolve_organization_context(
            explicit_organization_id=explicit_org or None
        )
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 403
    from ._integration_common import fetch_upstream_common_bootstrap

    data, err = fetch_upstream_common_bootstrap(
        collection, organization_id=organization_id or None
    )
    if err:
        return jsonify({"message": err}), 502
    assert data is not None
    return jsonify(
        {
            "ok": True,
            "organizationId": organization_id or None,
            "collection": collection,
            "documentLanguages": data.get("documentLanguages") or [],
            "registrationCountries": data.get("registrationCountries") or [],
            "registrationTypes": data.get("registrationTypes") or [],
            "registrationComponents": data.get("registrationComponents") or [],
            "projectForms": data.get("projectForms") or [],
            "cases": data.get("cases") or [],
        }
    )


@company_bp.get("/api/company/training/status")
@company_registry_api_required
def api_company_training_status():
    explicit_org = str(
        request.args.get("organizationId") or request.args.get("organization_id") or ""
    ).strip()
    try:
        organization_id, collection = resolve_organization_context(
            explicit_organization_id=explicit_org or None
        )
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 403
    from .aicheckword_core_proxy import upstream_get

    resp, code = upstream_get(
        "status",
        params={"collection": collection},
        organization_id=organization_id or None,
    )
    if code != 200:
        return resp, code
    data = resp.get_json()
    return jsonify(
        {
            "ok": True,
            "organizationId": organization_id,
            "collection": collection,
            "status": data.get("upstream") if isinstance(data, dict) else data,
        }
    )


@company_bp.post("/api/company/training/checklist/generate")
@company_admin_write_required
def api_company_training_checklist_generate():
    data = request.get_json(force=True) or {}
    explicit_org = str(data.get("organizationId") or data.get("organization_id") or "").strip()
    try:
        organization_id, collection = resolve_organization_context(
            explicit_organization_id=explicit_org or None
        )
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 403
    from .aicheckword_core_proxy import upstream_form_post

    form_data = {"collection": collection}
    base_cl = str(data.get("baseChecklist") or data.get("base_checklist") or "").strip()
    if base_cl:
        form_data["base_checklist"] = base_cl
    resp, code = upstream_form_post(
        "checklist/generate",
        data=form_data,
        organization_id=organization_id or None,
        read_seconds=300,
    )
    if code != 200:
        return resp, code
    payload = resp.get_json()
    upstream = payload.get("upstream") if isinstance(payload, dict) else {}
    checklist = upstream.get("checklist") if isinstance(upstream, dict) else []
    return jsonify(
        {
            "ok": True,
            "message": f"已生成 {len(checklist or [])} 条审核点",
            "organizationId": organization_id,
            "collection": collection,
            "checklist": checklist or [],
            "totalPoints": upstream.get("total_points") if isinstance(upstream, dict) else len(checklist or []),
            "upstream": upstream,
        }
    )


@company_bp.post("/api/company/training/checklist/train")
@company_admin_write_required
def api_company_training_checklist_train():
    data = request.get_json(force=True) or {}
    explicit_org = str(data.get("organizationId") or data.get("organization_id") or "").strip()
    try:
        organization_id, collection = resolve_organization_context(
            explicit_organization_id=explicit_org or None
        )
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 403
    from .aicheckword_core_proxy import parse_checklist_json, upstream_form_post

    try:
        checklist = parse_checklist_json(data.get("checklist") or data.get("checklistJson"))
    except (ValueError, json.JSONDecodeError) as exc:
        return jsonify({"message": f"checklist 格式错误：{exc}"}), 400
    if not checklist:
        return jsonify({"message": "checklist 不能为空"}), 400
    resp, code = upstream_form_post(
        "checklist/train",
        data={
            "collection": collection,
            "checklist_json": json.dumps(checklist, ensure_ascii=False),
        },
        organization_id=organization_id or None,
        read_seconds=600,
    )
    if code != 200:
        return resp, code
    payload = resp.get_json()
    upstream = payload.get("upstream") if isinstance(payload, dict) else {}
    chunks = upstream.get("chunks_added") if isinstance(upstream, dict) else 0
    return jsonify(
        {
            "ok": True,
            "message": f"审核点已入库（新增 {chunks or 0} 块）",
            "organizationId": organization_id,
            "collection": collection,
            "upstream": upstream,
        }
    )


@company_bp.post("/api/company/training/knowledge/clear")
@company_admin_write_required
def api_company_training_knowledge_clear():
    data = request.get_json(force=True) or {}
    explicit_org = str(data.get("organizationId") or data.get("organization_id") or "").strip()
    try:
        organization_id, collection = resolve_organization_context(
            explicit_organization_id=explicit_org or None
        )
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 403
    from .aicheckword_core_proxy import upstream_json_post

    return upstream_json_post(
        "knowledge/clear",
        body={"collection": collection},
        organization_id=organization_id or None,
        read_seconds=120,
    )


@company_bp.post("/api/company/training/directory")
@company_admin_write_required
def api_company_training_directory():
    """服务器本地目录训练（须 aicheckword 进程可访问该路径）。"""
    data = request.get_json(force=True) or {}
    dir_path = str(data.get("dirPath") or data.get("dir_path") or "").strip()
    if not dir_path:
        return jsonify({"message": "缺少 dirPath"}), 400
    category = str(data.get("category") or "regulation").strip() or "regulation"
    explicit_org = str(data.get("organizationId") or data.get("organization_id") or "").strip()
    try:
        organization_id, collection = resolve_organization_context(
            explicit_organization_id=explicit_org or None
        )
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 403
    from .aicheckword_core_proxy import upstream_form_post

    resp, code = upstream_form_post(
        "train/directory",
        data={"collection": collection, "category": category, "dir_path": dir_path},
        organization_id=organization_id or None,
        read_seconds=3600,
    )
    if code != 200:
        return resp, code
    payload = resp.get_json()
    return jsonify(
        {
            "ok": True,
            "message": "目录训练请求已完成",
            "organizationId": organization_id,
            "collection": collection,
            "upstream": payload.get("upstream") if isinstance(payload, dict) else payload,
        }
    )


@company_bp.post("/api/company/training/upload")
@company_admin_write_required
def api_company_training_upload():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"message": "请先选择要训练的文件"}), 400
    category = str(request.form.get("category") or "regulation").strip() or "regulation"
    explicit_org = str(request.form.get("organizationId") or request.form.get("organization_id") or "").strip()
    organization_id, collection = resolve_organization_context(explicit_organization_id=explicit_org)
    base = integration_api_base()
    if not base:
        return jsonify({"message": "未配置 AICHECKWORD_DRAFT_API_BASE / QUIZ_API_BASE_URL"}), 503
    upstream_url = f"{base.rstrip('/')}/train/upload"
    form_files: list[tuple[str, tuple[str, bytes, str]]] = []
    raw_items: list[tuple[str, bytes]] = []
    for f in files:
        if f is None:
            continue
        raw = f.read()
        if raw:
            raw_items.append((str(f.filename or "upload.bin"), raw))
    from .archive_expand import expand_upload_blobs

    expanded = expand_upload_blobs(raw_items)
    if not expanded:
        return jsonify({"message": "无有效训练文件（支持单文件或 zip/tar 压缩包）"}), 400
    for disp_name, raw in expanded:
        form_files.append(("files", (disp_name, raw, "application/octet-stream")))
    try:
        resp = requests.post(
            upstream_url,
            data={"collection": collection, "category": category},
            files=form_files,
            headers=upstream_headers(for_multipart=True, organization_id=organization_id),
            timeout=integration_requests_timeout(read_seconds=600),
        )
    except requests.RequestException as exc:
        return jsonify({"message": f"上游训练请求失败：{exc}"}), 502
    try:
        body = resp.json()
    except Exception:
        body = {"raw": (resp.text or "")[:4000]}
    if resp.status_code >= 400:
        return jsonify({"message": f"上游训练失败（HTTP {resp.status_code}）", "upstream": body}), resp.status_code
    return jsonify(
        {
            "message": "训练请求已完成",
            "organizationId": organization_id,
            "collection": collection,
            "upstream": body,
        }
    )


@company_bp.post("/api/company/training/project-cases/create")
@company_admin_write_required
def api_company_training_project_case_create():
    data = request.get_json(force=True) or {}
    explicit_org = str(data.get("organizationId") or data.get("organization_id") or "").strip()
    organization_id, collection = resolve_organization_context(explicit_organization_id=explicit_org)
    case_name = str(data.get("caseName") or data.get("case_name") or "").strip()
    if not case_name:
        return jsonify({"message": "caseName 不能为空"}), 400
    base = integration_api_base()
    if not base:
        return jsonify({"message": "未配置 AICHECKWORD_DRAFT_API_BASE / QUIZ_API_BASE_URL"}), 503
    try:
        resp = requests.post(
            f"{base.rstrip('/')}/train/project-cases/create",
            data={
                "collection": collection,
                "case_name": case_name,
                "case_name_en": str(data.get("caseNameEn") or data.get("case_name_en") or "").strip(),
                "product_name": str(data.get("productName") or data.get("product_name") or "").strip(),
                "product_name_en": str(data.get("productNameEn") or data.get("product_name_en") or "").strip(),
                "registration_country": str(data.get("registrationCountry") or data.get("registration_country") or "").strip(),
                "registration_country_en": str(
                    data.get("registrationCountryEn") or data.get("registration_country_en") or ""
                ).strip(),
                "registration_type": str(data.get("registrationType") or data.get("registration_type") or "").strip(),
                "registration_component": str(data.get("registrationComponent") or data.get("registration_component") or "").strip(),
                "project_form": str(data.get("projectForm") or data.get("project_form") or "").strip(),
                "scope_of_application": str(data.get("scopeOfApplication") or data.get("scope_of_application") or "").strip(),
                "document_language": str(data.get("documentLanguage") or data.get("document_language") or "zh").strip() or "zh",
                "project_key": str(data.get("projectKey") or data.get("project_key") or "").strip(),
            },
            headers=upstream_headers(for_multipart=True, organization_id=organization_id),
            timeout=integration_requests_timeout(read_seconds=60),
        )
    except requests.RequestException as exc:
        return jsonify({"message": f"上游创建案例失败：{exc}"}), 502
    try:
        body = resp.json()
    except Exception:
        body = {"raw": (resp.text or "")[:4000]}
    if resp.status_code >= 400:
        return jsonify({"message": f"上游创建案例失败（HTTP {resp.status_code}）", "upstream": body}), resp.status_code
    return jsonify(
        {
            "message": "项目案例已创建",
            "organizationId": organization_id,
            "collection": collection,
            "upstream": body,
        }
    )


@company_bp.post("/api/company/training/project-cases/upload")
@company_admin_write_required
def api_company_training_project_case_upload():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"message": "请先选择要训练的文件"}), 400
    case_id_raw = str(request.form.get("caseId") or request.form.get("case_id") or "").strip()
    if not case_id_raw:
        return jsonify({"message": "缺少 caseId"}), 400
    explicit_org = str(request.form.get("organizationId") or request.form.get("organization_id") or "").strip()
    organization_id, collection = resolve_organization_context(explicit_organization_id=explicit_org)
    base = integration_api_base()
    if not base:
        return jsonify({"message": "未配置 AICHECKWORD_DRAFT_API_BASE / QUIZ_API_BASE_URL"}), 503
    form_files: list[tuple[str, tuple[str, bytes, str]]] = []
    for f in files:
        if f is None:
            continue
        raw = f.read()
        if not raw:
            continue
        form_files.append(
            (
                "files",
                (
                    str(f.filename or "upload.bin"),
                    raw,
                    str(getattr(f, "mimetype", None) or "application/octet-stream"),
                ),
            )
        )
    if not form_files:
        return jsonify({"message": "文件为空或读取失败"}), 400
    try:
        resp = requests.post(
            f"{base.rstrip('/')}/train/project-cases/upload",
            data={"collection": collection, "case_id": case_id_raw},
            files=form_files,
            headers=upstream_headers(for_multipart=True, organization_id=organization_id),
            timeout=integration_requests_timeout(read_seconds=900),
        )
    except requests.RequestException as exc:
        return jsonify({"message": f"上游案例训练失败：{exc}"}), 502
    try:
        body = resp.json()
    except Exception:
        body = {"raw": (resp.text or "")[:4000]}
    if resp.status_code >= 400:
        return jsonify({"message": f"上游案例训练失败（HTTP {resp.status_code}）", "upstream": body}), resp.status_code
    return jsonify(
        {
            "message": "案例文档训练完成",
            "organizationId": organization_id,
            "collection": collection,
            "caseId": case_id_raw,
            "upstream": body,
        }
    )


@company_bp.post("/api/company/projects/sync-legacy")
@company_admin_write_required
def api_company_projects_sync_legacy():
    n = _sync_unlinked_page1_one_to_one()
    return jsonify(
        {
            "message": f"已同步 {n} 个页面1 项目到公司总览（各建一条公司项目记录，可在「关联」中合并为多对一）",
            "synced": n,
        }
    )


@company_bp.get("/api/company/projects")
@company_registry_api_required
def api_company_projects_list():
    from .routes import _project_meta_map

    synced = 0
    sync_arg = (request.args.get("syncLegacy") or "").strip().lower()
    force_sync = sync_arg in ("1", "true", "yes", "on")
    scope_org_ids, scope_err = _requested_company_scope_org_ids()
    if scope_err:
        return jsonify({"message": scope_err}), 403
    if force_sync:
        synced = _sync_unlinked_page1_one_to_one(scope_org_ids=scope_org_ids)

    from .project_registry_sync import sync_all_linked_page1_from_company

    pushed = sync_all_linked_page1_from_company()
    if pushed:
        db.session.commit()

    _project_meta_map(auto_create_from_uploads=True)
    q = CompanyProject.query
    if is_multi_tenant_enabled():
        if scope_org_ids:
            q = q.filter(CompanyProject.organization_id.in_(scope_org_ids))
        else:
            from sqlalchemy import false as sql_false

            q = q.filter(sql_false())
    starred_only = (request.args.get("starredOnly") or "").strip().lower()
    if starred_only in ("1", "true", "yes", "on"):
        q = q.filter(CompanyProject.is_starred.is_(True))
    rows = q.order_by(
        CompanyProject.is_starred.desc(),
        CompanyProject.priority.desc(),
        CompanyProject.name.asc(),
    ).all()
    from .authz import company_project_in_scope

    rows = [cp for cp in rows if company_project_in_scope(cp)]
    org_ids = {
        str(getattr(cp, "organization_id", "") or "").strip()
        for cp in rows
        if str(getattr(cp, "organization_id", "") or "").strip()
    }
    org_names = _organization_name_map(org_ids)
    projects = [_serialize_company_project(cp, org_names=org_names) for cp in rows]
    return jsonify({"projects": projects, "synced": synced, "total": len(projects)})


@company_bp.get("/api/company/page1-project-candidates")
@company_registry_api_required
def api_page1_project_candidates():
    """供关联弹窗：全部页面1 项目及当前绑定的公司总览 id。"""
    from .routes import _project_meta_map

    _project_meta_map(auto_create_from_uploads=True)
    q = Project.query
    scope_org_ids, scope_err = _requested_company_scope_org_ids()
    if scope_err:
        return jsonify({"message": scope_err}), 403
    if is_multi_tenant_enabled():
        if scope_org_ids:
            q = q.filter(Project.organization_id.in_(scope_org_ids))
        else:
            from sqlalchemy import false as sql_false

            q = q.filter(sql_false())
    rows = q.order_by(Project.name.asc()).all()
    return jsonify(
        [
            {
                **_serialize_page1_link(p),
                "companyProjectId": getattr(p, "company_project_id", None),
            }
            for p in rows
        ]
    )


@company_bp.get("/api/company/projects/<company_project_id>/page1-links")
@company_registry_api_required
def api_company_page1_links_get(company_project_id: str):
    cp = CompanyProject.query.get(company_project_id)
    if not cp:
        return jsonify({"message": "未找到该公司总览项目"}), 404
    if not _company_project_in_active_org(cp):
        return jsonify({"message": "未找到该公司总览项目"}), 404
    linked = _linked_page1_rows(company_project_id)
    return jsonify(
        {
            "companyProjectId": company_project_id,
            "linkedPage1Projects": [_serialize_page1_link(p) for p in linked],
        }
    )


@company_bp.put("/api/company/projects/<company_project_id>/page1-links")
@company_admin_write_required
def api_company_page1_links_put(company_project_id: str):
    cp0 = CompanyProject.query.get(company_project_id)
    if cp0 and not _company_project_in_active_org(cp0):
        return jsonify({"message": "未找到该公司总览项目"}), 404
    data = request.get_json(force=True) or {}
    ids = _parse_page1_project_ids(data)
    result = _set_page1_links(company_project_id, ids)
    if result.get("code") == 404:
        return jsonify({"message": result["error"]}), 404
    cp = CompanyProject.query.get(company_project_id)
    return jsonify(
        {
            "message": f"已关联 {result['linked']} 个页面1 项目，页面0 登记信息已同步到页面1",
            "project": _serialize_company_project(cp) if cp else None,
        }
    )


@company_bp.post("/api/company/projects")
@company_admin_write_required
def api_company_projects_create():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"message": "项目名称不能为空"}), 400
    row = CompanyProject(
        organization_id=(_current_company_scope_org_id() or None),
        name=name,
        created_by_user_id=session.get("user_id"),
    )
    if "organizationId" in data or "organization_id" in data:
        raw = (
            data.get("organizationId")
            if "organizationId" in data
            else data.get("organization_id")
        )
        oid, oid_err = _resolve_assignable_organization_id(raw)
        if oid_err:
            return jsonify({"message": oid_err}), 400
        row.organization_id = oid
    field_err = _apply_company_fields(row, data)
    if field_err:
        return jsonify({"message": field_err}), 400
    db.session.add(row)
    db.session.flush()
    from .authz import company_project_in_scope

    if not company_project_in_scope(row):
        db.session.rollback()
        return jsonify({"message": "无权登记该注册国家的项目"}), 403
    page1_ids = _parse_page1_project_ids(data)
    if page1_ids:
        _set_page1_links(row.id, page1_ids)
        row = CompanyProject.query.get(row.id)
    _sync_company_to_page1_after_update(row)
    db.session.commit()
    return jsonify({"message": "已保存", "project": _serialize_company_project(row)})


@company_bp.patch("/api/company/projects/<company_project_id>")
@company_admin_write_required
def api_company_projects_patch(company_project_id: str):
    row = CompanyProject.query.get(company_project_id)
    if not row:
        return jsonify({"message": "未找到该项目"}), 404
    if not _company_project_in_active_org(row):
        return jsonify({"message": "未找到该项目"}), 404
    from .authz import company_project_in_scope

    if not company_project_in_scope(row):
        return jsonify({"message": "无权操作该国家的项目"}), 403
    data = request.get_json(force=True) or {}
    field_err = _apply_company_fields(row, data)
    if field_err:
        return jsonify({"message": field_err}), 400
    db.session.add(row)
    registry_keys = {
        k
        for k in data
        if k not in ("isStarred", "starred", "page1ProjectIds", "linkedProjectIds")
    }
    if registry_keys:
        _sync_company_to_page1_after_update(row)
    db.session.commit()
    if "page1ProjectIds" in data or "linkedProjectIds" in data:
        _set_page1_links(company_project_id, _parse_page1_project_ids(data))
        row = CompanyProject.query.get(company_project_id)
        if row:
            _sync_company_to_page1_after_update(row)
            db.session.commit()
    return jsonify({"message": "已更新", "project": _serialize_company_project(row)})


@company_bp.post("/api/company/projects/batch")
@company_admin_write_required
def api_company_projects_batch_update():
    data = request.get_json(force=True) or {}
    ids = _parse_project_ids(data)
    if not ids:
        return jsonify({"message": "请勾选要编辑的项目"}), 400
    patch: dict[str, Any] = {}
    if data.get("priority") is not None and str(data.get("priority")).strip() != "":
        patch["priority"] = data.get("priority")
    if (data.get("status") or "").strip():
        patch["status"] = data.get("status")
        from .authz import is_page13_super_admin
        from .project_teams import PROJECT_STATUS_LOCKED_MSG, company_project_has_page1_upload_tasks

        if not is_page13_super_admin():
            new_st = (patch["status"] or "").strip().lower()
            for cid in ids:
                row = CompanyProject.query.get(cid)
                if not row:
                    continue
                old = (row.status or CompanyProject.STATUS_ACTIVE).strip().lower()
                if old == new_st:
                    continue
                if company_project_has_page1_upload_tasks(cid):
                    return jsonify({"message": PROJECT_STATUS_LOCKED_MSG}), 403
    if "assignedTeamId" in data:
        tid = data.get("assignedTeamId")
        patch["assignedTeamId"] = None if tid in (None, "", "__none__") else tid
        from .authz import is_page13_super_admin
        from .project_teams import ASSIGNED_TEAM_LOCKED_MSG, company_project_has_page1_upload_tasks

        if not is_page13_super_admin():
            new_tid = patch["assignedTeamId"]
            for cid in ids:
                row = CompanyProject.query.get(cid)
                if not row:
                    continue
                old = (getattr(row, "assigned_team_id", None) or "").strip() or None
                if old == ((new_tid or "").strip() or None):
                    continue
                if company_project_has_page1_upload_tasks(cid):
                    return jsonify({"message": ASSIGNED_TEAM_LOCKED_MSG}), 403
    if "progressDescription" in data:
        patch["progressDescription"] = data.get("progressDescription")
    if "productType" in data:
        patch["productType"] = (data.get("productType") or "").strip() or None
    if "registrationOwner" in data:
        patch["registrationOwner"] = (data.get("registrationOwner") or "").strip() or None
    if "isStarred" in data:
        patch["isStarred"] = bool(data.get("isStarred"))
    if "organizationId" in data or "organization_id" in data:
        raw = (
            data.get("organizationId")
            if "organizationId" in data
            else data.get("organization_id")
        )
        oid, oid_err = _resolve_assignable_organization_id(raw)
        if oid_err:
            return jsonify({"message": oid_err}), 400
        patch["organizationId"] = oid
        from .authz import is_page13_super_admin
        from .project_teams import (
            ORGANIZATION_ID_LOCKED_MSG,
            company_project_has_page1_upload_tasks,
        )

        if not is_page13_super_admin():
            for cid in ids:
                row = CompanyProject.query.get(cid)
                if not row:
                    continue
                old = str(getattr(row, "organization_id", "") or "").strip() or None
                if old == oid:
                    continue
                if company_project_has_page1_upload_tasks(cid):
                    return jsonify({"message": ORGANIZATION_ID_LOCKED_MSG}), 403
    if not patch:
        return jsonify({"message": "请至少选择一项要修改的字段"}), 400
    from .authz import company_project_in_scope

    updated = 0
    for cid in ids:
        row = CompanyProject.query.get(cid)
        if (not row) or (not _company_project_in_active_org(row)) or (not company_project_in_scope(row)):
            continue
        field_err = _apply_company_fields(row, patch)
        if field_err:
            return jsonify({"message": field_err}), 400
        db.session.add(row)
        _sync_company_to_page1_after_update(row)
        updated += 1
    if updated:
        db.session.commit()
    return jsonify({"message": f"已更新 {updated} 个项目", "updated": updated})


@company_bp.delete("/api/company/projects/<company_project_id>")
@company_admin_write_required
def api_company_project_remove_from_registry(company_project_id: str):
    cp = CompanyProject.query.get(company_project_id)
    if cp and not _company_project_in_active_org(cp):
        return jsonify({"message": "未找到该项目"}), 404
    n = _delete_company_projects([company_project_id])
    return jsonify(
        {
            "message": "已从公司总览移除；关联的页面1 项目与任务均保留，可再次同步或重新关联",
            "removed": n,
        }
    )


@company_bp.post("/api/company/projects/remove-from-registry")
@company_admin_write_required
def api_company_projects_batch_remove():
    data = request.get_json(force=True) or {}
    ids = _parse_project_ids(data)
    if not ids:
        return jsonify({"message": "请勾选要移出的项目"}), 400
    scoped_ids: list[str] = []
    for cid in ids:
        cp = CompanyProject.query.get(cid)
        if cp and _company_project_in_active_org(cp):
            scoped_ids.append(cid)
    n = _delete_company_projects(scoped_ids)
    return jsonify(
        {
            "message": f"已从公司总览移除 {n} 条记录；页面1/2/3 不受影响",
            "removed": n,
        }
    )


@company_bp.get("/api/company/projects/summary")
@company_registry_api_required
def api_company_projects_summary():
    from .routes import _summary_payload

    payload = _summary_payload()
    keys: set[str] = set()
    q = CompanyProject.query
    scope_org_id = _current_company_scope_org_id()
    if is_multi_tenant_enabled() and scope_org_id:
        q = q.filter(CompanyProject.organization_id == scope_org_id)
    for cp in q.all():
        for p in _linked_page1_rows(cp.id):
            keys.add(
                project_display_label(
                    p.name, p.registered_country, p.registered_category
                )
            )
    if keys:
        payload["byProject"] = [
            x for x in payload.get("byProject", []) if x.get("label") in keys
        ]
        payload["detail"] = [
            x for x in payload.get("detail", []) if x.get("projectName") in keys
        ]
    return jsonify(payload)


@company_bp.get("/api/teams")
@company_registry_api_required
def api_teams_list():
    """项目组字典列表（页面0 维护 / 页面1 下拉选用）。"""
    from .project_teams import serialize_team_item

    rows = ProjectTeam.query.order_by(
        ProjectTeam.sort_order.asc(), ProjectTeam.name.asc()
    ).all()
    return jsonify([serialize_team_item(t) for t in rows])


@company_bp.post("/api/teams")
@super_admin_required
def api_teams_create():
    from .project_teams import normalize_team_dingtalk_webhook_for_storage

    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"message": "组名不能为空"}), 400
    if ProjectTeam.query.filter_by(name=name).first():
        return jsonify({"message": "组名已存在"}), 409
    t = ProjectTeam(
        name=name,
        sort_order=int(data.get("sortOrder") or 0),
        is_active=bool(data.get("isActive", True)),
        dingtalk_webhook=normalize_team_dingtalk_webhook_for_storage(
            data.get("dingtalkWebhook")
        ),
        dingtalk_secret=(data.get("dingtalkSecret") or "").strip() or None,
    )
    db.session.add(t)
    db.session.flush()
    org_ids = data.get("organizationIds")
    if org_ids is None and data.get("organizationId"):
        org_ids = [data.get("organizationId")]
    if org_ids is not None:
        from .team_organizations import set_team_organization_ids

        set_team_organization_ids(t.id, org_ids if isinstance(org_ids, list) else [])
    db.session.commit()
    from .project_teams import serialize_team_item

    return jsonify({"message": "已创建", "team": serialize_team_item(t)})


@company_bp.patch("/api/teams/<team_id>")
@super_admin_required
def api_teams_patch(team_id: str):
    from .project_teams import serialize_team_item, update_team_name

    t = ProjectTeam.query.get(team_id)
    if not t:
        return jsonify({"message": "未找到该组"}), 404
    data = request.get_json(force=True) or {}
    if "name" in data:
        t, err = update_team_name(team_id, data.get("name"))
        if err:
            return jsonify({"message": err}), 400 if "未找到" not in err else 404
    if "sortOrder" in data:
        try:
            t.sort_order = int(data.get("sortOrder"))
        except Exception:
            pass
    if "isActive" in data:
        t.is_active = bool(data.get("isActive"))
    if "dingtalkWebhook" in data:
        from .project_teams import normalize_team_dingtalk_webhook_for_storage

        t.dingtalk_webhook = normalize_team_dingtalk_webhook_for_storage(
            data.get("dingtalkWebhook")
        )
    if "dingtalkSecret" in data:
        stripped = (data.get("dingtalkSecret") or "").strip()
        if stripped:
            t.dingtalk_secret = stripped
    if "organizationIds" in data or "organizationId" in data:
        from .team_organizations import set_team_organization_ids

        raw = data.get("organizationIds")
        if raw is None and "organizationId" in data:
            oid = str(data.get("organizationId") or "").strip()
            raw = [oid] if oid else []
        if not isinstance(raw, list):
            raw = []
        set_team_organization_ids(team_id, raw)
    db.session.add(t)
    db.session.commit()
    return jsonify({"message": "已更新", "team": serialize_team_item(t)})


@company_bp.delete("/api/teams/<team_id>")
@super_admin_required
def api_teams_delete(team_id: str):
    from .project_teams import delete_team

    cascade = request.args.get("cascade") in ("1", "true", "yes")
    if not cascade:
        data = request.get_json(silent=True) or {}
        cascade = bool(data.get("cascade"))
    ok, err = delete_team(team_id, cascade=cascade)
    if not ok:
        return jsonify({"message": err or "无法删除"}), 409 if err else 404
    db.session.commit()
    return jsonify({"message": "已删除"})


@company_bp.get("/api/users/<user_id>/teams")
@company_registry_api_required
def api_user_teams_get(user_id: str):
    ids = [
        m.team_id
        for m in UserTeamMembership.query.filter_by(user_id=user_id).all()
    ]
    return jsonify({"teamIds": ids})


@company_bp.put("/api/users/<user_id>/teams")
@company_admin_write_required
def api_user_teams_put(user_id: str):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "用户不存在"}), 404
    data = request.get_json(force=True) or {}
    raw_ids = data.get("teamIds")
    if not isinstance(raw_ids, list):
        return jsonify({"message": "teamIds 须为数组"}), 400
    from .user_access import normalize_user_team_ids, set_user_team_memberships

    raw_list = [str(x).strip() for x in raw_ids if str(x).strip()]
    if len(raw_list) > 1:
        return jsonify({"message": "每个账号最多绑定一个所属项目组"}), 400
    team_ids = normalize_user_team_ids(raw_list)
    set_user_team_memberships(user_id, team_ids)
    db.session.commit()
    if session.get("user_id") == user_id:
        session["team_ids"] = list(team_ids)
    return jsonify({"message": "已更新", "teamIds": list(team_ids)})


@company_bp.get("/api/company/registered-countries")
@company_registry_api_required
def api_company_registered_countries_list():
    """页面0：注册国家字典列表（含停用项，供维护）。"""
    from .registered_countries import list_registered_country_items

    return jsonify({"countries": list_registered_country_items(active_only=False)})


@company_bp.post("/api/company/registered-countries")
@super_admin_required
def api_company_registered_countries_create():
    """页面4：新增注册国家字典项。"""
    from .registered_countries import add_registered_country_to_dict, normalize_registered_country

    data = request.get_json(force=True) or {}
    name = normalize_registered_country(data.get("name"))
    if not name:
        return jsonify({"message": "国家名称不能为空"}), 400
    try:
        row = add_registered_country_to_dict(name)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": str(e) or "保存失败"}), 400
    return jsonify(
        {
            "message": "已添加",
            "country": {
                "id": row.id,
                "name": row.name,
                "isActive": bool(row.is_active),
            },
        }
    )


@company_bp.patch("/api/company/registered-countries/<country_id>")
@super_admin_required
def api_company_registered_countries_patch(country_id: str):
    from .registered_countries import (
        list_registered_country_items,
        update_registered_country_name,
    )

    data = request.get_json(force=True) or {}
    row, err = update_registered_country_name(country_id, data.get("name"))
    if err:
        code = 404 if "未找到" in err else 400
        return jsonify({"message": err}), code
    db.session.commit()
    items = list_registered_country_items(active_only=False)
    item = next((x for x in items if x["id"] == country_id), None)
    return jsonify({"message": "已更新", "country": item})


@company_bp.delete("/api/company/registered-countries/<country_id>")
@super_admin_required
def api_company_registered_countries_delete(country_id: str):
    """页面4：删除字典项（超级管理员可级联清理引用）。"""
    from .registered_countries import delete_registered_country

    cascade = request.args.get("cascade") in ("1", "true", "yes")
    if not cascade:
        data = request.get_json(silent=True) or {}
        cascade = bool(data.get("cascade"))
    ok, err = delete_registered_country(country_id, cascade=cascade)
    if not ok:
        return jsonify({"message": err or "无法删除"}), 409 if err else 404
    db.session.commit()
    return jsonify({"message": "已删除"})


@company_bp.get("/api/organizations")
@super_admin_required
def api_organizations_list():
    rows = (
        Organization.query.order_by(
            Organization.is_default.desc(),
            Organization.created_at.asc(),
        ).all()
    )
    return jsonify({"organizations": [_serialize_organization(o) for o in rows]})


@company_bp.post("/api/organizations")
@super_admin_required
def api_organizations_create():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"message": "公司名称不能为空"}), 400
    slug = _normalize_org_slug(data.get("slug")) or _slug_from_name(name)
    collection = _normalize_collection(data.get("knowledgeCollection")) or slug
    if not collection:
        return jsonify({"message": "知识库 collection 不能为空"}), 400
    if Organization.query.filter_by(name=name).first():
        return jsonify({"message": "公司名称已存在"}), 409
    if Organization.query.filter_by(slug=slug).first():
        return jsonify({"message": "公司 slug 已存在"}), 409
    if Organization.query.filter_by(knowledge_collection=collection).first():
        return jsonify({"message": "知识库 collection 已存在"}), 409
    row = Organization(
        name=name,
        slug=slug,
        knowledge_collection=collection,
        is_active=bool(data.get("isActive", True)),
        is_default=bool(data.get("isDefault", False)),
    )
    if row.is_default:
        Organization.query.update({"is_default": False}, synchronize_session=False)
    db.session.add(row)
    db.session.commit()
    _sync_org_to_aicheckword(org=row, delete=False)
    return jsonify({"message": "公司已创建", "organization": _serialize_organization(row)})


@company_bp.patch("/api/organizations/<org_id>")
@super_admin_required
def api_organizations_patch(org_id: str):
    row = Organization.query.get(org_id)
    if not row:
        return jsonify({"message": "公司不存在"}), 404
    data = request.get_json(force=True) or {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"message": "公司名称不能为空"}), 400
        exists = Organization.query.filter(
            Organization.id != org_id,
            Organization.name == name,
        ).first()
        if exists:
            return jsonify({"message": "公司名称已存在"}), 409
        row.name = name
    if "slug" in data:
        slug = _normalize_org_slug(data.get("slug"))
        if not slug:
            return jsonify({"message": "slug 不能为空"}), 400
        exists = Organization.query.filter(
            Organization.id != org_id,
            Organization.slug == slug,
        ).first()
        if exists:
            return jsonify({"message": "slug 已存在"}), 409
        row.slug = slug
    if "knowledgeCollection" in data:
        col = _normalize_collection(data.get("knowledgeCollection"))
        if not col:
            return jsonify({"message": "knowledgeCollection 不能为空"}), 400
        exists = Organization.query.filter(
            Organization.id != org_id,
            Organization.knowledge_collection == col,
        ).first()
        if exists:
            return jsonify({"message": "knowledgeCollection 已存在"}), 409
        row.knowledge_collection = col
    if "isActive" in data:
        row.is_active = bool(data.get("isActive"))
    if "isDefault" in data:
        next_default = bool(data.get("isDefault"))
        if next_default:
            Organization.query.update({"is_default": False}, synchronize_session=False)
            row.is_default = True
        elif row.is_default and not next_default:
            others = Organization.query.filter(Organization.id != org_id).count()
            if others <= 0:
                return jsonify({"message": "至少保留一个默认公司"}), 400
            row.is_default = False
    db.session.add(row)
    db.session.commit()
    _sync_org_to_aicheckword(org=row, delete=False)
    return jsonify({"message": "公司已更新", "organization": _serialize_organization(row)})


@company_bp.delete("/api/organizations/<org_id>")
@super_admin_required
def api_organizations_delete(org_id: str):
    row = Organization.query.get(org_id)
    if not row:
        return jsonify({"message": "公司不存在"}), 404
    if bool(getattr(row, "is_default", False)):
        return jsonify({"message": "默认公司不可删除"}), 409
    reason = _organization_delete_block_reason(org_id)
    if reason:
        return jsonify({"message": reason}), 409
    row_copy = row
    db.session.delete(row)
    db.session.commit()
    _sync_org_to_aicheckword(org=row_copy, delete=True)
    return jsonify({"message": "公司已删除"})
