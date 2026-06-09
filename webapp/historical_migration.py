# -*- coding: utf-8 -*-
"""历史数据一次性迁移：空值补齐默认公司/项目组，完成后不再自动执行。"""
from __future__ import annotations

import re

from sqlalchemy import text

HISTORICAL_MIGRATION_KEY = "HISTORICAL_ORG_TEAM_MIGRATION_V1"
EXAM_ORG_BACKFILL_KEY = "EXAM_ORG_BACKFILL_V1"

_TEST_TEAM_NAME_RE = re.compile(
    r"^(exam_smoke_|regress_scope_|regress_test_|smoke_test_)",
    re.IGNORECASE,
)

_BACKFILL_TABLES = (
    "project_teams",
    "company_projects",
    "projects",
    "upload_records",
    "draft_generation_jobs",
    "audit_jobs",
    "translation_jobs",
    "exam_center_assignments",
    "exam_center_activities",
    "exam_attempts",
    "exam_bank_ingest_jobs",
    "exam_set_review_jobs",
)

_EXAM_BACKFILL_TABLES = (
    "exam_center_assignments",
    "exam_center_activities",
    "exam_attempts",
    "exam_bank_ingest_jobs",
    "exam_set_review_jobs",
)


def is_historical_migration_done() -> bool:
    from .models import AppConfig

    row = AppConfig.query.filter_by(config_key=HISTORICAL_MIGRATION_KEY).first()
    return bool(row and (row.config_value or "").strip() == "1")


def mark_historical_migration_done() -> None:
    from . import db
    from .app_settings import _upsert_config

    _upsert_config(HISTORICAL_MIGRATION_KEY, "1")
    db.session.commit()


def _database_already_backfilled(engine) -> bool:
    """升级场景：业务表已无空 organization_id，视为历史迁移已完成。"""
    try:
        with engine.connect() as conn:
            org_cnt = conn.execute(text("SELECT COUNT(*) FROM organizations")).scalar() or 0
            if org_cnt <= 0:
                return False
            for table_name in _BACKFILL_TABLES:
                try:
                    row = conn.execute(
                        text(
                            f"SELECT 1 FROM {table_name} "
                            "WHERE organization_id IS NULL OR organization_id = '' LIMIT 1"
                        )
                    ).fetchone()
                except Exception:
                    continue
                if row:
                    return False
            return True
    except Exception:
        return False


def ensure_historical_migration_gate(engine) -> bool:
    """返回是否仍应执行 seed/backfill（False=已跳过并标记完成）。"""
    if is_historical_migration_done():
        return False
    if _database_already_backfilled(engine):
        mark_historical_migration_done()
        return False
    return True


def run_team_data_migration_if_pending() -> None:
    """启动时调用：仅在未完成历史迁移时执行项目组/空 organization 补齐。"""
    if is_historical_migration_done():
        return
    from .team_data_migration import ensure_default_team_data

    ensure_default_team_data()
    mark_historical_migration_done()


def is_exam_org_backfill_done() -> bool:
    from .models import AppConfig

    row = AppConfig.query.filter_by(config_key=EXAM_ORG_BACKFILL_KEY).first()
    return bool(row and (row.config_value or "").strip() == "1")


def mark_exam_org_backfill_done() -> None:
    from . import db
    from .app_settings import _upsert_config

    _upsert_config(EXAM_ORG_BACKFILL_KEY, "1")
    db.session.commit()


def _is_test_project_team_name(name: str | None) -> bool:
    n = str(name or "").strip()
    if not n:
        return False
    return bool(_TEST_TEAM_NAME_RE.match(n))


def ensure_default_team_linked_to_default_org() -> None:
    """幂等：默认项目组「互联网产品部」绑定默认公司（含 M2M junction）。"""
    from . import db
    from .models import ProjectTeam
    from .team_data_migration import DEFAULT_TEAM_NAME, ensure_default_team_data
    from .team_organizations import set_team_organization_ids
    from .tenant_context import default_organization

    ensure_default_team_data()
    team = ProjectTeam.query.filter_by(name=DEFAULT_TEAM_NAME, is_active=True).first()
    if not team:
        return
    dorg = default_organization()
    dorg_id = str(getattr(dorg, "id", "") or "").strip()
    if not dorg_id:
        return
    set_team_organization_ids(str(team.id), [dorg_id])
    db.session.commit()


