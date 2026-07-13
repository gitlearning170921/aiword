"""文控台账与页面1项目（project_id）按所属项目名称 + 注册国家关联。"""
from __future__ import annotations

from typing import Any, Optional

from webapp import db
from webapp.models import ControlledDocument, now_local
from webapp.project_identity import find_page1_project, scope_field_tokens


def _registration_scope_entries(meta: Optional[dict]) -> list[dict[str, Any]]:
    if not isinstance(meta, dict):
        return []
    items = meta.get("registrationProjects")
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict)]


def _primary_scope_pair(doc: ControlledDocument) -> tuple[str, str]:
    entries = _registration_scope_entries(doc.metadata_json)
    if entries:
        first = entries[0]
        return (
            (first.get("projectName") or "").strip(),
            (first.get("registeredCountry") or "").strip(),
        )
    names = scope_field_tokens(doc.project_name)
    countries = scope_field_tokens(doc.registered_country)
    name = names[0] if names else (doc.project_name or "").strip()
    country = countries[0] if countries else (doc.registered_country or "").strip()
    return name, country


def link_controlled_document_to_page1_project(
    doc: ControlledDocument,
    *,
    organization_id: Optional[str] = None,
    force: bool = False,
) -> bool:
    """按所属项目 + 注册国家解析页面1 project_id 并写入台账。"""
    del organization_id  # 当前 Project 表未按 org 隔离名称；保留参数便于后续扩展
    if (doc.project_id or "").strip() and not force:
        return False

    names = scope_field_tokens(doc.project_name)
    if len(names) > 1:
        return False

    project_name, registered_country = _primary_scope_pair(doc)
    if not project_name:
        return False

    proj = find_page1_project(
        project_name=project_name,
        registered_country=registered_country or None,
        project_id=doc.project_id if force else None,
    )
    if not proj:
        return False

    if (doc.project_id or "").strip() == proj.id:
        return False

    doc.project_id = proj.id
    doc.updated_at = now_local()
    return True


def backfill_controlled_document_project_ids(
    organization_id: Optional[str] = None,
    *,
    limit: int = 500,
) -> int:
    """为尚未关联 project_id 的受控台账按项目名称回填（幂等）。"""
    org = (organization_id or "").strip() or None
    q = ControlledDocument.query.filter(
        (ControlledDocument.project_id.is_(None)) | (ControlledDocument.project_id == "")
    )
    if org:
        q = q.filter_by(organization_id=org)
    rows = (
        q.order_by(ControlledDocument.updated_at.desc(), ControlledDocument.id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    updated = 0
    for doc in rows:
        if link_controlled_document_to_page1_project(doc, organization_id=org):
            updated += 1
    if updated:
        db.session.flush()
    return updated


def count_controlled_documents_for_project_id(project_id: Optional[str]) -> int:
    pid = (project_id or "").strip()
    if not pid:
        return 0
    return (
        ControlledDocument.query.filter_by(project_id=pid, status="controlled").count()
    )


def controlled_document_labels_for_project_id(
    project_id: Optional[str],
    *,
    limit: int = 5,
) -> list[str]:
    pid = (project_id or "").strip()
    if not pid:
        return []
    rows = (
        ControlledDocument.query.filter_by(project_id=pid, status="controlled")
        .order_by(ControlledDocument.updated_at.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    out: list[str] = []
    for row in rows:
        label = (row.document_number or row.title or row.id or "").strip()
        if label and label not in out:
            out.append(label)
    return out
