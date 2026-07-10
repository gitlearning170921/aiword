from __future__ import annotations

import re
from datetime import timedelta
from typing import Optional

from sqlalchemy import and_, func, or_

from webapp import db
from webapp.models import ControlledDocument, NumberAllocation, NumberingScheme, now_local


_DASH_RE = re.compile(r"-{2,}")
# 判重时去掉空格及不可见字符（不换为连字符，避免 QR-SMP 7.3 与 QR-SMP7.3 被拆成不同编号）
_WS_INVISIBLE_RE = re.compile(r"[\s\u00a0\u2000-\u200d\u202f\u205f\u3000\ufeff]+")
_UNDERSCORE_RE = re.compile(r"_+")
DOC_STATUS_CONTROLLED = "controlled"
DOC_STATUS_VOIDED = "voided"


def is_controlled_document_status(status: Optional[str]) -> bool:
    s = (status or "").strip().lower()
    if s in (DOC_STATUS_VOIDED, "obsolete", "作废"):
        return False
    return True


def normalize_document_number(number: str) -> str:
    text = (number or "").strip().upper()
    if not text:
        return ""
    text = _WS_INVISIBLE_RE.sub("", text)
    text = _UNDERSCORE_RE.sub("-", text)
    text = text.replace("—", "-").replace("–", "-").replace("－", "-")
    text = _DASH_RE.sub("-", text)
    return text.strip("-")


def effective_document_norm(doc: ControlledDocument) -> str:
    """以当前规范化规则重算编号键；优先 document_number，兼容旧库 normalized 字段。"""
    raw = (doc.document_number or doc.normalized_document_number or "").strip()
    return normalize_document_number(raw)


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
    hit = q.first()
    if hit:
        return hit
    # 兼容尚未回填 normalized_document_number 的历史记录
    fallback_q = ControlledDocument.query.filter_by(
        organization_id=org_id,
        status=DOC_STATUS_CONTROLLED,
    )
    if exclude_id:
        fallback_q = fallback_q.filter(ControlledDocument.id != exclude_id)
    for row in fallback_q.all():
        if effective_document_norm(row) == norm:
            return row
    return None


def load_controlled_docs_by_norm(org_id: str) -> dict[str, ControlledDocument]:
    rows = ControlledDocument.query.filter_by(
        organization_id=org_id,
        status=DOC_STATUS_CONTROLLED,
    ).all()
    out: dict[str, ControlledDocument] = {}
    for row in rows:
        norm = effective_document_norm(row)
        if norm:
            out[norm] = row
    return out


def backfill_normalized_document_numbers() -> int:
    """按最新规则回填 normalized_document_number（幂等）。

    启动时由 historical_migration.run_doc_control_norm_backfill_if_pending 调用；
    全部对齐后在 app_configs 写入 DOC_CONTROL_NORMALIZED_NUMBER_BACKFILL_V1，不再重复全表扫描。
    """
    updated = 0
    rows = (
        ControlledDocument.query.order_by(ControlledDocument.created_at.asc(), ControlledDocument.id.asc())
        .all()
    )
    controlled_keys: dict[tuple[str, str], str] = {}
    for row in rows:
        new_norm = normalize_document_number(row.document_number or "")
        if not new_norm:
            continue
        if row.status == DOC_STATUS_CONTROLLED:
            key = (row.organization_id or "", new_norm)
            if key in controlled_keys and controlled_keys[key] != row.id:
                continue
            controlled_keys[key] = row.id
        if (row.normalized_document_number or "") != new_norm:
            row.normalized_document_number = new_norm
            updated += 1
    if updated:
        db.session.commit()
    return updated


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


def scheme_allocation_prefix(scheme: NumberingScheme, project_code: Optional[str]) -> str:
    if (scheme.prefix_source or "fixed") == "from_project_code":
        return _prefix_from_project_code(project_code, scheme.fixed_prefix)
    return normalize_document_number(scheme.fixed_prefix or scheme.doc_type_code or "DOC")


def _render_number(
    scheme: NumberingScheme,
    *,
    prefix: str,
    seq: int,
    subtype: str = "",
) -> str:
    template = (scheme.render_template or "{prefix}-{type}-{seq:03d}").strip()
    doc_type = normalize_document_number(scheme.doc_type_code or "DOC")
    safe_prefix = normalize_document_number(prefix) or "DOC"
    sub_raw = (subtype or "").strip()
    if "{subtype}" in template:
        if not sub_raw:
            raise ValueError("子类编号未生成，请检查文件名称")
        safe_subtype = normalize_document_number(sub_raw)
    else:
        safe_subtype = normalize_document_number(sub_raw or doc_type)
    pad = max(1, int(scheme.seq_pad or 3))
    return template.format(
        prefix=safe_prefix,
        type=doc_type,
        subtype=safe_subtype,
        seq=int(seq),
        seq_pad=pad,
    )


