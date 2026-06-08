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


def _strict_org_scope() -> bool:
    """开启多租户或页面0/4 公司体系时，公司列表仅来自账号绑定，不回退默认公司。"""
    from .authz import company_registry_enabled

    return bool(is_multi_tenant_enabled() or company_registry_enabled())


def user_allowed_organization_ids(user_id: str | None = None) -> list[str]:
    """当前请求可见的公司 id（超管=全部；普通账号=UserOrganizationMembership）。"""
    from .authz import is_page13_super_admin

    if is_page13_super_admin():
        return [
            str(r.id or "").strip()
            for r in Organization.query.filter_by(is_active=True)
            .order_by(Organization.is_default.desc(), Organization.created_at.asc())
            .all()
            if str(r.id or "").strip()
        ]
    uid = (user_id or "").strip()
    if not uid and has_request_context():
        uid = str(session.get("user_id") or "").strip()
    out: list[str] = []
    if has_request_context():
        raw = session.get("organization_ids")
        if isinstance(raw, list):
            for x in raw:
                s = str(x or "").strip()
                if s and s not in out:
                    out.append(s)
    if uid:
        for s in user_organization_ids(uid):
            if s and s not in out:
                out.append(s)
    if not is_page13_super_admin():
        from .authz import is_project_admin, user_team_ids

        if is_project_admin():
            from .team_organizations import organization_ids_for_teams

            for s in organization_ids_for_teams(user_team_ids()):
                if s and s not in out:
                    out.append(s)
    return out


def organization_id_allowed(organization_id: str) -> bool:
    oid = str(organization_id or "").strip()
    if not oid:
        return False
    return oid in set(user_allowed_organization_ids())


def active_organization_id_from_session() -> str:
    oid = ""
    if has_request_context():
        oid = str(session.get("active_organization_id") or "").strip()
    if _strict_org_scope():
        allowed = user_allowed_organization_ids()
        if oid and oid in allowed:
            return oid
        if allowed:
            return allowed[0]
        return ""
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


def organization_id_for_collection(collection: str) -> str:
    """按 knowledge_collection 反查组织 id（须已绑定且启用）。"""
    ck = str(collection or "").strip()
    if not ck:
        return ""
    row = (
        Organization.query.filter_by(knowledge_collection=ck, is_active=True)
        .order_by(Organization.is_default.desc(), Organization.created_at.asc())
        .first()
    )
    if row:
        return str(row.id or "").strip()
    return ""


def is_collection_bound_to_organization(collection: str) -> bool:
    return bool(organization_id_for_collection(collection))


def validate_resolved_collection(collection: str) -> str | None:
    """未绑定公司的 collection 不可使用；返回可读错误，合法则 None。"""
    ck = str(collection or "").strip()
    if not ck:
        return "知识库 collection 不能为空"
    if not is_collection_bound_to_organization(ck):
        return f"知识库「{ck}」未绑定任何公司，请先在系统管理/页面4 维护公司与 knowledge_collection"
    return None


def integration_visible_organizations() -> list[Organization]:
    """集成页（审核/初稿/翻译/考试）可见的公司列表：仅账号已绑定公司，不含默认公司回退。"""
    ids = user_allowed_organization_ids()
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
    return [by_id[i] for i in ids if i in by_id]


def integration_organizations_payload() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in integration_visible_organizations():
        oid = str(row.id or "").strip()
        if not oid:
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


def integration_org_context_payload() -> dict[str, Any]:
    orgs = integration_organizations_payload()
    if not orgs:
        return {
            "organizations": [],
            "activeOrganizationId": None,
            "activeKnowledgeCollection": "regulations",
            "message": "当前账号未绑定任何公司，请联系管理员在页面4配置「所属公司」",
        }
    active = active_organization_id_from_session()
    allowed = {str(x.get("id") or "").strip() for x in orgs}
    if active not in allowed and orgs:
        active = str(orgs[0].get("id") or "").strip()
        if has_request_context():
            session["active_organization_id"] = active
    elif not active and orgs:
        active = str(orgs[0].get("id") or "").strip()
        if has_request_context():
            session["active_organization_id"] = active
    coll = collection_for_organization(active) if active else "regulations"
    return {
        "organizations": orgs,
        "activeOrganizationId": active or None,
        "activeKnowledgeCollection": coll,
    }


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
        allowed = user_allowed_organization_ids() if _strict_org_scope() else []
        oid = str(explicit_organization_id or "").strip()
        if not oid:
            oid = active_organization_id_from_session()
        if _strict_org_scope():
            if oid and oid not in allowed:
                oid = allowed[0] if allowed else ""
            elif not oid and allowed:
                oid = allowed[0]
            if not oid:
                d = default_organization()
                oid = str(getattr(d, "id", "") or "").strip()
        elif not oid:
            d = default_organization()
            oid = str(getattr(d, "id", "") or "").strip()
        if _strict_org_scope() and oid and not organization_id_allowed(oid):
            raise ValueError("无权使用该公司或未绑定所属公司，请联系管理员在页面4配置")
        coll = collection_for_organization(oid)
        if prefer and prefer != coll:
            if is_collection_bound_to_organization(prefer) and organization_id_for_collection(prefer) == oid:
                coll = prefer
        err = validate_resolved_collection(coll)
        if err:
            coll = collection_for_organization(oid)
        return oid, coll

    oid = str(explicit_organization_id or "").strip()
    if oid:
        if not organization_id_allowed(oid):
            raise ValueError("无权切换到该公司")
        return oid, collection_for_organization(oid)

    for uid in _normalize_upload_ids(upload_ids):
        oid = _organization_id_for_upload(uid)
        if oid:
            if organization_id_allowed(oid):
                return oid, collection_for_organization(oid)

    oid = _organization_id_for_upload(str(upload_id or "").strip())
    if oid and organization_id_allowed(oid):
        return oid, collection_for_organization(oid)

    oid = active_organization_id_from_session()
    if oid:
        return oid, collection_for_organization(oid)

    allowed = user_allowed_organization_ids()
    if allowed:
        oid = allowed[0]
        return oid, collection_for_organization(oid)

    d = default_organization()
    oid = str(getattr(d, "id", "") or "").strip()
    coll = collection_for_organization(oid)
    err = validate_resolved_collection(coll)
    if err:
        coll = "regulations"
    return oid, coll

