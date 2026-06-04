# -*- coding: utf-8 -*-
"""多公司租户上下文解析（开关关闭时保持现网单租户行为）。"""
from __future__ import annotations

from typing import Any, Optional

from flask import has_request_context, session

from .app_settings import is_multi_tenant_enabled
from .models import Organization, Project, UploadRecord, UserOrganizationMembership


def default_organization() -> Optional[Organization]:
    row = Organization.query.filter_by(is_default=True).order_by(Organization.created_at.asc()).first()
    if row:
        return row
    row = (
        Organization.query.filter_by(knowledge_collection="regulations")
        .order_by(Organization.created_at.asc())
        .first()
    )
    if row:
        return row
    return Organization.query.order_by(Organization.created_at.asc()).first()


def user_organization_ids(user_id: str) -> list[str]:
    uid = (user_id or "").strip()
    if not uid:
        return []
    rows = UserOrganizationMembership.query.filter_by(user_id=uid).all()
    return [str(r.organization_id).strip() for r in rows if str(r.organization_id).strip()]


def active_organization_id_from_session() -> str:
    if not is_multi_tenant_enabled():
        d = default_organization()
        return str(getattr(d, "id", "") or "").strip()
    oid = ""
    if has_request_context():
        oid = str(session.get("active_organization_id") or "").strip()
    if oid:
        return oid
    d = default_organization()
    return str(getattr(d, "id", "") or "").strip()


def collection_for_organization(organization_id: str) -> str:
    oid = (organization_id or "").strip()
    if oid:
        row = Organization.query.get(oid)
        if row:
            c = str(row.knowledge_collection or "").strip()
            if c:
                return c
    d = default_organization()
    if d and str(d.knowledge_collection or "").strip():
        return str(d.knowledge_collection).strip()
    return "regulations"


def _organization_id_for_upload(upload_id: str) -> str:
    uid = (upload_id or "").strip()
    if not uid:
        return ""
    rec = UploadRecord.query.get(uid)
    if not rec:
        return ""
    oid = str(getattr(rec, "organization_id", "") or "").strip()
    if oid:
        return oid
    pid = str(getattr(rec, "project_id", "") or "").strip()
    if not pid:
        return ""
    proj = Project.query.get(pid)
    if not proj:
        return ""
    return str(getattr(proj, "organization_id", "") or "").strip()


def _normalize_upload_ids(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for x in raw:
        s = str(x or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def resolve_organization_context(
    *,
    preferred_collection: Optional[str] = None,
    explicit_organization_id: Optional[str] = None,
    upload_id: Optional[str] = None,
    upload_ids: Optional[list[str]] = None,
) -> tuple[str, str]:
    """解析当前请求应使用的 organization_id 与 collection。

    规则：
    - 开关关闭：保持现网，直接返回 (默认组织, preferred_collection|regulations)
    - 开关开启：按显式 organization_id -> upload(s) 所属公司 -> session active organization -> 默认公司
    - collection 在开关开启时始终由 organization 反查，避免跨公司误取知识库
    """
    prefer = str(preferred_collection or "").strip()
    if not is_multi_tenant_enabled():
        d = default_organization()
        oid = str(getattr(d, "id", "") or "").strip()
        return oid, (prefer or "regulations")

    oid = str(explicit_organization_id or "").strip()
    if oid:
        return oid, collection_for_organization(oid)

    for uid in _normalize_upload_ids(upload_ids):
        oid = _organization_id_for_upload(uid)
        if oid:
            return oid, collection_for_organization(oid)

    oid = _organization_id_for_upload(str(upload_id or "").strip())
    if oid:
        return oid, collection_for_organization(oid)

    oid = active_organization_id_from_session()
    if oid:
        return oid, collection_for_organization(oid)

    d = default_organization()
    oid = str(getattr(d, "id", "") or "").strip()
    return oid, collection_for_organization(oid)

