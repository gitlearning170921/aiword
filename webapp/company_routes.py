# -*- coding: utf-8 -*-
"""公司级项目总览：独立 company_projects 表，与页面1 projects 一对多关联。"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, render_template, request, session
from sqlalchemy import or_

from . import db
from .authz import (
    company_admin_write_required,
    company_registry_api_required,
    company_registry_enabled,
    company_registry_page_required,
    is_company_admin,
    parse_optional_date,
    project_display_label,
    super_admin_required,
    user_country_scopes,
)
from .models import (
    CompanyProject,
    Project,
    ProjectTeam,
    REGISTRATION_SCOPE_COMPANY,
    REGISTRATION_SCOPE_LEGACY,
    User,
    UserTeamMembership,
    now_local,
)

company_bp = Blueprint("company", __name__)


def _team_name_map() -> dict[str, str]:
    return {t.id: t.name for t in ProjectTeam.query.all()}


def _migrate_scope_company_to_company_projects() -> int:
    """历史数据：registration_scope=company 的页面1 行迁入 company_projects 并改回 legacy。"""
    rows = Project.query.filter(Project.registration_scope == REGISTRATION_SCOPE_COMPANY).all()
    n = 0
    for p in rows:
        if (getattr(p, "company_project_id", None) or "").strip():
            p.registration_scope = REGISTRATION_SCOPE_LEGACY
            db.session.add(p)
            continue
        cp = CompanyProject(
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


def _sync_unlinked_page1_one_to_one() -> int:
    """为尚未关联公司总览的页面1 项目各建一条公司项目（初始一对一，可在页面0 改绑为多对一）。"""
    _migrate_scope_company_to_company_projects()
    rows = Project.query.filter(
        or_(
            Project.company_project_id.is_(None),
            Project.company_project_id == "",
        )
    ).all()
    n = 0
    for p in rows:
        cp = CompanyProject(
            name=p.name,
            registered_country=getattr(p, "registered_country", None),
            registered_category=getattr(p, "registered_category", None),
            product_type=getattr(p, "product_type", None),
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
    return None


def _sync_company_to_page1_after_update(cp: CompanyProject) -> None:
    from .project_registry_sync import sync_company_to_page1

    sync_company_to_page1(cp.id, push_nulls=True)


def _serialize_company_project(cp: CompanyProject) -> dict:
    from .routes import _project_priority_label, _project_status_label

    from .project_teams import company_project_has_page1_upload_tasks

    teams = _team_name_map()
    tid = (getattr(cp, "assigned_team_id", None) or "").strip()
    linked = _linked_page1_rows(cp.id)
    team_locked = company_project_has_page1_upload_tasks(cp.id)
    return {
        "id": cp.id,
        "name": cp.name,
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
        scope_label = "全部（页面1·3 访问密码 · 超级管理员）"
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
    if force_sync or CompanyProject.query.count() == 0:
        synced = _sync_unlinked_page1_one_to_one()

    from .project_registry_sync import sync_all_linked_page1_from_company

    pushed = sync_all_linked_page1_from_company()
    if pushed:
        db.session.commit()

    _project_meta_map(auto_create_from_uploads=True)
    q = CompanyProject.query
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
    projects = [_serialize_company_project(cp) for cp in rows]
    return jsonify({"projects": projects, "synced": synced, "total": len(projects)})


@company_bp.get("/api/company/page1-project-candidates")
@company_registry_api_required
def api_page1_project_candidates():
    """供关联弹窗：全部页面1 项目及当前绑定的公司总览 id。"""
    from .routes import _project_meta_map

    _project_meta_map(auto_create_from_uploads=True)
    rows = Project.query.order_by(Project.name.asc()).all()
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
        name=name,
        created_by_user_id=session.get("user_id"),
    )
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
    if not patch:
        return jsonify({"message": "请至少选择一项要修改的字段"}), 400
    from .authz import company_project_in_scope

    updated = 0
    for cid in ids:
        row = CompanyProject.query.get(cid)
        if not row or not company_project_in_scope(row):
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
    n = _delete_company_projects(ids)
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
    for cp in CompanyProject.query.all():
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
        dingtalk_webhook=(data.get("dingtalkWebhook") or "").strip() or None,
        dingtalk_secret=(data.get("dingtalkSecret") or "").strip() or None,
    )
    db.session.add(t)
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
        t.dingtalk_webhook = (data.get("dingtalkWebhook") or "").strip() or None
    if "dingtalkSecret" in data:
        # 明确传空串表示清空，未传则保持原值。
        t.dingtalk_secret = (data.get("dingtalkSecret") or "").strip() or None
    db.session.add(t)
    db.session.commit()
    return jsonify({"message": "已更新", "team": serialize_team_item(t)})


@company_bp.delete("/api/teams/<team_id>")
@super_admin_required
def api_teams_delete(team_id: str):
    from .project_teams import delete_team

    ok, err = delete_team(team_id)
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
    new_ids = {str(x).strip() for x in raw_ids if str(x).strip()}
    UserTeamMembership.query.filter_by(user_id=user_id).delete()
    for tid in new_ids:
        if not ProjectTeam.query.get(tid):
            continue
        db.session.add(UserTeamMembership(user_id=user_id, team_id=tid))
    db.session.commit()
    if session.get("user_id") == user_id:
        session["team_ids"] = list(new_ids)
    return jsonify({"message": "已更新", "teamIds": list(new_ids)})


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
    """页面4：删除字典项（已有业务引用时不允许）。"""
    from .registered_countries import delete_registered_country

    ok, err = delete_registered_country(country_id)
    if not ok:
        return jsonify({"message": err or "无法删除"}), 409 if err else 404
    db.session.commit()
    return jsonify({"message": "已删除"})
