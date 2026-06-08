# -*- coding: utf-8 -*-
"""项目组 ↔ 公司多对多解析（兼容 project_teams.organization_id）。"""
from __future__ import annotations

from typing import Any, Iterable

from . import db
from .models import Organization, ProjectTeam, ProjectTeamOrganization

_EXAM_SMOKE_PREFIX = "exam_smoke_"


def _dedupe_ids(raw: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in raw:
        s = str(x or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def organization_ids_for_team(team_id: str) -> list[str]:
    tid = str(team_id or "").strip()
    if not tid:
        return []
    rows = ProjectTeamOrganization.query.filter_by(team_id=tid).order_by(
        ProjectTeamOrganization.created_at.asc()
    ).all()
    ids = _dedupe_ids(str(r.organization_id) for r in rows)
    if ids:
        return ids
    team = ProjectTeam.query.get(tid)
    legacy = str(getattr(team, "organization_id", "") or "").strip()
    return [legacy] if legacy else []


def organization_ids_for_teams(team_ids: Iterable[str]) -> list[str]:
    merged: list[str] = []
    for tid in team_ids:
        for oid in organization_ids_for_team(str(tid or "").strip()):
            if oid and oid not in merged:
                merged.append(oid)
    return merged


def teams_for_organization(org_id: str, *, active_only: bool = True) -> list[ProjectTeam]:
    oid = str(org_id or "").strip()
    if not oid:
        return []
    junction_team_ids = {
        str(r.team_id or "").strip()
        for r in ProjectTeamOrganization.query.filter_by(organization_id=oid).all()
        if str(r.team_id or "").strip()
    }
    base_q = ProjectTeam.query
    if active_only:
        base_q = base_q.filter_by(is_active=True)
    legacy_rows = base_q.filter(ProjectTeam.organization_id == oid).all()
    all_ids = junction_team_ids | {str(r.id or "").strip() for r in legacy_rows if str(r.id or "").strip()}
    if not all_ids:
        return []
    q = ProjectTeam.query.filter(ProjectTeam.id.in_(list(all_ids)))
    if active_only:
        q = q.filter_by(is_active=True)
    rows = q.order_by(ProjectTeam.sort_order.asc(), ProjectTeam.name.asc()).all()
    out: list[ProjectTeam] = []
    for team in rows:
        name = str(team.name or "").strip()
        if name.lower().startswith(_EXAM_SMOKE_PREFIX):
            continue
        out.append(team)
    return out


def count_teams_for_organization(org_id: str) -> int:
    return len(teams_for_organization(org_id, active_only=False))


def organization_has_team(org_id: str) -> bool:
    oid = str(org_id or "").strip()
    if not oid:
        return False
    if ProjectTeamOrganization.query.filter_by(organization_id=oid).limit(1).first():
        return True
    return bool(ProjectTeam.query.filter_by(organization_id=oid).limit(1).first())


def set_team_organization_ids(team_id: str, org_ids: Iterable[str]) -> None:
    tid = str(team_id or "").strip()
    if not tid:
        return
    normalized = _dedupe_ids(str(x or "").strip() for x in org_ids if str(x or "").strip())
    if normalized:
        valid = {
            str(r.id or "").strip()
            for r in Organization.query.filter(
                Organization.id.in_(normalized),
                Organization.is_active.is_(True),
            ).all()
            if str(r.id or "").strip()
        }
        normalized = [x for x in normalized if x in valid]
    ProjectTeamOrganization.query.filter_by(team_id=tid).delete(synchronize_session=False)
    for oid in normalized:
        db.session.add(ProjectTeamOrganization(team_id=tid, organization_id=oid))
    team = ProjectTeam.query.get(tid)
    if team:
        team.organization_id = normalized[0] if normalized else None
        db.session.add(team)


def sync_legacy_team_organization(team: ProjectTeam, organization_id: str | None) -> None:
    """写入 legacy 列并同步 junction（单公司绑定场景）。"""
    tid = str(getattr(team, "id", "") or "").strip()
    if not tid:
        return
    oid = str(organization_id or "").strip()
    if oid:
        set_team_organization_ids(tid, [oid])
    else:
        set_team_organization_ids(tid, [])


def organization_labels_for_team(team_id: str) -> list[dict[str, str]]:
    ids = organization_ids_for_team(team_id)
    if not ids:
        return []
    rows = Organization.query.filter(Organization.id.in_(ids)).all()
    by_id = {str(r.id or "").strip(): r for r in rows}
    out: list[dict[str, str]] = []
    for oid in ids:
        row = by_id.get(oid)
        if not row:
            continue
        out.append(
            {
                "id": oid,
                "name": str(row.name or oid).strip() or oid,
            }
        )
    return out


def organizations_payload_for_ids(org_ids: Iterable[str]) -> list[dict[str, Any]]:
    ids = _dedupe_ids(str(x or "").strip() for x in org_ids)
    if not ids:
        return []
    rows = (
        Organization.query.filter(
            Organization.id.in_(ids),
            Organization.is_active.is_(True),
        )
        .order_by(Organization.is_default.desc(), Organization.created_at.asc())
        .all()
    )
    by_id = {str(r.id or "").strip(): r for r in rows}
    out: list[dict[str, Any]] = []
    for oid in ids:
        row = by_id.get(oid)
        if not row:
            continue
        kc = str(row.knowledge_collection or "regulations").strip() or "regulations"
        out.append(
            {
                "id": oid,
                "name": str(row.name or oid).strip() or oid,
                "knowledgeCollection": kc,
                "label": f"{str(row.name or oid).strip()} ({kc})",
                "isDefault": bool(getattr(row, "is_default", False)),
            }
        )
    return out


def backfill_junction_from_legacy() -> int:
    """从 project_teams.organization_id 回填 junction 表（幂等）。"""
    n = 0
    for team in ProjectTeam.query.all():
        tid = str(team.id or "").strip()
        legacy = str(getattr(team, "organization_id", "") or "").strip()
        if not tid or not legacy:
            continue
        exists = ProjectTeamOrganization.query.filter_by(team_id=tid, organization_id=legacy).first()
        if exists:
            continue
        db.session.add(ProjectTeamOrganization(team_id=tid, organization_id=legacy))
        n += 1
    if n:
        db.session.commit()
    return n
