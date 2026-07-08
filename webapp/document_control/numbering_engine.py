from __future__ import annotations

import re
from datetime import timedelta
from typing import Optional

from sqlalchemy import and_, func, or_

from webapp import db
from webapp.models import ControlledDocument, NumberAllocation, NumberingScheme, now_local


_SEP_RE = re.compile(r"[\s_]+")
_DASH_RE = re.compile(r"-{2,}")
DOC_STATUS_CONTROLLED = "controlled"
DOC_STATUS_VOIDED = "voided"


def is_controlled_document_status(status: Optional[str]) -> bool:
    s = (status or "").strip().lower()
    if s in (DOC_STATUS_VOIDED, "obsolete", "作废"):
        return False
    return True


def find_controlled_document_by_norm(
    org_id: str,
    norm: str,
    *,
    exclude_id: Optional[str] = None,
) -> Optional[ControlledDocument]:
    if not norm:
        return None
    q = ControlledDocument.query.filter_by(
        organization_id=org_id,
        normalized_document_number=norm,
        status=DOC_STATUS_CONTROLLED,
    )
    if exclude_id:
        q = q.filter(ControlledDocument.id != exclude_id)
    return q.first()


def load_controlled_docs_by_norm(org_id: str) -> dict[str, ControlledDocument]:
    rows = ControlledDocument.query.filter_by(
        organization_id=org_id,
        status=DOC_STATUS_CONTROLLED,
    ).all()
    return {
        row.normalized_document_number: row
        for row in rows
        if row.normalized_document_number
    }


def controlled_number_conflict_message(
    org_id: str,
    norm: str,
    *,
    exclude_id: Optional[str] = None,
) -> Optional[str]:
    conflict = find_controlled_document_by_norm(org_id, norm, exclude_id=exclude_id)
    if not conflict:
        return None
    label = (conflict.title or conflict.document_number or norm).strip()
    return f"受控编号已存在（{label}）"


def normalize_document_number(number: str) -> str:
    text = (number or "").strip().upper()
    if not text:
        return ""
    text = _SEP_RE.sub("-", text)
    text = text.replace("—", "-").replace("–", "-").replace("－", "-")
    text = _DASH_RE.sub("-", text)
    return text.strip("-")


def registration_compare_key(number: str) -> str:
    """注册关联比对键：仅规范空格/破折号等后做编号精确匹配，不写入库。"""
    normalized = normalize_document_number(number)
    if not normalized:
        return ""
    return normalized.replace("-", "")


def _prefix_from_project_code(project_code: Optional[str], fallback: Optional[str]) -> str:
    code = (project_code or "").strip()
    if code:
        return normalize_document_number(code)
    return normalize_document_number(fallback or "")


def _render_number(scheme: NumberingScheme, *, prefix: str, seq: int) -> str:
    template = (scheme.render_template or "{prefix}-{type}-{seq:03d}").strip()
    doc_type = normalize_document_number(scheme.doc_type_code or "DOC")
    safe_prefix = normalize_document_number(prefix) or "DOC"
    return template.format(prefix=safe_prefix, type=doc_type, seq=int(seq))


def _max_sequence_for_prefix(org_id: Optional[str], prefix: str, doc_type: str) -> int:
    prefix2 = normalize_document_number(prefix)
    doc_type2 = normalize_document_number(doc_type)
    if not prefix2:
        return 0
    pattern = re.compile(rf"^{re.escape(prefix2)}-{re.escape(doc_type2)}-(\d+)$")
    max_seq = 0
    for row in (
        db.session.query(ControlledDocument.document_number)
        .filter(ControlledDocument.organization_id == org_id)
        .all()
    ):
        value = normalize_document_number(row[0] or "")
        m = pattern.match(value)
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    for row in (
        db.session.query(NumberAllocation.allocated_number)
        .filter(
            NumberAllocation.organization_id == org_id,
            NumberAllocation.status.in_(("reserved", "issued")),
        )
        .all()
    ):
        value = normalize_document_number(row[0] or "")
        m = pattern.match(value)
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    return max_seq