def cleanup_test_project_teams() -> dict[str, int]:
    """删除字典中的测试项目组（exam_smoke_* 等），账号/项目引用迁回「互联网产品部」。"""
    from . import db
    from .models import (
        CompanyProject,
        Project,
        ProjectTeam,
        ProjectTeamOrganization,
        UserTeamMembership,
    )
    from .team_data_migration import DEFAULT_TEAM_NAME, ensure_default_team_data

    ensure_default_team_data()
    default_team = ProjectTeam.query.filter_by(name=DEFAULT_TEAM_NAME, is_active=True).first()
    if not default_team:
        return {"teamsRemoved": 0, "membershipsMoved": 0, "projectsReassigned": 0}

    default_id = str(default_team.id or "").strip()
    teams_removed = 0
    memberships_moved = 0
    projects_reassigned = 0

    for team in ProjectTeam.query.order_by(ProjectTeam.created_at.asc()).all():
        tid = str(team.id or "").strip()
        if not tid or tid == default_id:
            continue
        if not _is_test_project_team_name(team.name):
            continue

        for m in UserTeamMembership.query.filter_by(team_id=tid).all():
            uid = str(m.user_id or "").strip()
            if uid and not UserTeamMembership.query.filter_by(user_id=uid, team_id=default_id).first():
                db.session.add(UserTeamMembership(user_id=uid, team_id=default_id))
                memberships_moved += 1
            db.session.delete(m)

        projects_reassigned += int(
            CompanyProject.query.filter_by(assigned_team_id=tid).update(
                {"assigned_team_id": default_id}, synchronize_session=False
            )
            or 0
        )
        projects_reassigned += int(
            Project.query.filter_by(assigned_team_id=tid).update(
                {"assigned_team_id": default_id}, synchronize_session=False
            )
            or 0
        )
        ProjectTeamOrganization.query.filter_by(team_id=tid).delete(synchronize_session=False)
        db.session.delete(team)
        teams_removed += 1

    if teams_removed or memberships_moved or projects_reassigned:
        db.session.commit()
    return {
        "teamsRemoved": teams_removed,
        "membershipsMoved": memberships_moved,
        "projectsReassigned": projects_reassigned,
    }


def repair_exam_activity_organization_to_default() -> int:
    """考试活动/作答/下发任务：空或无效 organization_id 回填默认公司；单公司部署下统一归入默认公司。"""
    from . import db
    from .app_settings import is_multi_tenant_enabled
    from .models import ExamCenterActivity, ExamCenterAssignment, ExamAttempt, Organization
    from .tenant_context import default_organization

    dorg = default_organization()
    if not dorg:
        return 0
    default_oid = str(dorg.id or "").strip()
    if not default_oid:
        return 0
    valid_oids = {str(o.id or "").strip() for o in Organization.query.all() if str(o.id or "").strip()}
    single_org_mode = (not is_multi_tenant_enabled()) or len(valid_oids) <= 1
    changed = 0

    def _needs_fix(raw: str | None) -> bool:
        oid = str(raw or "").strip()
        if not oid or oid not in valid_oids:
            return True
        return bool(single_org_mode and oid != default_oid)

    for row in ExamCenterActivity.query.all():
        if _needs_fix(getattr(row, "organization_id", None)):
            row.organization_id = default_oid
            changed += 1
    for row in ExamCenterAssignment.query.all():
        if _needs_fix(getattr(row, "organization_id", None)):
            row.organization_id = default_oid
            changed += 1
    for row in ExamAttempt.query.all():
        if _needs_fix(getattr(row, "organization_id", None)):
            row.organization_id = default_oid
            changed += 1
    if changed:
        db.session.commit()
    return changed


