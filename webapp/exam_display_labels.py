# -*- coding: utf-8 -*-
"""考试中心筛选项：展示用中文名/业务名，避免下拉直接显示 UUID 或内部 id。"""
from __future__ import annotations

import re

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


def looks_like_opaque_id(text: str | None) -> bool:
    s = str(text or "").strip()
    if not s:
        return True
    if _UUID_RE.match(s):
        return True
    if len(s) >= 32 and re.fullmatch(r"[0-9a-f-]+", s, re.I):
        return True
    return False


def human_user_label(user_id: str, *, activity_display: str | None = None) -> str:
    from .models import User

    for raw in (activity_display,):
        s = str(raw or "").strip()
        if s and not looks_like_opaque_id(s):
            return s
    uid = str(user_id or "").strip()
    if uid:
        u = User.query.get(uid)
        if u is None and not looks_like_opaque_id(uid):
            u = User.query.filter_by(username=uid).first()
        if u:
            s = str(getattr(u, "display_name", None) or getattr(u, "username", None) or "").strip()
            if s:
                return s
    return "未知用户"


def activity_display_names_for_users(user_ids: set[str] | list[str]) -> dict[str, str]:
    """从 exam_center_activities 取各 user_id 最近一条活动的展示名（与统计端下拉同源）。"""
    ids = [str(x).strip() for x in (user_ids or []) if str(x or "").strip()]
    if not ids:
        return {}
    from .models import ExamCenterActivity

    out: dict[str, str] = {}
    rows = (
        ExamCenterActivity.query.filter(ExamCenterActivity.user_id.in_(ids))
        .order_by(ExamCenterActivity.user_id.asc(), ExamCenterActivity.created_at.desc())
        .all()
    )
    for r in rows:
        uid = str(getattr(r, "user_id", "") or "").strip()
        if not uid or uid in out:
            continue
        nm = str(getattr(r, "display_name", None) or getattr(r, "username", None) or "").strip()
        if nm and not looks_like_opaque_id(nm):
            out[uid] = nm
    return out


def human_team_name(team_id: str, *, name_cache: dict[str, str] | None = None) -> str:
    from .models import ProjectTeam

    tid = str(team_id or "").strip()
    if not tid:
        return "未命名项目组"
    cache = name_cache or {}
    cached = str(cache.get(tid, "") or "").strip()
    if cached and not looks_like_opaque_id(cached):
        return cached
    row = ProjectTeam.query.get(tid)
    nm = str(getattr(row, "name", None) or "").strip() if row else ""
    if nm and not looks_like_opaque_id(nm):
        return nm
    return "未命名项目组"


def human_assignment_label(
    assignment_id: str,
    *,
    activity_label: str | None = None,
    title: str | None = None,
) -> str:
    from .models import ExamCenterAssignment

    for raw in (title, activity_label):
        s = str(raw or "").strip()
        if s and not looks_like_opaque_id(s):
            return s
    aid = str(assignment_id or "").strip()
    if aid:
        row = ExamCenterAssignment.query.filter_by(assignment_id=aid).first()
        if row:
            s = str(getattr(row, "title", None) or "").strip()
            if s and not looks_like_opaque_id(s):
                return s
    return "未命名考试任务"
