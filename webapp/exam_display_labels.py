# -*- coding: utf-8 -*-
"""考试中心筛选项：展示用中文名/业务名，避免下拉直接显示 UUID 或内部 id。"""
from __future__ import annotations

import re

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


_EMBEDDED_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.I,
)
_WRAPPER_OPEN = "([{<（【［《「『\"'“‘"
_WRAPPER_CLOSE = ")]}>）】］》」』\"'”’"


def extract_embedded_uuid(text: str | None) -> str:
    m = _EMBEDDED_UUID_RE.search(str(text or "").strip())
    return m.group(0) if m else ""


def _compact_uuid_hex(text: str) -> str:
    return re.sub(r"[^0-9a-f]", "", str(text or ""), flags=re.I)


def normalize_user_key(user_key: str | None) -> str:
    """去掉首尾空白及各类括号，提取嵌入的 UUID。"""
    s = str(user_key or "").strip()
    if not s:
        return ""
    for _ in range(4):
        changed = False
        if len(s) >= 2 and s[0] in _WRAPPER_OPEN and s[-1] in _WRAPPER_CLOSE:
            inner = s[1:-1].strip()
            if inner:
                s = inner
                changed = True
        emb = extract_embedded_uuid(s)
        if emb:
            compact = _compact_uuid_hex(s)
            emb_compact = _compact_uuid_hex(emb)
            if compact == emb_compact or _UUID_RE.match(s):
                s = emb
                changed = True
        if not changed:
            break
    return s


def looks_like_opaque_id(text: str | None) -> bool:
    s = str(text or "").strip()
    if not s:
        return True
    nk = normalize_user_key(s)
    if nk and _UUID_RE.match(nk):
        return True
    if _UUID_RE.match(s):
        return True
    emb = extract_embedded_uuid(s)
    if emb:
        if _compact_uuid_hex(s) == _compact_uuid_hex(emb):
            return True
        if len(s) <= len(emb) + 4:
            return True
    if len(s) >= 32 and re.fullmatch(r"[0-9a-f-]+", s, re.I):
        return True
    return False


def activity_user_id_lookup_keys(keys: set[str] | list[str]) -> set[str]:
    """DB 中 user_id 可能带括号或与 canonical id 混存，查询时扩展匹配键。"""
    out: set[str] = set()
    for k in keys or []:
        raw = str(k or "").strip()
        nk = normalize_user_key(raw)
        if raw:
            out.add(raw)
        if nk:
            out.add(nk)
            out.add(f"({nk})")
    return {x for x in out if x}


def resolve_user_record(user_key: str | None):
    """按 User.id、username 或 display_name 解析账号（兼容 activity.user_id 混存）。"""
    from .models import User

    uid = normalize_user_key(user_key)
    if not uid:
        return None
    u = User.query.get(uid)
    if u is not None:
        return u
    u = User.query.filter_by(username=uid).first()
    if u is not None:
        return u
    return User.query.filter_by(display_name=uid).first()


def exam_activity_user_id_match_keys(user_key: str) -> set[str]:
    """活动表 user_id 可能与 User.id 或 username 混存，筛选用并集。"""
    keys: set[str] = set()
    raw = normalize_user_key(user_key)
    if raw:
        keys.add(raw)
    u = resolve_user_record(raw)
    if u:
        keys.add(str(getattr(u, "id", "") or "").strip())
        un = str(getattr(u, "username", "") or "").strip()
        if un:
            keys.add(un)
        dn = str(getattr(u, "display_name", "") or "").strip()
        if dn:
            keys.add(dn)
    return {k for k in keys if k}


def user_preferred_label(user) -> str:
    if user is None:
        return ""
    for attr in ("display_name", "username"):
        s = str(getattr(user, attr, None) or "").strip()
        if s and not looks_like_opaque_id(s):
            return s
    return ""


def _is_placeholder_user_label(text: str | None) -> bool:
    s = str(text or "").strip()
    return not s or s in ("未知用户", "未命名", "-")


def human_user_label(
    user_id: str,
    *,
    activity_display: str | None = None,
    activity_username: str | None = None,
) -> str:
    for raw in (activity_display, activity_username):
        s = str(raw or "").strip()
        if s and not looks_like_opaque_id(s) and not _is_placeholder_user_label(s):
            return s
    uid = normalize_user_key(user_id)
    u = resolve_user_record(uid)
    if u:
        s = user_preferred_label(u)
        if s:
            return s
    if uid and not looks_like_opaque_id(uid):
        return uid
    return "未知用户"