def repair_exam_null_organization_ids() -> None:
    """启动时幂等补齐考试表空 organization_id → 默认公司（南京鱼跃软件技术有限公司）。"""
    from . import db
    from .tenant_context import default_organization

    org = default_organization()
    if not org or not str(org.id or "").strip():
        return
    org_id = str(org.id).strip()
    try:
        with db.engine.connect() as conn:
            for table_name in _EXAM_BACKFILL_TABLES:
                try:
                    conn.execute(
                        text(
                            f"UPDATE {table_name} SET organization_id = :oid "
                            "WHERE organization_id IS NULL OR organization_id = ''"
                        ),
                        {"oid": org_id},
                    )
                except Exception:
                    continue
            conn.commit()
    except Exception:
        db.session.rollback()
        raise


def repair_users_without_team_membership() -> int:
    """启动时幂等：无任何项目组绑定的账号补默认项目组（互联网产品部）。"""
    from . import db
    from .models import ProjectTeam, User, UserTeamMembership
    from .team_data_migration import DEFAULT_TEAM_NAME

    team = ProjectTeam.query.filter_by(name=DEFAULT_TEAM_NAME).first()
    if not team:
        from .team_data_migration import ensure_default_team_data

        ensure_default_team_data()
        team = ProjectTeam.query.filter_by(name=DEFAULT_TEAM_NAME).first()
    if not team:
        return 0
    try:
        from .tenant_context import default_organization

        dorg = default_organization()
        dorg_id = str(getattr(dorg, "id", "") or "").strip()
        if dorg_id and not str(getattr(team, "organization_id", "") or "").strip():
            team.organization_id = dorg_id
            db.session.add(team)
    except Exception:
        pass
    linked = 0
    for u in User.query.all():
        uid = str(u.id or "").strip()
        if not uid:
            continue
        if UserTeamMembership.query.filter_by(user_id=uid).first():
            continue
        db.session.add(UserTeamMembership(user_id=uid, team_id=team.id))
        linked += 1
    if linked:
        db.session.commit()
    return linked


def cleanup_redundant_default_team_memberships() -> int:
    """用户已属于其它项目组时，移除历史回填误加的默认组「互联网产品部」成员关系。"""
    from . import db
    from .models import ProjectTeam, UserTeamMembership
    from .team_data_migration import DEFAULT_TEAM_NAME

    team = ProjectTeam.query.filter_by(name=DEFAULT_TEAM_NAME, is_active=True).first()
    if not team:
        return 0
    default_id = str(team.id or "").strip()
    if not default_id:
        return 0
    removed = 0
    for m in UserTeamMembership.query.filter_by(team_id=default_id).all():
        uid = str(m.user_id or "").strip()
        if not uid:
            continue
        has_other = (
            UserTeamMembership.query.filter(
                UserTeamMembership.user_id == uid,
                UserTeamMembership.team_id != default_id,
            ).first()
            is not None
        )
        if has_other:
            db.session.delete(m)
            removed += 1
    if removed:
        db.session.commit()
    return removed


def repair_exam_participants_default_team() -> int:
    """有考试活动但无任何项目组的账号，补默认项目组「互联网产品部」（幂等；不覆盖已有归属）。"""
    from . import db
    from .models import ExamCenterActivity, ProjectTeam, User, UserTeamMembership
    from .team_data_migration import DEFAULT_TEAM_NAME, ensure_default_team_data
    from .team_organizations import set_team_organization_ids
    from .tenant_context import default_organization

    ensure_default_team_data()
    team = ProjectTeam.query.filter_by(name=DEFAULT_TEAM_NAME, is_active=True).first()
    if not team:
        return 0
    dorg = default_organization()
    dorg_id = str(getattr(dorg, "id", "") or "").strip()
    if dorg_id:
        set_team_organization_ids(str(team.id), [dorg_id])
        db.session.flush()
    raw_uids = {
        str(r[0]).strip()
        for r in db.session.query(ExamCenterActivity.user_id).distinct().all()
        if r and str(r[0] or "").strip()
    }
    if not raw_uids:
        db.session.commit()
        return 0
    valid_uids = {
        str(u.id).strip()
        for u in User.query.filter(User.id.in_(list(raw_uids))).all()
        if str(u.id or "").strip()
    }
    linked = 0
    for uid in valid_uids:
        if UserTeamMembership.query.filter_by(user_id=uid).first():
            continue
        db.session.add(UserTeamMembership(user_id=uid, team_id=team.id))
        linked += 1
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return 0
    return linked


