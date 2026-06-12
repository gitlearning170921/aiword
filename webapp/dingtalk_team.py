# -*- coding: utf-8 -*-
"""按项目组解析钉钉 webhook/secret（缺失时回退默认项目组，再回退全局配置）。"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .models import Project, ProjectTeam, UploadRecord


def _norm_team_id(team_id: str | None) -> str | None:
    tid = (team_id or "").strip()
    return tid or None


def _team_id_from_project(project: Project | None) -> str | None:
    if project is None:
        return None
    tid = (getattr(project, "assigned_team_id", None) or "").strip()
    return tid or None


def _project_for_label(project_name: str | None) -> Project | None:
    """与 authz.resolve_project_for_upload 一致：按展示名 / 基础名匹配项目。"""
    label = (project_name or "").strip()
    if not label:
        return None
    from .authz import _project_lookup_maps

    _by_id, by_label, by_name = _project_lookup_maps()
    return by_label.get(label) or by_name.get(label)


def resolve_team_id_by_project_name(project_name: str | None) -> str | None:
    label = (project_name or "").strip()
    if not label:
        return None
    _by_id, by_label, by_name = build_project_team_maps()
    if label in by_label:
        return by_label[label]
    if label in by_name:
        return by_name[label]
    return _team_id_from_project(_project_for_label(label))


def resolve_team_id_by_upload(rec: UploadRecord | None) -> str | None:
    if rec is None:
        return None
    from .authz import resolve_project_for_upload

    maps = build_project_team_maps()
    tid = upload_team_id_from_maps(rec, maps)
    if tid:
        return tid
    return _team_id_from_project(resolve_project_for_upload(rec))


def upload_team_id_from_maps(
    rec: UploadRecord | None,
    maps: tuple[dict[str, str | None], dict[str, str | None], dict[str, str | None]],
) -> str | None:
    """定时催办：以 Project.assigned_team_id 为准（project_id → 展示名 → 基础名）。"""
    if rec is None:
        return None
    by_id, by_label, by_name = maps
    pid = (getattr(rec, "project_id", None) or "").strip()
    if pid and pid in by_id:
        return by_id[pid]
    label = (getattr(rec, "project_name", None) or "").strip()
    if not label:
        return None
    if label in by_label:
        return by_label[label]
    if label in by_name:
        return by_name[label]
    return None


def build_project_team_maps() -> tuple[dict[str, str | None], dict[str, str | None], dict[str, str | None]]:
    """project_id / 展示名 / 基础名 → 所属项目组 id（Project.assigned_team_id）。"""
    from .authz import project_display_label

    by_id: dict[str, str | None] = {}
    by_label: dict[str, str | None] = {}
    by_name: dict[str, str | None] = {}
    for r in Project.query.all():
        tid = _norm_team_id(getattr(r, "assigned_team_id", None))
        rid = (getattr(r, "id", None) or "").strip()
        if rid:
            by_id[rid] = tid
        label = project_display_label(
            getattr(r, "name", None),
            getattr(r, "registered_country", None),
            getattr(r, "registered_category", None),
        )
        if label:
            by_label[label] = tid
        name = (getattr(r, "name", None) or "").strip()
        if name:
            by_name[name] = tid
    return by_id, by_label, by_name


def iter_teams_with_dedicated_webhook() -> Iterable[tuple[str, str, str, str | None]]:
    """已配置独立 Webhook 的活跃项目组（不含与全局相同的 URL）。"""
    from .project_teams import team_dingtalk_webhook_for_settings

    teams = (
        ProjectTeam.query.filter_by(is_active=True)
        .order_by(ProjectTeam.sort_order.asc(), ProjectTeam.created_at.asc())
        .all()
    )
    for team in teams:
        webhook = team_dingtalk_webhook_for_settings(team)
        if not webhook:
            continue
        tid = (team.id or "").strip()
        if not tid:
            continue
        name = (team.name or "").strip() or tid
        secret = (getattr(team, "dingtalk_secret", None) or "").strip() or None
        yield tid, name, webhook, secret


def dedicated_webhook_team_ids() -> frozenset[str]:
    return frozenset(tid for tid, _name, _wh, _sec in iter_teams_with_dedicated_webhook())


def resolve_team_id_by_upload_with_meta(
    rec: UploadRecord | None,
    proj_meta: dict | None = None,
) -> str | None:
    """定时任务侧：upload → 项目 → 项目组；再回退 proj_meta[project_name].team_id。"""
    tid = resolve_team_id_by_upload(rec)
    if tid:
        return tid
    if not proj_meta or rec is None:
        return None
    pn = (getattr(rec, "project_name", None) or "").strip()
    if not pn:
        return None
    m = proj_meta.get(pn) or {}
    fallback = (m.get("team_id") or "").strip()
    return fallback or None


def group_uploads_by_team(
    uploads: Iterable[UploadRecord],
    *,
    proj_meta: dict | None = None,
) -> dict[str | None, list[UploadRecord]]:
    from .authz import resolve_project_for_upload

    maps = build_project_team_maps()
    out: dict[str | None, list[UploadRecord]] = defaultdict(list)
    for rec in uploads:
        tid = upload_team_id_from_maps(rec, maps)
        if not tid and proj_meta is not None:
            tid = resolve_team_id_by_upload_with_meta(rec, proj_meta)
        if not tid:
            tid = _team_id_from_project(resolve_project_for_upload(rec))
        out[_norm_team_id(tid)].append(rec)
    return dict(out)


def group_project_names_by_team(
    uploads: Iterable[UploadRecord],
    *,
    proj_meta: dict | None = None,
) -> dict[str | None, set[str]]:
    out: dict[str | None, set[str]] = defaultdict(set)
    for rec in uploads:
        pn = (getattr(rec, "project_name", None) or "").strip()
        if not pn:
            continue
        if proj_meta is not None:
            tid = resolve_team_id_by_upload_with_meta(rec, proj_meta)
        else:
            tid = resolve_team_id_by_upload(rec)
        out[_norm_team_id(tid)].add(pn)
    return dict(out)


def _default_team_dingtalk_credentials(*, for_scheduler: bool = False) -> tuple[str, str | None]:
    """互联网产品部（或首个活跃项目组）的 webhook/secret，作为项目组未配置时的默认机器人。"""
    from .team_data_migration import DEFAULT_TEAM_NAME

    team = (
        ProjectTeam.query.filter_by(name=DEFAULT_TEAM_NAME, is_active=True)
        .order_by(ProjectTeam.sort_order.asc(), ProjectTeam.created_at.asc())
        .first()
    )
    if not team:
        team = (
            ProjectTeam.query.filter_by(is_active=True)
            .order_by(ProjectTeam.sort_order.asc(), ProjectTeam.created_at.asc())
            .first()
        )
    if not team:
        return "", None
    webhook = (getattr(team, "dingtalk_webhook", None) or "").strip()
    secret = (getattr(team, "dingtalk_secret", None) or "").strip() or None
    return webhook, secret


def _global_dingtalk_credentials(*, for_scheduler: bool = False):
    if for_scheduler:
        from .scheduler import _app as scheduler_app
        from .app_settings import get_setting_for_scheduler

        app = scheduler_app
        if app is None:
            return "", None
        webhook = (get_setting_for_scheduler("DINGTALK_WEBHOOK", default="", app=app) or "").strip()
        secret = (get_setting_for_scheduler("DINGTALK_SECRET", default="", app=app) or "").strip() or None
        return webhook, secret
    from .app_settings import get_setting

    webhook = (get_setting("DINGTALK_WEBHOOK") or "").strip()
    secret = (get_setting("DINGTALK_SECRET") or "").strip() or None
    return webhook, secret


def notify_routing_meta(team_id: str | None, *, for_scheduler: bool = False) -> dict[str, object]:
    """催办路由诊断：解析到的项目组与 Webhook 来源。"""
    tid = _norm_team_id(team_id)
    team_name = ""
    if tid:
        team = ProjectTeam.query.get(tid)
        team_name = (getattr(team, "name", None) or "").strip() if team else ""
    _wh, _sec, source = resolve_dingtalk_credentials(tid, for_scheduler=for_scheduler)
    dedicated_ids = dedicated_webhook_team_ids()
    return {
        "teamId": tid,
        "teamName": team_name or None,
        "webhookSource": source,
        "usesDedicatedWebhook": bool(tid and tid in dedicated_ids and source == "team"),
    }


def resolve_dingtalk_credentials(
    team_id: str | None,
    *,
    for_scheduler: bool = False,
) -> tuple[str, str | None, str]:
    """解析催办 Webhook：优先项目组独立配置（team_dingtalk_webhook_for_settings），再回退默认组/全局。"""
    from .project_teams import team_dingtalk_webhook_for_settings

    tid = (team_id or "").strip()
    if tid:
        team = ProjectTeam.query.get(tid)
        if team:
            webhook = team_dingtalk_webhook_for_settings(team)
            secret = (getattr(team, "dingtalk_secret", None) or "").strip() or None
            if webhook:
                return webhook, secret, "team"
    webhook, secret = _default_team_dingtalk_credentials(for_scheduler=for_scheduler)
    if webhook:
        return webhook, secret, "default_team"
    webhook, secret = _global_dingtalk_credentials(for_scheduler=for_scheduler)
    return webhook, secret, "global"