def exam_user_filter_options(raw_user_keys: set[str] | list[str]) -> list[dict[str, str]]:
    """学生端/统计端人员下拉：严格按 User.id 去重，禁止 UUID/括号 id 作为展示名。"""
    from .models import ExamCenterActivity, User
    from sqlalchemy import or_

    candidate_keys: set[str] = set()
    for x in raw_user_keys or []:
        raw = str(x or "").strip()
        if not raw:
            continue
        candidate_keys.add(raw)
        nk = normalize_user_key(raw)
        if nk:
            candidate_keys.add(nk)
        emb = extract_embedded_uuid(raw)
        if emb:
            candidate_keys.add(emb)

    if not candidate_keys:
        return []

    lookup_keys: set[str] = set()
    for raw in candidate_keys:
        lookup_keys.update(exam_activity_user_id_match_keys(raw))
    if not lookup_keys:
        lookup_keys = set(candidate_keys)

    users = User.query.filter(
        or_(
            User.id.in_(list(lookup_keys)),
            User.username.in_(list(lookup_keys)),
            User.display_name.in_(list(lookup_keys)),
        )
    ).all()
    user_by_id = {str(u.id): u for u in users if getattr(u, "id", None)}

    act_rows = (
        ExamCenterActivity.query.filter(
            ExamCenterActivity.user_id.in_(list(activity_user_id_lookup_keys(lookup_keys)))
        )
        .order_by(ExamCenterActivity.user_id.asc(), ExamCenterActivity.created_at.desc())
        .all()
    )
    act_by_key: dict[str, ExamCenterActivity] = {}
    for a in act_rows:
        k = normalize_user_key(getattr(a, "user_id", "") or "")
        if k and k not in act_by_key:
            act_by_key[k] = a

    canonical_users: dict[str, User] = {}
    for key in candidate_keys:
        u = user_by_id.get(normalize_user_key(key)) or resolve_user_record(key)
        if u and getattr(u, "id", None):
            canonical_users[str(u.id).strip()] = u

    out_by_id: dict[str, dict[str, str]] = {}
    for canonical, u in canonical_users.items():
        act = act_by_key.get(canonical)
        if act is None:
            for alt in exam_activity_user_id_match_keys(canonical):
                act = act_by_key.get(alt)
                if act is not None:
                    break
        act_disp = str(getattr(act, "display_name", None) or "").strip() if act else ""
        act_user = str(getattr(act, "username", None) or "").strip() if act else ""
        label = human_user_label(
            canonical,
            activity_display=act_disp or None,
            activity_username=act_user or user_preferred_label(u) or None,
        )
        if _is_placeholder_user_label(label) or looks_like_opaque_id(label):
            continue
        out_by_id[canonical] = {
            "id": canonical,
            "userId": canonical,
            "label": label,
            "name": label,
            "username": str(getattr(u, "username", "") or act_user or "").strip() or None,
            "display_name": label,
        }

    users_out = sorted(out_by_id.values(), key=lambda x: str(x.get("label") or ""))
    return _filter_exam_user_filter_options(users_out)


def _filter_exam_user_filter_options(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """去掉纯 UUID 标签项，并按展示名与 canonical user id 去重。"""
    seen_labels: set[str] = set()
    seen_uids: set[str] = set()
    out: list[dict[str, str]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        uid = normalize_user_key(str(item.get("userId") or item.get("id") or ""))
        if uid and uid in seen_uids:
            continue
        lab = str(item.get("label") or item.get("name") or "").strip()
        un = str(item.get("username") or "").strip()
        if (not lab or looks_like_opaque_id(lab)) and un and not looks_like_opaque_id(un):
            lab = un
            item = {**item, "label": lab, "name": lab, "display_name": lab}
        if not lab or _is_placeholder_user_label(lab) or looks_like_opaque_id(lab):
            continue
        key = lab.casefold()
        if key in seen_labels:
            continue
        seen_labels.add(key)
        if uid:
            seen_uids.add(uid)
        out.append(item)
    return out


def activity_display_names_for_users(user_ids: set[str] | list[str]) -> dict[str, str]:
    """从 exam_center_activities 取各 user_id 最近一条活动的展示名（与统计端下拉同源）。"""
    ids = [normalize_user_key(x) for x in (user_ids or [])]
    ids = [x for x in ids if x]
    if not ids:
        return {}
    from .models import ExamCenterActivity

    lookup_keys: set[str] = set()
    for i in ids:
        lookup_keys.update(exam_activity_user_id_match_keys(i))
    if not lookup_keys:
        lookup_keys = set(ids)

    out: dict[str, str] = {}
    rows = (
        ExamCenterActivity.query.filter(
            ExamCenterActivity.user_id.in_(list(activity_user_id_lookup_keys(lookup_keys)))
        )
        .order_by(ExamCenterActivity.user_id.asc(), ExamCenterActivity.created_at.desc())
        .all()
    )
    act_by_key: dict[str, ExamCenterActivity] = {}
    for r in rows:
        k = normalize_user_key(getattr(r, "user_id", "") or "")
        if k and k not in act_by_key:
            act_by_key[k] = r

    def _label_for_activity(act: ExamCenterActivity | None, uid: str) -> str:
        if act:
            nm = str(getattr(act, "display_name", None) or getattr(act, "username", None) or "").strip()
            if nm and not looks_like_opaque_id(nm):
                return nm
        u = resolve_user_record(uid)
        if u:
            nm2 = str(getattr(u, "display_name", None) or getattr(u, "username", None) or "").strip()
            if nm2:
                return nm2
        return ""

    for req_uid in ids:
        if req_uid in out:
            continue
        act = act_by_key.get(req_uid)
        if act is None:
            for alt in exam_activity_user_id_match_keys(req_uid):
                act = act_by_key.get(alt)
                if act is not None:
                    break
        lab = _label_for_activity(act, req_uid)
        if lab:
            out[req_uid] = lab
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
