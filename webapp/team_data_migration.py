# -*- coding: utf-8 -*-
"""项目组默认数据迁移：确保历史数据可平滑切换到“互联网产品部”。"""
from __future__ import annotations

from . import db
from .authz import project_display_label
from .models import (
    CompanyProject,
    Project,
    ProjectTeam,
    UploadRecord,
    User,
    UserTeamMembership,
)

DEFAULT_TEAM_NAME = "互联网产品部"


def _backfill_upload_project_ids() -> int:
    from .models import GenerationSummary, ModuleCascadeReminder

    rows = Project.query.order_by(Project.updated_at.asc(), Project.id.asc()).all()
    key_to_pid: dict[str, str] = {}
    for p in rows:
        k = project_display_label(
            getattr(p, "name", None),
            getattr(p, "registered_country", None),
            getattr(p, "registered_category", None),
        )
        if k and k not in key_to_pid:
            key_to_pid[k] = p.id
    changed = 0
    for k, pid in key_to_pid.items():
        changed += UploadRecord.query.filter(
            UploadRecord.project_id.is_(None),
            UploadRecord.project_name == k,
        ).update({"project_id": pid}, synchronize_session=False)
        changed += ModuleCascadeReminder.query.filter(
            ModuleCascadeReminder.project_id.is_(None),
            ModuleCascadeReminder.project_name == k,
        ).update({"project_id": pid}, synchronize_session=False)
        try:
            changed += GenerationSummary.query.filter(
                GenerationSummary.project_id.is_(None),
                GenerationSummary.project_name == k,
            ).update({"project_id": pid}, synchronize_session=False)
        except Exception:
            pass
    return changed


def ensure_default_team_data() -> dict[str, int | str]:
    """幂等迁移：补默认组并回填项目/任务/用户归组。"""
    team = ProjectTeam.query.filter(ProjectTeam.name == DEFAULT_TEAM_NAME).first()
    created = 0
    if not team:
        team = ProjectTeam(name=DEFAULT_TEAM_NAME, sort_order=0, is_active=True)
        db.session.add(team)
        db.session.flush()
        created = 1
    if not bool(getattr(team, "is_active", True)):
        team.is_active = True
        db.session.add(team)

    # 不在库内写入全局 Webhook/Secret；发送时由 dingtalk_team 按项目组→全局回退，避免误展示体系机器人默认值。
    db.session.add(team)
    db.session.flush()

    default_team_id = team.id

    try:
        from .tenant_context import default_organization
        from .team_organizations import set_team_organization_ids

        dorg = default_organization()
        dorg_id = str(getattr(dorg, "id", "") or "").strip()
        if dorg_id:
            set_team_organization_ids(str(team.id), [dorg_id])
    except Exception:
        pass

    company_projects_updated = CompanyProject.query.filter(
        CompanyProject.assigned_team_id.is_(None)
    ).update({"assigned_team_id": default_team_id}, synchronize_session=False)
    projects_updated = Project.query.filter(
        Project.assigned_team_id.is_(None)
    ).update({"assigned_team_id": default_team_id}, synchronize_session=False)
    uploads_backfilled = _backfill_upload_project_ids()

    users_linked = 0
    from .user_access import user_eligible_for_team_membership

    for u in User.query.all():
        if not user_eligible_for_team_membership(u):
            continue
        exists = UserTeamMembership.query.filter_by(user_id=u.id).first()
        if exists:
            continue
        db.session.add(UserTeamMembership(user_id=u.id, team_id=default_team_id))
        users_linked += 1

    db.session.commit()
    return {
        "defaultTeamId": default_team_id,
        "defaultTeamCreated": created,
        "companyProjectsUpdated": int(company_projects_updated or 0),
        "projectsUpdated": int(projects_updated or 0),
        "uploadsBackfilled": int(uploads_backfilled or 0),
        "usersLinked": users_linked,
    }
