from __future__ import annotations

"""
考试中心最小联调回归脚本（本地 mock 上游）。

用途：
- 改动 exam_center 前后，快速验证关键链路是否回归。
- 避免再次出现 answers 结构 / attempt_id / 状态文案语义相关低级错误。
- 脚本结束（含断言失败）后自动清理 exam_smoke_* 测试账号、项目组、任务与活动，不污染业务库。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webapp import create_app, db
import webapp.routes as routes
from webapp.models import (
    ADMIN_ROLE_NONE,
    ADMIN_ROLE_PROJECT,
    AppConfig,
    ExamCenterActivity,
    ExamCenterActivityDetail,
    ExamCenterAssignment,
    ExamCenterAssignmentAudience,
    ExamAttempt,
    ExamAttemptItem,
    ProjectTeam,
    ProjectTeamOrganization,
    User,
    UserOrganizationMembership,
    UserTeamMembership,
)


SMOKE_TEAM_A_NAME = "exam_smoke_team_alpha"
SMOKE_TEAM_B_NAME = "exam_smoke_team_beta"
SMOKE_PA_A = "exam_smoke_pa_a"
SMOKE_STU_A = "exam_smoke_stu_a"
SMOKE_STU_B = "exam_smoke_stu_b"
SMOKE_ASSIGNMENT_ID = "smoke-co-scope-assign-1"
SMOKE_SESSION_USER_ID = "stu-1"
SMOKE_USERNAMES = (SMOKE_PA_A, SMOKE_STU_A, SMOKE_STU_B)
SMOKE_TEAM_NAMES = (
    SMOKE_TEAM_A_NAME,
    SMOKE_TEAM_B_NAME,
    "regress_scope_team_a",
    "regress_scope_team_b",
)


def _get_config_value(key: str) -> str:
    row = AppConfig.query.filter_by(config_key=key).first()
    return str(row.config_value or "").strip() if row else ""


def _set_config_value(key: str, value: str) -> None:
    from webapp.app_settings import _upsert_config

    _upsert_config(key, value)
    db.session.commit()


def _ensure_team(name: str, org_id: str | None = None) -> ProjectTeam:
    from webapp.team_organizations import set_team_organization_ids

    row = ProjectTeam.query.filter_by(name=name).first()
    if row:
        if org_id:
            oid = str(org_id).strip()
            if str(getattr(row, "organization_id", "") or "").strip() != oid:
                row.organization_id = oid
            set_team_organization_ids(str(row.id), [oid])
        return row
    row = ProjectTeam(name=name, is_active=True)
    if org_id:
        row.organization_id = str(org_id).strip()
    db.session.add(row)
    db.session.flush()
    if org_id:
        set_team_organization_ids(str(row.id), [str(org_id).strip()])
    return row


def _ensure_user(
    username: str,
    *,
    admin_role: str,
    team_id: str,
    org_id: str | None,
) -> User:
    u = User.query.filter_by(username=username).first()
    if not u:
        u = User(
            username=username,
            display_name=username,
            admin_role=admin_role,
            is_admin=False,
        )
        u.set_password("smoke-test")
        db.session.add(u)
        db.session.flush()
    else:
        u.admin_role = admin_role
    UserTeamMembership.query.filter_by(user_id=u.id).delete(synchronize_session=False)
    db.session.add(UserTeamMembership(user_id=u.id, team_id=team_id))
    if org_id:
        exists = UserOrganizationMembership.query.filter_by(
            user_id=u.id, organization_id=org_id
        ).first()
        if not exists:
            db.session.add(UserOrganizationMembership(user_id=u.id, organization_id=org_id))
    db.session.flush()
    return u


def _add_exam_activity(*, user: User, org_id: str, mode: str = "exam") -> ExamCenterActivity:
    row = ExamCenterActivity(
        organization_id=org_id or None,
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        mode=mode,
        exam_track="cn",
        exam_category="daily",
        result_summary="smoke team scope",
    )
    db.session.add(row)
    db.session.flush()
    return row


def _delete_smoke_activities_for_users(user_ids: list[str]) -> None:
    if not user_ids:
        return
    acts = ExamCenterActivity.query.filter(ExamCenterActivity.user_id.in_(user_ids)).all()
    act_ids = [str(a.id) for a in acts if getattr(a, "id", None)]
    if act_ids:
        ExamCenterActivityDetail.query.filter(
            ExamCenterActivityDetail.activity_id.in_(act_ids)
        ).delete(synchronize_session=False)
    ExamCenterActivity.query.filter(ExamCenterActivity.user_id.in_(user_ids)).delete(
        synchronize_session=False
    )


def _collect_smoke_assignment_ids() -> list[str]:
    from sqlalchemy import or_

    rows = ExamCenterAssignment.query.filter(
        or_(
            ExamCenterAssignment.assignment_id == SMOKE_ASSIGNMENT_ID,
            ExamCenterAssignment.title.contains("Smoke"),
            ExamCenterAssignment.title.contains("【测试】"),
            ExamCenterAssignment.set_id == "set-100",
        )
    ).all()
    aids: list[str] = []
    for row in rows:
        aid = str(getattr(row, "assignment_id", "") or "").strip()
        if aid and aid not in aids:
            aids.append(aid)
    return aids


def _delete_exam_records_for_assignment_ids(aids: list[str]) -> None:
    if not aids:
        return
    ExamCenterAssignmentAudience.query.filter(
        ExamCenterAssignmentAudience.assignment_id.in_(aids)
    ).delete(synchronize_session=False)

    acts = ExamCenterActivity.query.filter(ExamCenterActivity.assignment_id.in_(aids)).all()
    act_ids = [str(a.id) for a in acts if getattr(a, "id", None)]
    if act_ids:
        ExamCenterActivityDetail.query.filter(
            ExamCenterActivityDetail.activity_id.in_(act_ids)
        ).delete(synchronize_session=False)
        ExamCenterActivity.query.filter(ExamCenterActivity.id.in_(act_ids)).delete(
            synchronize_session=False
        )

    attempt_keys = [
        str(x.attempt_id)
        for x in ExamAttempt.query.filter(ExamAttempt.assignment_id.in_(aids)).all()
        if str(getattr(x, "attempt_id", "") or "").strip()
    ]
    if attempt_keys:
        ExamAttemptItem.query.filter(ExamAttemptItem.attempt_id.in_(attempt_keys)).delete(
            synchronize_session=False
        )
    ExamAttempt.query.filter(ExamAttempt.assignment_id.in_(aids)).delete(synchronize_session=False)
    ExamCenterAssignment.query.filter(ExamCenterAssignment.assignment_id.in_(aids)).delete(
        synchronize_session=False
    )


def _purge_exam_smoke_database_artifacts() -> None:
    """删除本脚本产生的项目组/账号/考试任务/活动记录，避免污染业务库。"""
    from webapp.models import CompanyProject, Project

    smoke_users = User.query.filter(User.username.in_(SMOKE_USERNAMES)).all()
    smoke_user_ids = [str(u.id) for u in smoke_users if getattr(u, "id", None)]

    extra_user_ids = [SMOKE_SESSION_USER_ID]
    all_user_ids = list(dict.fromkeys(smoke_user_ids + extra_user_ids))
    _delete_smoke_activities_for_users(all_user_ids)

    username_acts = ExamCenterActivity.query.filter(
        ExamCenterActivity.username.in_(SMOKE_USERNAMES)
    ).all()
    username_act_ids = [str(a.id) for a in username_acts if getattr(a, "id", None)]
    if username_act_ids:
        ExamCenterActivityDetail.query.filter(
            ExamCenterActivityDetail.activity_id.in_(username_act_ids)
        ).delete(synchronize_session=False)
        ExamCenterActivity.query.filter(ExamCenterActivity.id.in_(username_act_ids)).delete(
            synchronize_session=False
        )

    orphan_acts = ExamCenterActivity.query.filter(
        ExamCenterActivity.result_summary.like("smoke %")
    ).all()
    orphan_act_ids = [str(a.id) for a in orphan_acts if getattr(a, "id", None)]
    if orphan_act_ids:
        ExamCenterActivityDetail.query.filter(
            ExamCenterActivityDetail.activity_id.in_(orphan_act_ids)
        ).delete(synchronize_session=False)
        ExamCenterActivity.query.filter(ExamCenterActivity.id.in_(orphan_act_ids)).delete(
            synchronize_session=False
        )

    _delete_exam_records_for_assignment_ids(_collect_smoke_assignment_ids())

    for uid in smoke_user_ids:
        ExamCenterAssignmentAudience.query.filter_by(user_id=uid).delete(
            synchronize_session=False
        )
        attempt_keys = [
            str(x.attempt_id)
            for x in ExamAttempt.query.filter_by(user_id=uid).all()
            if str(getattr(x, "attempt_id", "") or "").strip()
        ]
        if attempt_keys:
            ExamAttemptItem.query.filter(ExamAttemptItem.attempt_id.in_(attempt_keys)).delete(
                synchronize_session=False
            )
        ExamAttempt.query.filter_by(user_id=uid).delete(synchronize_session=False)
        UserTeamMembership.query.filter_by(user_id=uid).delete(synchronize_session=False)
        UserOrganizationMembership.query.filter_by(user_id=uid).delete(synchronize_session=False)

    for username in SMOKE_USERNAMES:
        u = User.query.filter_by(username=username).first()
        if u:
            db.session.delete(u)

    smoke_teams = ProjectTeam.query.filter(ProjectTeam.name.in_(SMOKE_TEAM_NAMES)).all()
    default_team = ProjectTeam.query.filter_by(name="互联网产品部", is_active=True).first()
    default_team_id = str(getattr(default_team, "id", "") or "").strip()

    for team in smoke_teams:
        tid = str(getattr(team, "id", "") or "").strip()
        if not tid:
            continue
        UserTeamMembership.query.filter_by(team_id=tid).delete(synchronize_session=False)
        if default_team_id:
            CompanyProject.query.filter_by(assigned_team_id=tid).update(
                {"assigned_team_id": default_team_id}, synchronize_session=False
            )
            Project.query.filter_by(assigned_team_id=tid).update(
                {"assigned_team_id": default_team_id}, synchronize_session=False
            )
        ProjectTeamOrganization.query.filter_by(team_id=tid).delete(synchronize_session=False)
        db.session.delete(team)

    db.session.commit()


def run_exam_team_scope_regression(app, c) -> None:
    """项目管理员 A 不可见项目组 B 学员的练习/考试记录与下发人选。"""
    from webapp.tenant_context import default_organization

    old_registry = ""
    user_ids: list[str] = []
    pa_a_id = stu_a_id = stu_b_id = org_id = team_a_id = team_b_id = pa_username = pa_display = ""

    with app.app_context():
        old_registry = _get_config_value("FEATURE_COMPANY_REGISTRY")
        _set_config_value("FEATURE_COMPANY_REGISTRY", "1")
        org = default_organization()
        assert org and org.id, "缺少默认公司，无法跑项目组隔离回归"
        org_id = str(org.id).strip()

        team_a = _ensure_team(SMOKE_TEAM_A_NAME, org_id=org_id)
        team_b = _ensure_team(SMOKE_TEAM_B_NAME, org_id=org_id)
        pa_a = _ensure_user(SMOKE_PA_A, admin_role=ADMIN_ROLE_PROJECT, team_id=team_a.id, org_id=org_id)
        stu_a = _ensure_user(SMOKE_STU_A, admin_role=ADMIN_ROLE_NONE, team_id=team_a.id, org_id=org_id)
        stu_b = _ensure_user(SMOKE_STU_B, admin_role=ADMIN_ROLE_NONE, team_id=team_b.id, org_id=org_id)
        pa_a_id = str(pa_a.id)
        stu_a_id = str(stu_a.id)
        stu_b_id = str(stu_b.id)
        pa_username = pa_a.username
        pa_display = pa_a.display_name or pa_a.username
        team_a_id = str(team_a.id)
        team_b_id = str(team_b.id)
        user_ids = [pa_a_id, stu_a_id, stu_b_id]

        _delete_smoke_activities_for_users(user_ids)
        _add_exam_activity(user=stu_a, org_id=org_id, mode="practice")
        _add_exam_activity(user=stu_b, org_id=org_id, mode="exam")
        db.session.commit()

    try:
        with c.session_transaction() as s:
            s.pop("page13_authenticated", None)
            s["user_id"] = pa_a_id
            s["username"] = pa_username
            s["display_name"] = pa_display
            s["admin_role"] = ADMIN_ROLE_PROJECT
            s["active_organization_id"] = org_id
            s["organization_ids"] = [org_id]
            s["team_ids"] = [team_a_id]

        r = c.get("/api/exam-center/stats/students")
        assert r.status_code == 200, r.get_json()
        rows = ((r.get_json() or {}).get("data") or {}).get("rows") or []
        row_ids = {str(x.get("student_id") or "") for x in rows if isinstance(x, dict)}
        assert stu_a_id in row_ids, {"expected_stu_a": stu_a_id, "rows": rows}
        assert stu_b_id not in row_ids, {"forbidden_stu_b": stu_b_id, "rows": rows}

        r_scope_pa = c.get("/api/exam-center/scope-context")
        assert r_scope_pa.status_code == 200, r_scope_pa.get_json()
        scope_pa = r_scope_pa.get_json() or {}
        assert scope_pa.get("isProjectAdmin"), scope_pa
        pa_teams = scope_pa.get("assignedTeams") or scope_pa.get("teams") or []
        assert pa_teams, {"project_admin_scope_teams": scope_pa}
        assert str(scope_pa.get("activeOrganizationId") or "") == org_id, scope_pa

        r2 = c.get(f"/api/exam-center/stats/student/{stu_b_id}")
        assert r2.status_code == 404, r2.get_json()

        r3 = c.get("/api/exam-center/teacher/assignable-users")
        assert r3.status_code == 200, r3.get_json()
        assign_ids = {
            str(u.get("id") or "")
            for u in (r3.get_json() or {}).get("users") or []
            if isinstance(u, dict)
        }
        assert stu_a_id in assign_ids, assign_ids
        assert stu_b_id not in assign_ids, assign_ids

        r4 = c.get("/api/exam-center/stats/overview")
        assert r4.status_code == 200, r4.get_json()
        overview = (r4.get_json() or {}).get("data") or {}
        assert int(overview.get("students_total") or 0) == 1, overview

        with c.session_transaction() as s:
            s["page13_authenticated"] = True
            s.pop("user_id", None)
            s.pop("admin_role", None)
            s.pop("team_ids", None)
            s["active_organization_id"] = org_id
            s.pop("active_exam_team_id", None)

        r5 = c.get("/api/exam-center/stats/students")
        assert r5.status_code == 200, r5.get_json()
        sa_rows = ((r5.get_json() or {}).get("data") or {}).get("rows") or []
        sa_ids = {str(x.get("student_id") or "") for x in sa_rows if isinstance(x, dict)}
        assert stu_a_id not in sa_ids and stu_b_id not in sa_ids, {
            "super_admin_without_scope_all_filters_default_team": sa_rows,
        }

        r_scope = c.get("/api/exam-center/scope-context")
        assert r_scope.status_code == 200, r_scope.get_json()
        scope_j = r_scope.get_json() or {}
        scope_team_names = [str(t.get("name") or "") for t in scope_j.get("teams") or []]
        assert not any(n.startswith("exam_smoke_") for n in scope_team_names), scope_j

        from webapp.routes import _project_teams_for_organization

        with c.session_transaction() as s:
            s["exam_team_scope_all"] = True
            s.pop("active_exam_team_id", None)

        r5b = c.get("/api/exam-center/stats/students")
        sa_rows_b = ((r5b.get_json() or {}).get("data") or {}).get("rows") or []
        sa_ids_b = {str(x.get("student_id") or "") for x in sa_rows_b if isinstance(x, dict)}
        assert stu_a_id in sa_ids_b and stu_b_id in sa_ids_b, {"super_admin_all_teams": sa_rows_b}

        from webapp.models import Organization

        other_org = (
            Organization.query.filter(
                Organization.id != org_id,
                Organization.is_active.is_(True),
            )
            .order_by(Organization.created_at.asc())
            .first()
        )
        if other_org:
            real_a_id = real_b_id = ""
            with app.app_context():
                real_a = _ensure_team("regress_scope_team_a", org_id=org_id)
                real_b = _ensure_team("regress_scope_team_b", org_id=str(other_org.id).strip())
                real_a_id = str(real_a.id)
                real_b_id = str(real_b.id)
                db.session.commit()
                teams_other = _project_teams_for_organization(org_id)
                team_ids_other = {str(t.id) for t in teams_other}
            assert real_a_id in team_ids_other and real_b_id not in team_ids_other
            with app.app_context():
                ProjectTeam.query.filter(
                    ProjectTeam.name.in_(["regress_scope_team_a", "regress_scope_team_b"])
                ).delete(synchronize_session=False)
                db.session.commit()

        with c.session_transaction() as s:
            s["exam_team_scope_all"] = True
            s.pop("active_exam_team_id", None)
            s["active_exam_team_id"] = team_a_id
            s.pop("exam_team_scope_all", None)

        r5a = c.get("/api/exam-center/stats/students")
        sa_rows_a = ((r5a.get_json() or {}).get("data") or {}).get("rows") or []
        sa_ids_a = {str(x.get("student_id") or "") for x in sa_rows_a if isinstance(x, dict)}
        assert stu_a_id in sa_ids_a and stu_b_id not in sa_ids_a, {"team_a_scope": sa_rows_a}

        with app.app_context():
            null_act = ExamCenterActivity(
                organization_id=None,
                user_id=stu_b_id,
                username=SMOKE_STU_B,
                display_name=SMOKE_STU_B,
                mode="practice",
                exam_track="cn",
                exam_category="daily",
                result_summary="smoke null org",
            )
            db.session.add(null_act)
            db.session.commit()

        r6 = c.get("/api/exam-center/stats/students")
        sa_ids2 = {
            str(x.get("student_id") or "")
            for x in ((r6.get_json() or {}).get("data") or {}).get("rows") or []
            if isinstance(x, dict)
        }
        assert stu_b_id not in sa_ids2, {"null_org_not_in_scoped_company": r6.get_json()}

        with c.session_transaction() as s:
            s.pop("page13_authenticated", None)
            s["user_id"] = pa_a_id
            s["username"] = pa_username
            s["display_name"] = pa_display
            s["admin_role"] = ADMIN_ROLE_PROJECT
            s["active_organization_id"] = org_id
            s["organization_ids"] = [org_id]
            s["team_ids"] = [team_a_id]

        r7 = c.get("/api/exam-center/stats/students")
        pa_ids2 = {
            str(x.get("student_id") or "")
            for x in ((r7.get_json() or {}).get("data") or {}).get("rows") or []
            if isinstance(x, dict)
        }
        assert stu_a_id in pa_ids2 and stu_b_id not in pa_ids2, r7.get_json()

        smoke_assign_id = SMOKE_ASSIGNMENT_ID
        with app.app_context():
            from webapp.models import ExamCenterAssignmentAudience

            ExamCenterAssignment.query.filter_by(assignment_id=smoke_assign_id).delete(
                synchronize_session=False
            )
            row_asn = ExamCenterAssignment(
                assignment_id=smoke_assign_id,
                organization_id=org_id,
                title="smoke company scoped assign",
                status="published",
            )
            db.session.add(row_asn)
            db.session.add(
                ExamCenterAssignmentAudience(assignment_id=smoke_assign_id, user_id=stu_b_id)
            )
            db.session.commit()

        r_assign_list = c.get("/api/exam-center/teacher/assignments-local")
        assert r_assign_list.status_code == 200, r_assign_list.get_json()
        assign_ids = {
            str(x.get("assignment_id") or "")
            for x in ((r_assign_list.get_json() or {}).get("data") or {}).get("rows") or []
            if isinstance(x, dict)
        }
        assert smoke_assign_id in assign_ids, {"pa_sees_company_assignment": assign_ids}

        with c.session_transaction() as s:
            s["page13_authenticated"] = True
            s.pop("user_id", None)
            s.pop("admin_role", None)
            s.pop("team_ids", None)

        r_student_page = c.get("/exam-center?role=student")
        assert r_student_page.status_code == 200, r_student_page.status_code
        assert "学生端" in (r_student_page.get_data(as_text=True) or "")

        r_scope_super = c.get("/api/exam-center/scope-context")
        assert r_scope_super.status_code == 200, r_scope_super.get_json()
    finally:
        with app.app_context():
            _purge_exam_smoke_database_artifacts()
            _set_config_value("FEATURE_COMPANY_REGISTRY", old_registry)


def run() -> None:
    app = create_app()
    state = {
        "assignments": {},
        "next_assignment": 100,
        "next_attempt": 500,
    }

    def fake_quiz(path: str, method: str = "GET", payload=None, query=None, timeout_seconds=None, organization_id=None, **_kw):
        payload = payload or {}
        if path.startswith("quiz/sets/") and path.endswith("/publish") and method == "POST":
            set_id = path.split("/")[2]
            return 200, {"code": 0, "message": "ok", "data": {"code": 0, "status": "published", "set_id": set_id}}

        if method == "GET":
            parts_g = [p for p in path.split("/") if p]
            if len(parts_g) == 3 and parts_g[0] == "quiz" and parts_g[1] == "sets":
                sid = parts_g[2]
                return 200, {
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "code": 0,
                        "data": {
                            "id": sid,
                            "title": "smoke-set",
                            "questions": [
                                {"question_id": "q1", "stem": "题1", "options": [{"id": "A", "text": "甲"}]},
                            ],
                        },
                    },
                }

        if path == "quiz/assignments" and method == "POST":
            aid = str(state["next_assignment"])
            state["next_assignment"] += 1
            title = payload.get("title") or payload.get("name") or f"任务-{aid}"
            set_id = str(payload.get("set_id") or payload.get("setId") or "")
            rec = {"assignment_id": aid, "title": title, "set_id": set_id}
            state["assignments"][aid] = rec
            return 200, {"code": 0, "message": "ok", "data": {"code": 0, "data": rec}}

        if path in ("quiz/student/assignments", "quiz/me/assignments", "quiz/student/exams") and method == "GET":
            items = [{"assignment_id": k, "title": v["title"], "set_id": v["set_id"]} for k, v in state["assignments"].items()]
            return 200, {"code": 0, "message": "ok", "data": {"code": 0, "data": {"assignments": items}}}

        if path.startswith("quiz/exams/") and path.endswith("/start") and method == "POST":
            assignment_id = path.split("/")[2]
            if assignment_id not in state["assignments"]:
                return 404, {"code": "NOT_FOUND", "message": "assignment not found", "data": None}
            attempt_id = state["next_attempt"]
            state["next_attempt"] += 1
            return 200, {
                "code": 0,
                "message": "ok",
                "data": {
                    "code": 0,
                    "data": {
                        "attempt_id": attempt_id,
                        "assignment_id": assignment_id,
                        "questions": [
                            {"question_id": "q1", "stem": "题1", "options": [{"id": "A", "text": "甲"}]},
                            {"question_id": "q2", "stem": "题2", "options": [{"id": "B", "text": "乙"}]},
                        ],
                    },
                },
            }

        if path == "quiz/practice/submit" and method == "POST":
            if not isinstance(payload.get("answers"), list):
                return 422, {"code": "BAD", "message": "answers must be list", "data": None}
            if not (payload.get("attempt_id") or payload.get("attemptId") or (query or {}).get("attempt_id")):
                return 422, {"code": "BAD", "message": "attempt_id required", "data": None}
            return 200, {"code": 0, "message": "ok", "data": {"code": 0, "score": 82, "max_score": 100}}

        if path.startswith("quiz/exams/") and path.endswith("/submit") and method == "POST":
            if not isinstance(payload.get("answers"), list):
                return 422, {"code": "BAD", "message": "answers must be list", "data": None}
            return 200, {"code": 0, "message": "ok", "data": {"code": 0, "score": 76, "max_score": 100}}

        if path == "quiz/stats/overview" and method == "GET":
            return 503, {"code": "UPSTREAM_DOWN", "message": "down", "data": None}
        if path in ("quiz/stats/options", "quiz/stats/recent-activity") and method == "GET":
            return 503, {"code": "UPSTREAM_DOWN", "message": "down", "data": None}

        if path.startswith("quiz/stats/exam/") and method == "GET":
            return 404, {"code": "NOT_MOCKED", "message": "no upstream exam stats", "data": None}

        if path == "quiz/tools/regulatory-updates-hint" and method == "POST":
            # 与真实 _quiz_api_call 一致：整包含 code/data（data 内为上游 FastAPI 根对象）
            return 200, {
                "code": 0,
                "message": "ok",
                "data": {
                    "ok": True,
                    "data": {
                        "since": "2025-01-01",
                        "as_of": "2026-01-01",
                        "exam_track": str(payload.get("exam_track") or "cn"),
                        "checklist": [
                            {"domain": "mock", "what_to_watch": "x", "why_for_software": "y", "how_to_verify": "z"}
                        ],
                        "suggested_question_angles": ["a1"],
                    },
                },
                "trace_id": "smoke-regulatory",
                "request": {"url": "mock://quiz", "method": "POST", "upstreamPath": path},
            }

        return 404, {"code": "NOT_MOCKED", "message": f"{method} {path}", "data": None}

    routes._quiz_api_call = fake_quiz

    try:
        with app.app_context():
            _purge_exam_smoke_database_artifacts()

        checks: list[str] = []
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["page13_authenticated"] = True
                s["display_name"] = "老师A"
                s["username"] = "teacher_a"

            r = c.post("/api/exam-center/teacher/sets/publish", json={"set_id": "set-100"})
            assert r.status_code == 200, r.get_json()
            checks.append("teacher_sync_set")

            r = c.post(
                "/api/exam-center/teacher/regulatory-updates-hint",
                json={"exam_track": "cn", "exam_category": "new_standard"},
            )
            assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:800])
            hint_j = r.get_json() or {}
            assert hint_j.get("code") == 0, hint_j
            inner = ((hint_j.get("data") or {}).get("data") or {})
            assert isinstance(inner.get("checklist"), list) and inner["checklist"], hint_j
            checks.append("teacher_regulatory_updates_hint_route")

            r = c.post(
                "/api/exam-center/teacher/assignments",
                json={"set_id": "set-100", "title": "【测试】Smoke 考试任务", "due_date": "2030-12-31"},
            )
            j = r.get_json()
            aid = ((j.get("aiword") or {}).get("assignment") or {}).get("assignment_id")
            assert r.status_code == 200 and aid, j
            checks.append("teacher_create_assignment")

            with c.session_transaction() as s:
                s.pop("page13_authenticated", None)
                s["user_id"] = SMOKE_SESSION_USER_ID
                s["username"] = "stu_login"
                s["display_name"] = "学生甲"

            r = c.get("/api/exam-center/student/assignments")
            arr = ((r.get_json().get("data") or {}).get("assignments") or [])
            hit = next((x for x in arr if str(x.get("id")) == str(aid)), None)
            assert hit is not None, r.get_json()
            assert hit.get("due_at"), r.get_json()
            checks.append("student_assignments_visible")

            r = c.post("/api/exam-center/student/exams/start", json={"assignment_id": str(aid)})
            sj0 = r.get_json() or {}
            d0 = sj0.get("data") or {}
            attempt_id = d0.get("attempt_id")
            if attempt_id is None and isinstance(d0.get("data"), dict):
                attempt_id = d0["data"].get("attempt_id")
            assert r.status_code == 200 and attempt_id is not None, sj0
            checks.append("student_start_exam")

            r = c.post("/api/exam-center/student/practice/submit", json={"session_id": "701", "answers": {"p1": "A"}})
            assert r.status_code == 200, r.get_json()
            checks.append("practice_submit_normalized")

            r = c.post(
                "/api/exam-center/student/exams/submit",
                json={"attempt_id": str(attempt_id), "assignment_id": str(aid), "answers": {"q1": "A"}},
            )
            assert r.status_code == 200, r.get_json()
            checks.append("exam_submit_normalized")

            with c.session_transaction() as s:
                s["page13_authenticated"] = True
                s["display_name"] = "老师A"
                s["username"] = "teacher_a"
            r = c.get(f"/api/exam-center/stats/exam/{aid}")
            sj = r.get_json() or {}
            dc = ((sj.get("data") or {}).get("deadline_completion")) or {}
            # 本地聚合字段以 DB 为准；mock 上游时准点人数可能仍为 0，只校验结构与迟交口径
            assert r.status_code == 200 and isinstance(dc, dict) and str(dc.get("due_at") or "").strip(), sj
            assert int(dc.get("late_count") or 0) == 0, sj
            checks.append("stats_exam_deadline_local")

            with c.session_transaction() as s:
                s.pop("page13_authenticated", None)
                s["user_id"] = SMOKE_SESSION_USER_ID
                s["username"] = "stu_login"
                s["display_name"] = "学生甲"

            r = c.get("/api/exam-center/student/history")
            recs = ((r.get_json().get("data") or {}).get("records") or [])
            assert recs and all("score" in x for x in recs), r.get_json()
            checks.append("history_scored")

            with c.session_transaction() as s:
                s["page13_authenticated"] = True
                s["exam_team_scope_all"] = True
                s.pop("active_exam_team_id", None)
            r = c.get("/api/exam-center/stats/overview")
            d = (r.get_json() or {}).get("data") or {}
            assert "pass_score" in d and "pass_count" in d and "pass_rate_percent" in d, r.get_json()
            checks.append("stats_pass_metrics")

            r = c.get("/api/exam-center/stats/students")
            assert r.status_code == 200, r.get_json()
            rows = ((r.get_json() or {}).get("data") or {}).get("rows")
            assert isinstance(rows, list) and len(rows) >= 1, r.get_json()
            checks.append("stats_students_table")

            r = c.get("/api/exam-center/stats/students_by_mode")
            assert r.status_code == 200, r.get_json()
            rows2 = ((r.get_json() or {}).get("data") or {}).get("rows")
            assert isinstance(rows2, list) and len(rows2) >= 2, r.get_json()
            assert any(str(x.get("mode")) == "exam" for x in rows2 if isinstance(x, dict)), r.get_json()
            checks.append("stats_students_by_mode")
            r_alt = c.get("/api/exam-center/stats/students-by-mode")
            assert r_alt.status_code == 200, r_alt.get_json()
            checks.append("stats_students_by_mode_hyphen_alias")

            run_exam_team_scope_regression(app, c)
            checks.append("team_scope_project_admin_cannot_see_other_team")
            checks.append("super_admin_scoped_by_company_and_team")

        print("ALL_OK", ",".join(checks))
    finally:
        with app.app_context():
            _purge_exam_smoke_database_artifacts()


if __name__ == "__main__":
    run()

