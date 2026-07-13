"""页面1 项目身份：优先 project_id，否则按项目名称 + 注册国家联合判等。"""
from __future__ import annotations

import re
from typing import Optional

from webapp.document_control.subtype_resolver import normalize_title_key
from webapp.models import Project

_SCOPE_SPLIT_RE = re.compile(r"[,，、]|\s*/\s*")


def scope_field_tokens(value: Optional[str]) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    return [p.strip() for p in _SCOPE_SPLIT_RE.split(text) if p and p.strip()]


def registered_country_identity_part(value: Optional[str]) -> str:
    keys: list[str] = []
    seen: set[str] = set()
    for token in scope_field_tokens(value):
        key = normalize_title_key(token)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return "|".join(sorted(keys))


def project_identity_key(
    project_id: Optional[str],
    project_name: Optional[str],
    registered_country: Optional[str] = None,
) -> str:
    pid = (project_id or "").strip()
    if pid:
        return f"id:{pid}"
    name_key = normalize_title_key(project_name or "")
    rc_key = registered_country_identity_part(registered_country)
    if name_key and rc_key:
        return f"name:{name_key}|rc:{rc_key}"
    if name_key:
        return f"name:{name_key}"
    return ""


def countries_identity_match(
    left: Optional[str],
    right: Optional[str],
) -> bool:
    a = registered_country_identity_part(left)
    b = registered_country_identity_part(right)
    if not a or not b:
        return not a and not b
    return a == b


def find_page1_project(
    *,
    project_name: Optional[str] = None,
    registered_country: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Optional[Project]:
    pid = (project_id or "").strip()
    if pid:
        return Project.query.get(pid)

    from webapp.authz import _project_lookup_maps, project_display_label

    label = (project_name or "").strip()
    if not label:
        return None

    _by_id, by_label, by_name = _project_lookup_maps()
    hit = by_label.get(label)
    if hit:
        return hit

    name_key = normalize_title_key(label)
    rc_key = registered_country_identity_part(registered_country)
    candidates: list[Project] = []
    for proj in _by_id.values():
        if normalize_title_key(getattr(proj, "name", None) or "") == name_key:
            candidates.append(proj)
    if not candidates:
        return by_name.get(label)

    if not rc_key:
        return candidates[0] if len(candidates) == 1 else None

    matched = [
        p
        for p in candidates
        if countries_identity_match(
            getattr(p, "registered_country", None),
            registered_country,
        )
    ]
    if len(matched) == 1:
        return matched[0]
    if not matched and len(candidates) == 1:
        only = candidates[0]
        if not (getattr(only, "registered_country", None) or "").strip():
            return only
    return None


def resolve_registered_country_for_context(
    *,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
    registered_country: Optional[str] = None,
) -> Optional[str]:
    explicit = (registered_country or "").strip()
    if explicit:
        return explicit
    proj = find_page1_project(
        project_id=project_id,
        project_name=project_name,
    )
    if proj:
        rc = (getattr(proj, "registered_country", None) or "").strip()
        if rc:
            return rc
    return None
