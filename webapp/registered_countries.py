# -*- coding: utf-8 -*-
"""注册国家字典：仅在页面0 维护；其他页面只能从字典中选择。"""
from __future__ import annotations

from typing import Any, Optional

from . import db
from .models import CompanyProject, Project, RegisteredCountry, UserCountryScope


def normalize_registered_country(raw: Any) -> Optional[str]:
    s = ("" if raw is None else str(raw)).strip()
    return s if s else None


def list_registered_countries(*, active_only: bool = True) -> list[str]:
    q = RegisteredCountry.query
    if active_only:
        q = q.filter(RegisteredCountry.is_active.is_(True))
    rows = q.order_by(
        RegisteredCountry.sort_order.asc(),
        RegisteredCountry.name.asc(),
    ).all()
    return [str(r.name).strip() for r in rows if str(r.name).strip()]


def registered_country_usage(name: str) -> dict[str, int]:
    n = normalize_registered_country(name)
    if not n:
        return {
            "companyProjects": 0,
            "projects": 0,
            "userScopes": 0,
            "total": 0,
        }
    cp = CompanyProject.query.filter(CompanyProject.registered_country == n).count()
    pr = Project.query.filter(Project.registered_country == n).count()
    us = UserCountryScope.query.filter(UserCountryScope.registered_country == n).count()
    return {
        "companyProjects": cp,
        "projects": pr,
        "userScopes": us,
        "total": cp + pr + us,
    }


def list_registered_country_items(*, active_only: bool = False) -> list[dict[str, Any]]:
    q = RegisteredCountry.query
    if active_only:
        q = q.filter(RegisteredCountry.is_active.is_(True))
    rows = q.order_by(
        RegisteredCountry.sort_order.asc(),
        RegisteredCountry.name.asc(),
    ).all()
    out: list[dict[str, Any]] = []
    for r in rows:
        name = str(r.name).strip()
        if not name:
            continue
        usage = registered_country_usage(name)
        out.append(
            {
                "id": r.id,
                "name": name,
                "sortOrder": int(r.sort_order or 0),
                "isActive": bool(r.is_active),
                "usageCount": usage["total"],
                "usage": usage,
                "canDelete": True,
                "requiresCascadeConfirm": usage["total"] > 0,
            }
        )
    return out


def resolve_registered_country_selection(raw: Any) -> Optional[str]:
    """仅当字典中已存在且启用时返回规范名（不自动新增）。"""
    name = normalize_registered_country(raw)
    if not name:
        return None
    row = RegisteredCountry.query.filter_by(name=name, is_active=True).first()
    return name if row else None


def add_registered_country_to_dict(raw: Any) -> RegisteredCountry:
    """页面0 维护：新增或重新启用字典项。"""
    name = normalize_registered_country(raw)
    if not name:
        raise ValueError("注册国家名称不能为空")
    row = RegisteredCountry.query.filter_by(name=name).first()
    if row:
        row.is_active = True
        db.session.add(row)
        return row
    row = RegisteredCountry(name=name, sort_order=0, is_active=True)
    db.session.add(row)
    return row


def update_registered_country_name(country_id: str, new_name_raw: Any) -> tuple[RegisteredCountry | None, str | None]:
    row = RegisteredCountry.query.get(country_id)
    if not row:
        return None, "未找到该字典项"
    new_name = normalize_registered_country(new_name_raw)
    if not new_name:
        return None, "国家名称不能为空"
    old_name = str(row.name).strip()
    if new_name == old_name:
        return row, None
    other = RegisteredCountry.query.filter(
        RegisteredCountry.id != country_id, RegisteredCountry.name == new_name
    ).first()
    if other:
        return None, "该国家名称已存在"
    row.name = new_name
    db.session.add(row)
    if old_name:
        CompanyProject.query.filter(CompanyProject.registered_country == old_name).update(
            {"registered_country": new_name}, synchronize_session=False
        )
        Project.query.filter(Project.registered_country == old_name).update(
            {"registered_country": new_name}, synchronize_session=False
        )
        UserCountryScope.query.filter(
            UserCountryScope.registered_country == old_name
        ).update({"registered_country": new_name}, synchronize_session=False)
    return row, None


def delete_registered_country(country_id: str, *, cascade: bool = False) -> tuple[bool, str | None]:
    row = RegisteredCountry.query.get(country_id)
    if not row:
        return False, "未找到该字典项"
    usage = registered_country_usage(row.name)
    if usage["total"] > 0 and not cascade:
        parts = []
        if usage["companyProjects"]:
            parts.append(f"公司总览 {usage['companyProjects']} 项")
        if usage["projects"]:
            parts.append(f"页面1 项目 {usage['projects']} 项")
        if usage["userScopes"]:
            parts.append(f"账号国家维度 {usage['userScopes']} 项")
        detail = "、".join(parts) if parts else f"{usage['total']} 处"
        return False, f"该国家已被引用（{detail}），无法删除"
    if usage["total"] > 0 and cascade:
        from .reference_cascade import cascade_delete_registered_country

        ok, err, _ = cascade_delete_registered_country(country_id)
        return ok, err
    db.session.delete(row)
    return True, None


def deactivate_registered_country(country_id: str) -> bool:
    ok, _ = delete_registered_country(country_id)
    if ok:
        return True
    row = RegisteredCountry.query.get(country_id)
    if not row:
        return False
    usage = registered_country_usage(row.name)
    if usage["total"] > 0:
        return False
    row.is_active = False
    db.session.add(row)
    return True


def collect_countries_from_legacy_data() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for model in (Project, CompanyProject, UserCountryScope):
        for row in model.query.all():
            raw = getattr(row, "registered_country", None)
            c = normalize_registered_country(raw)
            if c and c not in seen:
                seen.add(c)
                out.append(c)
    return out


def bootstrap_registered_countries_from_data() -> int:
    """一次性汇入历史数据（启动迁移）；日常仅在页面0 维护。"""
    added = 0
    changed = False
    for c in collect_countries_from_legacy_data():
        before = RegisteredCountry.query.filter_by(name=c).first()
        if not before:
            db.session.add(RegisteredCountry(name=c, sort_order=0, is_active=True))
            added += 1
            changed = True
        elif not before.is_active:
            before.is_active = True
            db.session.add(before)
            changed = True
    if changed:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return added


def assign_registered_country_field(row: Any, raw: Any) -> Optional[str]:
    name = resolve_registered_country_selection(raw)
    if hasattr(row, "registered_country"):
        row.registered_country = name
    return name


def validate_registered_country_selection(raw: Any) -> tuple[Optional[str], Optional[str]]:
    """返回 (规范名, 错误信息)。"""
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return None, None
    name = normalize_registered_country(raw)
    if not name:
        return None, None
    if resolve_registered_country_selection(name):
        return name, None
    return None, f"注册国家「{name}」不在字典中，请先在页面0 维护注册国家字典"
