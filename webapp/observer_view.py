# -*- coding: utf-8 -*-
"""页面2 / 考试学生端：超管与项目管理员只读观察视图（普通账号逻辑不变）。"""
from __future__ import annotations

from typing import Any

from .authz import (
    _project_lookup_maps,
    filter_upload_records_in_scope,
    is_page13_super_admin,
    is_project_admin,
)
from .models import ProjectTeam, UploadRecord, User, UserTeamMembership


def page2_view_mode() -> str:
    if is_page13_super_admin():
        return "super_admin_readonly"
    if is_project_admin():
        return "project_admin_readonly"
    return "normal"


def exam_student_view_mode() -> str:
    return page2_view_mode()


def page2_mutation_allowed() -> bool:
    """全局写权限：仅普通账号；项管/超管走记录级 upload_record_mutable_by_current_user。"""
    return page2_view_mode() == "normal"


def page2_observer_mode() -> bool:
    return page2_view_mode() != "normal"


def exam_student_mutation_allowed() -> bool:
    """考试学生端写操作：普通账号与项管（按 assignment 受众校验）；超管只读。"""
    mode = exam_student_view_mode()
    return mode in ("normal", "project_admin_readonly")


def observer_mutation_blocked_response(*, record_level: bool = False):
    from flask import jsonify

    if record_level:
        return jsonify({"message": "无权修改该任务"}), 403
    return jsonify({"message": "当前为只读查看模式，不可操作"}), 403


def upload_record_mutable_by_current_user(rec: UploadRecord) -> bool:
    from .authz import upload_record_mutable_by_current_user as _mutable

    return _mutable(rec)


def _build_user_team_maps() -> tuple[dict[str, list[str]], dict[str, User], dict[str, str]]:
    users_by_key: dict[str, User] = {}
    for u in User.query.all():
        for k in (getattr(u, "username", None), getattr(u, "display_name", None)):
            s = str(k or "").strip()
            if s and s not in users_by_key:
                users_by_key[s] = u
    user_teams: dict[str, list[str]] = {}
    for m in UserTeamMembership.query.all():
        uid = str(m.user_id or "").strip()
        tid = str(m.team_id or "").strip()
        if uid and tid:
            user_teams.setdefault(uid, [])
            if tid not in user_teams[uid]:
                user_teams[uid].append(tid)
    team_names = {
        str(t.id or "").strip(): str(t.name or t.id or "").strip()
        for t in ProjectTeam.query.filter_by(is_active=True).all()
        if str(t.id or "").strip()
    }
    return user_teams, users_by_key, team_names


def upload_observer_meta(
    rec: UploadRecord,
    *,
    by_id: dict,
    by_label: dict,
    by_name: dict,
    users_by_key: dict[str, User],
    user_teams: dict[str, list[str]],
    team_names: dict[str, str],
) -> dict[str, str]:
    proj = None
    pid = str(getattr(rec, "project_id", "") or "").strip()
    if pid:
        proj = by_id.get(pid)
    if proj is None:
        label = str(getattr(rec, "project_name", "") or "").strip()
        if label:
            proj = by_label.get(label) or by_name.get(label)
    team_id = str(getattr(proj, "assigned_team_id", "") or "").strip() if proj else ""
    assignee_user_id = ""
    assignee_label = str(getattr(rec, "assignee_name", None) or getattr(rec, "author", None) or "").strip()
    for key in (
        str(getattr(rec, "assignee_name", "") or "").strip(),
        str(getattr(rec, "author", "") or "").strip(),
    ):
        if not key:
            continue
        u = users_by_key.get(key)
        if u:
            assignee_user_id = str(u.id or "").strip()
            assignee_label = str(u.display_name or u.username or assignee_label).strip()
            break
    if not team_id and assignee_user_id:
        tids = user_teams.get(assignee_user_id) or []
        team_id = tids[0] if tids else ""
    return {
        "teamId": team_id,
        "teamName": team_names.get(team_id, "") if team_id else "",
        "assigneeUserId": assignee_user_id,
        "assigneeLabel": assignee_label,
    }


def prepare_page2_observer_rows(
    rows: list[UploadRecord],
    *,
    team_id: str | None = None,
    user_id: str | None = None,
) -> tuple[list[UploadRecord], list[dict[str, str]]]:
    by_id, by_label, by_name = _project_lookup_maps()
    user_teams, users_by_key, team_names = _build_user_team_maps()
    metas: list[dict[str, str]] = []
    for rec in rows:
        metas.append(
            upload_observer_meta(
                rec,
                by_id=by_id,
                by_label=by_label,
                by_name=by_name,
                users_by_key=users_by_key,
                user_teams=user_teams,
                team_names=team_names,
            )
        )
    ftid = str(team_id or "").strip()
    fuid = str(user_id or "").strip()
    if not ftid and not fuid:
        return rows, metas
    out_rows: list[UploadRecord] = []
    out_metas: list[dict[str, str]] = []
    for rec, meta in zip(rows, metas):
        if fuid:
            a_uid = str(meta.get("assigneeUserId") or "").strip()
            a_lab = str(meta.get("assigneeLabel") or "").strip()
            if a_uid:
                if a_uid != fuid:
                    continue
            elif a_lab != fuid:
                continue
        if ftid:
            m_tid = str(meta.get("teamId") or "").strip()
            a_uid = str(meta.get("assigneeUserId") or "").strip()
            in_team = m_tid == ftid
            if not in_team and a_uid:
                in_team = ftid in set(user_teams.get(a_uid) or [])
            if not in_team:
                continue
        out_rows.append(rec)
        out_metas.append(meta)
    return out_rows, out_metas