def _template_seq_regex(
    scheme: NumberingScheme,
    *,
    prefix: str,
    subtype: str = "",
) -> re.Pattern[str]:
    custom = (scheme.pattern_regex or "").strip()
    if custom:
        return re.compile(custom, re.I)
    doc_type = normalize_document_number(scheme.doc_type_code or "DOC")
    safe_prefix = re.escape(normalize_document_number(prefix) or "")
    safe_type = re.escape(doc_type)
    safe_subtype = re.escape(normalize_document_number(subtype or doc_type))
    template = (scheme.render_template or "{prefix}-{type}-{seq:03d}").strip()
    pad = max(1, int(scheme.seq_pad or 3))
    body = template
    body = body.replace("{prefix}", safe_prefix or "([A-Z0-9]{2,24})")
    body = body.replace("{type}", safe_type)
    body = body.replace("{subtype}", safe_subtype or "([A-Z]{2,12})")
    body = re.sub(r"\{seq:\d+d\}", rf"(\d{{{pad},}})", body)
    body = body.replace("{seq}", r"(\d+)")
    if safe_prefix:
        body = body.replace("([A-Z0-9]{2,24})", safe_prefix, 1)
    return re.compile(rf"^{body}$", re.I)


def _scheme_uses_subtype_template(scheme: NumberingScheme) -> bool:
    return "{subtype}" in ((scheme.render_template or "").strip())


def allocation_blocks_number(alloc: NumberAllocation) -> bool:
    """占用编号冲突检测：未过期预留，或已发放且台账仍为受控。"""
    st = (alloc.status or "").strip().lower()
    if st == "reserved":
        until = alloc.reserved_until
        if until is not None and until < now_local():
            return False
        return True
    if st != "issued":
        return False
    doc_id = (alloc.issued_document_id or "").strip()
    if not doc_id:
        return False
    doc = ControlledDocument.query.filter_by(id=doc_id).first()
    return doc is not None and (doc.status or "").strip().lower() == DOC_STATUS_CONTROLLED


def allocation_counts_for_subtype_reuse(alloc: NumberAllocation) -> bool:
    """子类复用：仅已发放且对应台账仍为受控。"""
    if (alloc.status or "").strip().lower() != "issued":
        return False
    doc_id = (alloc.issued_document_id or "").strip()
    if not doc_id:
        return False
    doc = ControlledDocument.query.filter_by(id=doc_id).first()
    return doc is not None and (doc.status or "").strip().lower() == DOC_STATUS_CONTROLLED


def _seq_from_number_for_scheme(
    scheme: NumberingScheme,
    *,
    prefix: str,
    subtype: str,
    number: str,
) -> Optional[int]:
    prefix_norm = normalize_document_number(prefix or "")
    value = normalize_document_number(number or "")
    if not prefix_norm or not value.startswith(prefix_norm + "-"):
        return None
    pattern = _template_seq_regex(scheme, prefix=prefix_norm, subtype=subtype)
    m = pattern.match(value)
    if not m:
        return None
    return int(m.groups()[-1])


def release_expired_number_reservations(org_id: Optional[str]) -> int:
    """清理已过期的预留编号（不参与流水号，仅释放占用）。"""
    if not (org_id or "").strip():
        return 0
    now = now_local()
    deleted = (
        NumberAllocation.query.filter(
            NumberAllocation.organization_id == org_id,
            NumberAllocation.status == "reserved",
            NumberAllocation.reserved_until.isnot(None),
            NumberAllocation.reserved_until < now,
        )
        .delete(synchronize_session=False)
    )
    if deleted:
        db.session.flush()
    return int(deleted or 0)


