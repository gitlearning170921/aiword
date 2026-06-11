# -*- coding: utf-8 -*-
"""按项目组解析钉钉 webhook/secret（缺失时回退默认项目组，再回退全局配置）。"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .models import Project, ProjectTeam, UploadRecord


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
    return _team_id_from_project(_project_for_label(project_name))


def resolve_team_id_by_upload(rec: UploadRecord | None) -> str | None:
    if rec is None:
        return None
    from .authz import resolve_project_for_upload

    return _team_id_from_project(resolve_project_for_upload(rec))


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
    out: dict[str | None, list[UploadRecord]] = defaultdict(list)
    for rec in uploads:
        if proj_meta is not None:
            tid = resolve_team_id_by_upload_with_meta(rec, proj_meta)
        else:
            tid = resolve_team_id_by_upload(rec)
        out[tid].append(rec)
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
        out[tid].add(pn)
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


def resolve_dingtalk_credentials(
    team_id: str | None,
    *,
    for_scheduler: bool = False,
) -> tuple[str, str | None, str]:
    tid = (team_id or "").strip()
    if tid:
        team = ProjectTeam.query.get(tid)
        if team:
            webhook = (getattr(team, "dingtalk_webhook", None) or "").strip()
            secret = (getattr(team, "dingtalk_secret", None) or "").strip() or None
            if webhook:
                return webhook, secret, "team"
    webhook, secret = _default_team_dingtalk_credentials(for_scheduler=for_scheduler)
    if webhook:
        return webhook, secret, "default_team"
    webhook, secret = _global_dingtalk_credentials(for_scheduler=for_scheduler)
    return webhook, secret, "global"