def build_observer_filter_options(
    metas: list[dict[str, str]],
    *,
    include_teams: bool,
) -> dict[str, list[dict[str, str]]]:
    teams: list[dict[str, str]] = []
    users: list[dict[str, str]] = []
    seen_t: set[str] = set()
    seen_u: set[str] = set()
    for meta in metas:
        tid = str(meta.get("teamId") or "").strip()
        tname = str(meta.get("teamName") or "").strip()
        if include_teams and tid and tid not in seen_t:
            seen_t.add(tid)
            teams.append({"id": tid, "name": tname or tid})
        uid = str(meta.get("assigneeUserId") or "").strip()
        ulab = str(meta.get("assigneeLabel") or "").strip()
        ukey = uid or ulab
        if ukey and ukey not in seen_u:
            seen_u.add(ukey)
            users.append({"id": uid or ulab, "label": ulab or uid or ukey})
    teams.sort(key=lambda x: x.get("name") or "")
    users.sort(key=lambda x: x.get("label") or "")
    return {"teams": teams, "users": users}


def page2_query_upload_rows(*, include_history: bool, proj_meta: dict, ended: set[str]) -> list[UploadRecord]:
    from . import db
    from .models import Project

    mode = page2_view_mode()
    if mode == "normal":
        from flask import session

        username = session.get("username")
        display_name = session.get("display_name")
        q = UploadRecord.query.filter(
            db.or_(
                UploadRecord.assignee_name == username,
                UploadRecord.assignee_name == display_name,
                UploadRecord.author == username,
                UploadRecord.author == display_name,
            )
        )
    else:
        q = UploadRecord.query
    if (not include_history) and ended:
        q = q.filter(~UploadRecord.project_name.in_(list(ended)))
    rows = q.order_by(UploadRecord.sort_order.asc(), UploadRecord.created_at.asc()).all()
    if mode == "project_admin_readonly":
        rows = filter_upload_records_in_scope(rows)
    return rows


def user_team_filter_options_for_exam(
    user_ids: set[str],
    *,
    include_teams: bool,
) -> dict[str, list[dict[str, str]]]:
    from .exam_display_labels import exam_user_filter_options, human_team_name, normalize_user_key

    user_teams, _, team_names = _build_user_team_maps()
    candidate_keys: set[str] = {
        normalize_user_key(x) for x in (user_ids or []) if normalize_user_key(x)
    }

    # 观察模式下拉：除活动表 user_id 外，补齐当前 scope 内项目组成员（避免仅有 UUID 无姓名）
    try:
        from .exam_scope import (
            project_admin_team_ids_for_org,
            resolve_active_exam_filter_team_id,
            resolve_active_organization_id,
            user_ids_for_team_ids,
        )
        from .team_organizations import teams_for_organization

        org_id = resolve_active_organization_id(write_session=False)
        team_id = resolve_active_exam_filter_team_id(org_id=org_id)
        scope_team_ids: set[str] = set()
        if team_id is None:
            scope_team_ids = {str(t.id) for t in teams_for_organization(org_id, active_only=True) if str(t.id or "").strip()}
        elif team_id:
            scope_team_ids = {team_id}
        else:
            scope_team_ids = set(project_admin_team_ids_for_org(org_id))
        if scope_team_ids:
            candidate_keys.update(user_ids_for_team_ids(scope_team_ids))
    except Exception:
        pass

    users_out = exam_user_filter_options(candidate_keys)
    teams: list[dict[str, str]] = []
    seen_t: set[str] = set()
    if include_teams:
        for u in users_out:
            canonical = str(u.get("userId") or u.get("id") or "").strip()
            for tid in user_teams.get(canonical) or []:
                if tid in seen_t:
                    continue
                seen_t.add(tid)
                teams.append({"id": tid, "name": human_team_name(tid, name_cache=team_names)})
        teams.sort(key=lambda x: x.get("name") or "")
    return {"teams": teams, "users": users_out}


def exam_activity_observer_fields(
    user_id: str,
    *,
    preferred_team_id: str | None = None,
    activity_display: str | None = None,
    activity_username: str | None = None,
) -> dict[str, str]:
    from .exam_display_labels import human_user_label, normalize_user_key, resolve_user_record

    uid = normalize_user_key(user_id)
    if not uid:
        return {"teamId": "", "teamName": "", "userId": "", "displayName": ""}

    user_teams, _, team_names = _build_user_team_maps()
    u = resolve_user_record(uid)
    canonical_uid = str(getattr(u, "id", None) or uid).strip()
    act_disp = str(activity_display or "").strip() or None
    act_user = str(activity_username or "").strip() or None
    if not act_disp and u:
        act_disp = str(getattr(u, "display_name", None) or "").strip() or None
    if not act_user and u:
        act_user = str(getattr(u, "username", "") or "").strip() or None
    label = human_user_label(
        uid,
        activity_display=act_disp,
        activity_username=act_user,
    )
    tids = user_teams.get(canonical_uid) or user_teams.get(uid) or []
    pref = str(preferred_team_id or "").strip()
    tid = ""
    from .team_data_migration import DEFAULT_TEAM_NAME

    if pref:
        tid = pref
    else:
        for candidate in tids:
            if str(team_names.get(candidate, "") or "").strip() == DEFAULT_TEAM_NAME:
                tid = candidate
                break
        if not tid and tids:
            tid = tids[0]
    team_label = str(team_names.get(tid, "") or "").strip() if tid else ""
    if pref and not team_label:
        row = ProjectTeam.query.get(pref)
        team_label = str(getattr(row, "name", None) or pref).strip() if row else pref
    return {
        "teamId": tid,
        "teamName": team_label,
        "userId": canonical_uid,
        "displayName": label,
    }
