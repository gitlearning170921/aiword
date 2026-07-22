from __future__ import annotations

from typing import Any, Optional

from flask import session

from .. import db
from ..authz import is_page13_super_admin
from ..models import LiteratureSearchBatch, now_local
from ..tenant_context import resolve_organization_context
from .normalize import normalize_record


def actor_user_id() -> str:
    uid = str(session.get("user_id") or "").strip()
    if uid:
        return uid
    if is_page13_super_admin():
        return "page13_super_admin"
    return ""


def _scope_org_id() -> Optional[str]:
    oid, _ = resolve_organization_context()
    return str(oid or "").strip() or None


def serialize_batch(row: LiteratureSearchBatch) -> dict[str, Any]:
    return {
        "id": row.id,
        "type": row.batch_type or "search",
        "typeLabel": "导入" if (row.batch_type or "") == "import" else "检索",
        "query": row.query_text or "",
        "sources": list(row.sources_json or []),
        "summary": row.summary or "",
        "statusNote": row.status_note or "",
        "details": list(row.details_json or []),
        "records": list(row.records_json or []),
        "recordCount": int(row.record_count or 0),
        "createdAt": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else "",
        "updatedAt": row.updated_at.strftime("%Y-%m-%d %H:%M:%S") if row.updated_at else "",
    }


def list_batches(*, limit: int = 50) -> list[dict[str, Any]]:
    uid = actor_user_id()
    if not uid:
        return []
    q = LiteratureSearchBatch.query.filter_by(user_id=uid)
    oid = _scope_org_id()
    if oid:
        q = q.filter(
            (LiteratureSearchBatch.organization_id == oid)
            | (LiteratureSearchBatch.organization_id.is_(None))
        )
    rows = q.order_by(LiteratureSearchBatch.created_at.desc()).limit(max(1, min(200, limit))).all()
    return [serialize_batch(r) for r in rows]


def upsert_batch(
    *,
    batch_id: str | None,
    batch_type: str,
    query: str,
    sources: list[str],
    summary: str,
    status_note: str,
    details: list[dict[str, Any]] | None,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    uid = actor_user_id()
    if not uid:
        raise PermissionError("未登录，无法保存检索批次")
    oid = _scope_org_id()
    cleaned = [normalize_record(x) for x in (records or []) if isinstance(x, dict)]
    detail_safe: list[dict[str, Any]] = []
    for d in details or []:
        if not isinstance(d, dict):
            continue
        detail_safe.append(
            {
                "source": d.get("source") or "",
                "error": d.get("error") or "",
                "elapsed_ms": int(d.get("elapsed_ms") or 0),
                "totalFound": int(d.get("totalFound") or 0),
                "fetched": int(d.get("fetched") or 0),
            }
        )

    row = None
    bid = str(batch_id or "").strip()
    if bid:
        row = LiteratureSearchBatch.query.filter_by(id=bid, user_id=uid).first()
    if row is None:
        row = LiteratureSearchBatch(
            id=bid or None,
            user_id=uid,
            organization_id=oid,
            batch_type=(batch_type or "search").strip().lower() or "search",
            created_at=now_local(),
        )
        db.session.add(row)

    row.organization_id = oid or row.organization_id
    row.batch_type = (batch_type or row.batch_type or "search").strip().lower() or "search"
    row.query_text = query or ""
    row.sources_json = list(sources or [])
    row.summary = summary or ""
    row.status_note = status_note or ""
    row.details_json = detail_safe
    row.records_json = cleaned
    row.record_count = len(cleaned)
    row.updated_at = now_local()
    db.session.commit()
    return serialize_batch(row)


def delete_batch(batch_id: str) -> bool:
    uid = actor_user_id()
    if not uid:
        return False
    row = LiteratureSearchBatch.query.filter_by(id=str(batch_id or "").strip(), user_id=uid).first()
    if not row:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def clear_batches() -> int:
    uid = actor_user_id()
    if not uid:
        return 0
    q = LiteratureSearchBatch.query.filter_by(user_id=uid)
    oid = _scope_org_id()
    if oid:
        q = q.filter(
            (LiteratureSearchBatch.organization_id == oid)
            | (LiteratureSearchBatch.organization_id.is_(None))
        )
    rows = q.all()
    n = len(rows)
    for row in rows:
        db.session.delete(row)
    db.session.commit()
    return n