def preview_next_number(
    *,
    organization_id: Optional[str],
    scheme: NumberingScheme,
    project_code: Optional[str] = None,
) -> dict:
    prefix = (
        _prefix_from_project_code(project_code, scheme.fixed_prefix)
        if (scheme.prefix_source or "fixed") == "from_project_code"
        else normalize_document_number(scheme.fixed_prefix or "DOC")
    )
    max_seq = _max_sequence_for_prefix(organization_id, prefix, scheme.doc_type_code or "DOC")
    seq = max(int(scheme.seq_start or 1), max_seq + 1)
    number = _render_number(scheme, prefix=prefix, seq=seq)
    return {
        "document_number": number,
        "normalized_document_number": normalize_document_number(number),
        "prefix": prefix,
        "doc_type_code": scheme.doc_type_code,
        "seq": seq,
    }


def reserve_number(
    *,
    organization_id: Optional[str],
    scheme: NumberingScheme,
    requested_title: str,
    project_id: Optional[str],
    project_code: Optional[str],
    user_id: Optional[str],
    reserved_minutes: int = 30,
) -> NumberAllocation:
    info = preview_next_number(
        organization_id=organization_id,
        scheme=scheme,
        project_code=project_code,
    )
    norm = info["normalized_document_number"]
    conflict = (
        db.session.query(NumberAllocation.id)
        .filter(
            NumberAllocation.organization_id == organization_id,
            NumberAllocation.normalized_allocated_number == norm,
            NumberAllocation.status.in_(("reserved", "issued")),
        )
        .first()
    )
    if conflict:
        raise ValueError("编号已被占用，请重试")
    allocation = NumberAllocation(
        organization_id=organization_id,
        scheme_id=scheme.id,
        requested_title=(requested_title or "").strip() or None,
        doc_type_code=(scheme.doc_type_code or "").strip() or None,
        project_id=(project_id or "").strip() or None,
        project_code=(project_code or "").strip() or None,
        allocated_number=info["document_number"],
        normalized_allocated_number=norm,
        status="reserved",
        reserved_until=now_local() + timedelta(minutes=max(1, int(reserved_minutes))),
        created_by_user_id=(user_id or "").strip() or None,
    )
    db.session.add(allocation)
    db.session.flush()
    return allocation


def issue_number(
    *,
    organization_id: Optional[str],
    allocation: NumberAllocation,
    version: Optional[str],
    title: str,
    source: str = "allocated",
    upload_record_id: Optional[str] = None,
    project_id: Optional[str] = None,
    project_code: Optional[str] = None,
    user_id: Optional[str] = None,
) -> ControlledDocument:
    if allocation.status not in ("reserved", "issued"):
        raise ValueError("编号状态不允许发放")
    norm = normalize_document_number(allocation.allocated_number or "")
    existing = find_controlled_document_by_norm(organization_id or "", norm)
    if existing:
        doc = existing
    else:
        doc = ControlledDocument(
            organization_id=organization_id,
            document_number=allocation.allocated_number,
            normalized_document_number=norm,
            version=(version or "").strip() or None,
            title=(title or "").strip() or allocation.requested_title or "未命名文件",
            doc_type_code=allocation.doc_type_code,
            project_id=(project_id or allocation.project_id or "").strip() or None,
            project_code=(project_code or allocation.project_code or "").strip() or None,
            status="controlled",
            source=(source or "allocated").strip() or "allocated",
            upload_record_id=(upload_record_id or "").strip() or None,
            created_by_user_id=(user_id or allocation.created_by_user_id or "").strip() or None,
        )
        db.session.add(doc)
    allocation.status = "issued"
    allocation.issued_document_id = doc.id
    allocation.allocated_version = (version or "").strip() or None
    db.session.add(allocation)
    db.session.flush()
    return doc