def _extract_trailing_seq(number: str) -> Optional[int]:
    norm = normalize_document_number(number or "")
    if not norm:
        return None
    m = re.search(r"-(\d+)$", norm)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _next_sequence_for_issue(
    org_id: Optional[str],
    scheme: NumberingScheme,
    *,
    prefix: str,
    subtype: str,
    title: Optional[str] = None,
    project_id: Optional[str] = None,
) -> int:
    """新名称从 seq_start 起；名称相关受控记录（与判重一致）最大流水号 +1。"""
    from .subtype_resolver import find_controlled_docs_for_issue_title

    db.session.expire_all()
    seq_start = max(1, int(scheme.seq_start or 1))
    org = org_id or ""
    raw_title = (title or "").strip()
    if not raw_title:
        return seq_start

    prefix_norm = normalize_document_number(prefix or "")
    matched = find_controlled_docs_for_issue_title(
        organization_id=org,
        prefix=prefix,
        title=raw_title,
        project_id=project_id,
    )
    max_seq = 0
    for doc in matched:
        num = normalize_document_number(doc.document_number or "")
        if prefix_norm and not num.startswith(prefix_norm + "-"):
            continue
        seq = _extract_trailing_seq(num)
        if seq is not None:
            max_seq = max(max_seq, seq)

    if max_seq > 0:
        return max(seq_start, max_seq + 1)
    return seq_start


def preview_next_number(
    *,
    organization_id: Optional[str],
    scheme: NumberingScheme,
    project_code: Optional[str] = None,
    project_id: Optional[str] = None,
    subtype: Optional[str] = None,
    title: Optional[str] = None,
    title_en: Optional[str] = None,
    subtype_from_title: bool = False,
) -> dict:
    prefix = (
        _prefix_from_project_code(project_code, scheme.fixed_prefix)
        if (scheme.prefix_source or "fixed") == "from_project_code"
        else normalize_document_number(scheme.fixed_prefix or scheme.doc_type_code or "DOC")
    )
    if subtype_from_title and title:
        from .subtype_resolver import resolve_allocation_subtype

        sub = resolve_allocation_subtype(
            organization_id=organization_id or "",
            scheme=scheme,
            project_code=project_code,
            title=title,
            title_en=title_en,
            manual_subtype=subtype,
            subtype_from_title=True,
        )
    elif _scheme_uses_subtype_template(scheme):
        raise ValueError("请填写文件名称以生成子类编号")
    else:
        sub = (subtype or scheme.doc_type_code or "").strip()
    seq = _next_sequence_for_issue(
        organization_id,
        scheme,
        prefix=prefix,
        subtype=sub,
        title=title,
        project_id=project_id,
    )
    number = _render_number(scheme, prefix=prefix, seq=seq, subtype=sub)
    return {
        "document_number": number,
        "normalized_document_number": normalize_document_number(number),
        "prefix": prefix,
        "doc_type_code": scheme.doc_type_code,
        "subtype": sub,
        "title_en": (title_en or "").strip() or None,
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
    subtype: Optional[str] = None,
    subtype_from_title: bool = False,
    title_en: Optional[str] = None,
) -> NumberAllocation:
    release_expired_number_reservations(organization_id)
    info = preview_next_number(
        organization_id=organization_id,
        scheme=scheme,
        project_code=project_code,
        project_id=project_id,
        subtype=subtype,
        title=requested_title,
        title_en=title_en,
        subtype_from_title=subtype_from_title,
    )
    norm = info["normalized_document_number"]
    conflict_alloc = (
        db.session.query(NumberAllocation)
        .filter(
            NumberAllocation.organization_id == organization_id,
            NumberAllocation.normalized_allocated_number == norm,
            NumberAllocation.status.in_(("reserved", "issued")),
        )
        .all()
    )
    if any(allocation_blocks_number(a) for a in conflict_alloc):
        raise ValueError("编号已被占用，请重试")
    conflict_doc = find_controlled_document_by_norm(organization_id or "", norm)
    if conflict_doc:
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
    title_en: Optional[str] = None,
) -> ControlledDocument:
    if allocation.status not in ("reserved", "issued"):
        raise ValueError("编号状态不允许发放")
    norm = normalize_document_number(allocation.allocated_number or "")
    existing = find_controlled_document_by_norm(organization_id or "", norm)
    title_en_clean = (title_en or "").strip() or None
    if existing:
        doc = existing
        if title_en_clean and not (doc.title_en or "").strip():
            doc.title_en = title_en_clean
    else:
        doc = ControlledDocument(
            organization_id=organization_id,
            document_number=allocation.allocated_number,
            normalized_document_number=norm,
            version=(version or "").strip() or None,
            title=(title or "").strip() or allocation.requested_title or "未命名文件",
            title_en=title_en_clean,
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

