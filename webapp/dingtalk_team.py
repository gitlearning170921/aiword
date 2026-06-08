# -*- coding: utf-8 -*-
"""按项目组解析钉钉 webhook/secret（缺失时回退默认项目组，再回退全局配置）。"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .authz import project_display_label
from .models import Project, ProjectTeam, UploadRecord


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


def resolve_team_id_by_project_name(project_name: str | None) -> str | None:
    label = (project_name or "").strip()
    if not label:
        return None
    for p in Project.query.all():
        if project_display_label(
            getattr(p, "name", None),
            getattr(p, "registered_country", None),
            getattr(p, "registered_category", None),
        ) == label:
            tid = (getattr(p, "assigned_team_id", None) or "").strip()
            return tid or None
    return None


def resolve_team_id_by_upload(rec: UploadRecord | None) -> str | None:
    if rec is None:
        return None
    pid = (getattr(rec, "project_id", None) or "").strip()
    if pid:
        p = Project.query.get(pid)
        if p:
            tid = (getattr(p, "assigned_team_id", None) or "").strip()
            if tid:
                return tid
    return resolve_team_id_by_project_name(getattr(rec, "project_name", None))


def group_uploads_by_team(uploads: Iterable[UploadRecord]) -> dict[str | None, list[UploadRecord]]:
    out: dict[str | None, list[UploadRecord]] = defaultdict(list)
    for rec in uploads:
        out[resolve_team_id_by_upload(rec)].append(rec)
    return dict(out)