def repair_project_admins_without_team() -> int:
    """项目管理员无项目组时补默认组「互联网产品部」（幂等）。"""
    from . import db
    from .models import ADMIN_ROLE_PROJECT, ProjectTeam, User, UserTeamMembership
    from .team_data_migration import DEFAULT_TEAM_NAME, ensure_default_team_data

    ensure_default_team_data()
    team = ProjectTeam.query.filter_by(name=DEFAULT_TEAM_NAME, is_active=True).first()
    if not team:
        return 0
    linked = 0
    for u in User.query.filter_by(admin_role=ADMIN_ROLE_PROJECT).all():
        uid = str(u.id or "").strip()
        if not uid:
            continue
        if UserTeamMembership.query.filter_by(user_id=uid).first():
            continue
        db.session.add(UserTeamMembership(user_id=uid, team_id=team.id))
        linked += 1
    if linked:
        db.session.commit()
    return linked


def repair_exam_activity_user_identity() -> int:
    """规范化活动 user_id，并清理 display_name/username 中的 UUID/括号 id（幂等）。"""
    from . import db
    from .exam_display_labels import (
        looks_like_opaque_id,
        normalize_user_key,
        resolve_user_record,
        user_preferred_label,
    )
    from .models import ExamCenterActivity, User

    fixed = 0
    for a in ExamCenterActivity.query.all():
        raw_uid = str(getattr(a, "user_id", "") or "").strip()
        nk = normalize_user_key(raw_uid)
        u = resolve_user_record(nk or raw_uid)
        canon = str(getattr(u, "id", "") or nk or "").strip()
        if canon and raw_uid and raw_uid != canon:
            a.user_id = canon
            fixed += 1
        for field in ("display_name", "username"):
            val = str(getattr(a, field, "") or "").strip()
            if not val or not looks_like_opaque_id(val):
                continue
            if u:
                pref = user_preferred_label(u)
            else:
                pref = ""
            if pref and not looks_like_opaque_id(pref):
                setattr(a, field, pref)
                fixed += 1
    for u in User.query.all():
        for field in ("display_name", "username"):
            val = str(getattr(u, field, "") or "").strip()
            if not val or not looks_like_opaque_id(val):
                continue
            other = "username" if field == "display_name" else "display_name"
            alt = str(getattr(u, other, "") or "").strip()
            if alt and not looks_like_opaque_id(alt):
                if field == "display_name":
                    u.display_name = alt
                else:
                    u.username = alt
                fixed += 1
    if fixed:
        db.session.commit()
    return fixed


def repair_exam_scope_defaults() -> None:
    """查询前可安全重复执行：默认公司/项目组绑定，不删除测试项目组。"""
    repair_exam_null_organization_ids()
    repair_exam_activity_organization_to_default()
    ensure_default_team_linked_to_default_org()
    cleanup_redundant_default_team_memberships()
    repair_exam_participants_default_team()
    repair_project_admins_without_team()
    repair_users_without_team_membership()
    repair_exam_activity_user_identity()
    try:
        from .routes import _backfill_exam_center_activities_from_attempts

        _backfill_exam_center_activities_from_attempts()
    except Exception:
        from . import db

        db.session.rollback()


def repair_exam_historical_data() -> None:
    """考试训练中心历史空值批量处理：默认公司 + 默认项目组 + 清理测试组。"""
    repair_exam_scope_defaults()
    cleanup_test_project_teams()


def run_exam_organization_backfill_if_pending() -> None:
    """考试训练中心历史数据一次性回填默认公司（南京鱼跃），与总历史迁移标记独立。"""
    if is_exam_org_backfill_done():
        return
    from . import db
    from .tenant_context import default_organization

    org = default_organization()
    if not org or not str(org.id or "").strip():
        return
    org_id = str(org.id).strip()
    try:
        with db.engine.connect() as conn:
            for table_name in _EXAM_BACKFILL_TABLES:
                try:
                    conn.execute(
                        text(
                            f"UPDATE {table_name} SET organization_id = :oid "
                            "WHERE organization_id IS NULL OR organization_id = ''"
                        ),
                        {"oid": org_id},
                    )
                except Exception:
                    continue
            conn.commit()
        mark_exam_org_backfill_done()
    except Exception:
        db.session.rollback()
        raise
