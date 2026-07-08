from __future__ import annotations

import io
import json
import uuid
from datetime import datetime
from typing import Any, Optional

import requests
from flask import Blueprint, current_app, jsonify, render_template, request, session
from openpyxl import load_workbook
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError

from webapp import db
from webapp._integration_common import (
    format_upstream_request_error,
    integration_api_base,
    integration_requests_timeout,
    login_wall,
    upstream_headers,
)
from webapp.app_settings import is_effective_feature_enabled
from webapp.models import (
    ControlledDocument,
    DocumentControlImportLog,
    NumberAllocation,
    NumberingScheme,
    now_local,
)
from webapp.tenant_context import resolve_organization_context
from webapp.user_facing import user_facing_upstream_error
from .numbering_engine import (
    controlled_number_conflict_message,
    issue_number,
    load_controlled_docs_by_norm,
    normalize_document_number,
    preview_next_number,
    registration_compare_key,
    reserve_number,
)


document_control_bp = Blueprint("document_control", __name__)

_DOC_STATUS_CONTROLLED = "controlled"
_DOC_STATUS_VOIDED = "voided"
_REGISTRATION_SHEET_NAME = "注册文件"


def _parse_registration_submitted_filter(raw: Optional[str]) -> Optional[bool]:
    value = (raw or "").strip().lower()
    if value in ("1", "true", "yes", "on", "已递交"):
        return True
    if value in ("0", "false", "no", "off", "未递交"):
        return False
    return None


def _parse_status_filter(raw: Optional[str]) -> Optional[str]:
    value = (raw or "").strip().lower()
    if value in (_DOC_STATUS_VOIDED, "obsolete", "作废"):
        return _DOC_STATUS_VOIDED
    if value in (_DOC_STATUS_CONTROLLED, "active", "受控"):
        return _DOC_STATUS_CONTROLLED
    return None


def _documents_base_query(org_id: str):
    return ControlledDocument.query.filter_by(organization_id=org_id)


def _document_list_order_clauses():
    """台账列表按 Excel 行序展示；无行序的手动录入记录排在后面。"""
    return (
        ControlledDocument.sheet_category.asc(),
        ControlledDocument.excel_row_index.asc().nulls_last(),
        ControlledDocument.document_number.asc(),
    )


def _excel_row_index_from_row(row: dict[str, Any]) -> Optional[int]:
    value = int(row.get("rowIndex") or 0)
    return value if value > 0 else None


def _apply_document_filters(q):
    keyword = (request.args.get("keyword") or "").strip()
    project_code = (request.args.get("projectCode") or "").strip()
    project_name = (request.args.get("projectName") or "").strip()
    registered_country = (request.args.get("registeredCountry") or "").strip()
    status = _parse_status_filter(request.args.get("status"))
    registration_submitted = _parse_registration_submitted_filter(
        request.args.get("registrationSubmitted")
    )
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            db.or_(
                ControlledDocument.document_number.ilike(like),
                ControlledDocument.title.ilike(like),
                ControlledDocument.title_en.ilike(like),
                ControlledDocument.project_code.ilike(like),
                ControlledDocument.project_name.ilike(like),
                ControlledDocument.registered_country.ilike(like),
                ControlledDocument.sheet_category.ilike(like),
            )
        )
    if project_code:
        q = q.filter(ControlledDocument.project_code == project_code)
    if project_name:
        q = q.filter(ControlledDocument.project_name.ilike(f"%{project_name}%"))
    if registered_country:
        q = q.filter(ControlledDocument.registered_country.ilike(f"%{registered_country}%"))
    if status:
        q = q.filter(ControlledDocument.status == status)
    if registration_submitted is True:
        q = q.filter(ControlledDocument.registration_submitted.is_(True))
    elif registration_submitted is False:
        q = q.filter(ControlledDocument.registration_submitted.is_(False))
    return q


def _apply_sheet_category_filter(q, sheet_category: str):
    category = (sheet_category or "").strip()
    if not category:
        return q
    if category == _REGISTRATION_SHEET_NAME:
        return q.filter(
            db.or_(
                ControlledDocument.sheet_category == _REGISTRATION_SHEET_NAME,
                ControlledDocument.registration_submitted.is_(True),
            )
        )
    return q.filter(ControlledDocument.sheet_category == category)


def _list_sheet_categories(org_id: str) -> list[str]:
    rows = (
        db.session.query(ControlledDocument.sheet_category)
        .filter(
            ControlledDocument.organization_id == org_id,
            ControlledDocument.sheet_category.isnot(None),
            ControlledDocument.sheet_category != "",
        )
        .distinct()
        .order_by(ControlledDocument.sheet_category.asc())
        .all()
    )
    items = [r[0] for r in rows if r[0]]
    if (
        db.session.query(ControlledDocument.id)
        .filter(
            ControlledDocument.organization_id == org_id,
            ControlledDocument.registration_submitted.is_(True),
        )
        .first()
        and _REGISTRATION_SHEET_NAME not in items
    ):
        items.append(_REGISTRATION_SHEET_NAME)
    return _sort_sheet_categories(items, org_id)


def _doc_lifecycle_label(status: Optional[str]) -> str:
    s = (status or "").strip().lower()
    if s in (_DOC_STATUS_VOIDED, "obsolete", "作废"):
        return "作废"
    return "受控"


def _require_feature():
    if not is_effective_feature_enabled("FEATURE_DOCUMENT_CONTROL"):
        return jsonify({"message": "文控中心功能未开启"}), 403
    return None


def _org_context() -> tuple[str, str]:
    explicit_org = (
        request.args.get("organizationId")
        or request.form.get("organizationId")
        or (request.get_json(silent=True) or {}).get("organizationId")
        or ""
    )
    return resolve_organization_context(explicit_organization_id=explicit_org)


def _serialize_doc(row: ControlledDocument) -> dict[str, Any]:
    meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    return {
        "id": row.id,
        "organizationId": row.organization_id,
        "documentNumber": row.document_number,
        "normalizedDocumentNumber": row.normalized_document_number,
        "version": row.version,
        "title": row.title,
        "titleEn": row.title_en or meta.get("titleEn"),
        "docTypeCode": row.doc_type_code,
        "projectId": row.project_id,
        "projectCode": row.project_code,
        "projectName": row.project_name,
        "registeredCountry": row.registered_country,
        "sheetCategory": row.sheet_category,
        "registrationSubmitted": bool(row.registration_submitted),
        "status": row.status,
        "statusLabel": _doc_lifecycle_label(row.status),
        "source": row.source,
        "extractConfidence": row.extract_confidence,
        "uploadRecordId": row.upload_record_id,
        "importBatchId": row.import_batch_id,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_scheme(row: NumberingScheme) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "docTypeCode": row.doc_type_code,
        "patternRegex": row.pattern_regex,
        "renderTemplate": row.render_template,
        "prefixSource": row.prefix_source,
        "fixedPrefix": row.fixed_prefix,
        "seqScope": row.seq_scope,
        "seqStart": row.seq_start,
        "seqPad": row.seq_pad,
        "isActive": bool(row.is_active),
        "kbRuleExcerpt": row.kb_rule_excerpt,
    }


@document_control_bp.get("/document-control")
def document_control_page():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    return render_template("document_control.html")


@document_control_bp.get("/document-control/import-logs")
def document_control_import_logs_page():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    return render_template("document_control_import_logs.html")


@document_control_bp.get("/api/document-control/bootstrap")
def api_document_control_bootstrap():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    schemes = (
        NumberingScheme.query.filter_by(organization_id=org_id)
        .order_by(NumberingScheme.created_at.desc())
        .all()
    )
    return jsonify(
        {
            "organizationId": org_id,
            "schemes": [_serialize_scheme(x) for x in schemes],
        }
    )


@document_control_bp.get("/api/document-control/documents")
def api_document_control_documents():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    q = _documents_base_query(org_id)
    q = _apply_document_filters(q)
    sheet_category = (request.args.get("sheetCategory") or "").strip()
    q = _apply_sheet_category_filter(q, sheet_category)
    page = max(1, int(request.args.get("page") or 1))
    page_size = min(200, max(10, int(request.args.get("pageSize") or 50)))
    total = q.count()
    rows = (
        q.order_by(*_document_list_order_clauses())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return jsonify(
        {
            "items": [_serialize_doc(x) for x in rows],
            "total": total,
            "page": page,
            "pageSize": page_size,
        }
    )


def _get_org_document(doc_id: str, org_id: str) -> Optional[ControlledDocument]:
    return ControlledDocument.query.filter_by(id=doc_id, organization_id=org_id).first()


def _apply_document_payload(doc: ControlledDocument, data: dict[str, Any]) -> Optional[str]:
    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return "请填写文件名称"
        doc.title = title
    if "titleEn" in data:
        doc.title_en = (data.get("titleEn") or "").strip() or None
    if "version" in data:
        doc.version = (data.get("version") or "").strip() or None
    if "docTypeCode" in data:
        doc.doc_type_code = (data.get("docTypeCode") or "").strip() or None
    if "projectCode" in data:
        doc.project_code = (data.get("projectCode") or "").strip() or None
    if "projectName" in data:
        doc.project_name = (data.get("projectName") or "").strip() or None
    if "registeredCountry" in data:
        doc.registered_country = (data.get("registeredCountry") or "").strip() or None
    if "sheetCategory" in data:
        doc.sheet_category = (data.get("sheetCategory") or "").strip() or None
    if "registrationSubmitted" in data:
        doc.registration_submitted = bool(data.get("registrationSubmitted"))
    if "status" in data:
        status = _parse_status_filter(str(data.get("status") or ""))
        if status:
            doc.status = status
    meta = dict(doc.metadata_json or {})
    if doc.title_en:
        meta["titleEn"] = doc.title_en
    elif "titleEn" in data:
        meta.pop("titleEn", None)
    doc.metadata_json = meta or None
    doc.updated_at = now_local()
    return None


@document_control_bp.post("/api/document-control/documents")
def api_document_control_create_document():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    data = request.get_json(silent=True) or {}
    doc_num = (data.get("documentNumber") or "").strip()
    norm = normalize_document_number(doc_num)
    if not norm:
        return jsonify({"message": "请填写有效文件编号"}), 400
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"message": "请填写文件名称"}), 400
    doc_status = _parse_status_filter(str(data.get("status") or "")) or _DOC_STATUS_CONTROLLED
    if doc_status == _DOC_STATUS_CONTROLLED:
        conflict_msg = controlled_number_conflict_message(org_id, norm)
        if conflict_msg:
            return jsonify({"message": conflict_msg}), 409
    title_en = (data.get("titleEn") or "").strip()
    metadata_json = {"titleEn": title_en} if title_en else None
    doc = ControlledDocument(
        organization_id=org_id,
        document_number=doc_num,
        normalized_document_number=norm,
        version=(data.get("version") or "").strip() or None,
        title=title,
        title_en=title_en or None,
        doc_type_code=(data.get("docTypeCode") or "").strip() or None,
        project_code=(data.get("projectCode") or "").strip() or None,
        project_name=(data.get("projectName") or "").strip() or None,
        registered_country=(data.get("registeredCountry") or "").strip() or None,
        sheet_category=(data.get("sheetCategory") or "").strip() or None,
        registration_submitted=bool(data.get("registrationSubmitted")),
        status=doc_status,
        source="manual",
        metadata_json=metadata_json,
        created_by_user_id=(session.get("user_id") or "").strip() or None,
    )
    try:
        db.session.add(doc)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "保存失败：受控编号冲突"}), 409
    return jsonify({"message": "已新增", "item": _serialize_doc(doc)})


@document_control_bp.route(
    "/api/document-control/documents/<doc_id>", methods=["PATCH", "DELETE"]
)
def api_document_control_document_detail(doc_id: str):
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    doc = _get_org_document(doc_id, org_id)
    if not doc:
        return jsonify({"message": "记录不存在"}), 404
    if request.method == "DELETE":
        db.session.delete(doc)
        db.session.commit()
        return jsonify({"message": "已删除"})
    data = request.get_json(silent=True) or {}
    if "documentNumber" in data:
        doc_num = (data.get("documentNumber") or "").strip()
        norm = normalize_document_number(doc_num)
        if not norm:
            return jsonify({"message": "请填写有效文件编号"}), 400
        if norm != doc.normalized_document_number:
            doc.document_number = doc_num
            doc.normalized_document_number = norm
    err = _apply_document_payload(doc, data)
    if err:
        return jsonify({"message": err}), 400
    if doc.status == _DOC_STATUS_CONTROLLED:
        conflict_msg = controlled_number_conflict_message(
            org_id, doc.normalized_document_number, exclude_id=doc.id
        )
        if conflict_msg:
            return jsonify({"message": conflict_msg}), 409
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "保存失败：受控编号冲突"}), 409
    return jsonify({"message": "已保存", "item": _serialize_doc(doc)})


_BATCH_EDIT_FIELDS = frozenset(
    {"status", "registrationSubmitted", "projectName", "projectCode", "registeredCountry"}
)
_BATCH_MAX_SIZE = 500


def _parse_batch_ids(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    for item in raw:
        value = str(item or "").strip()
        if value and value not in ids:
            ids.append(value)
        if len(ids) >= _BATCH_MAX_SIZE:
            break
    return ids


def _build_batch_update_payload(data: dict[str, Any]) -> tuple[dict[str, Any], Optional[str]]:
    payload: dict[str, Any] = {}
    if "status" in data:
        status = _parse_status_filter(str(data.get("status") or ""))
        if not status:
            return {}, "状态取值无效"
        payload["status"] = status
    if "registrationSubmitted" in data:
        payload["registrationSubmitted"] = bool(data.get("registrationSubmitted"))
    if "projectName" in data:
        payload["projectName"] = (data.get("projectName") or "").strip()
    if "projectCode" in data:
        payload["projectCode"] = (data.get("projectCode") or "").strip()
    if "registeredCountry" in data:
        payload["registeredCountry"] = (data.get("registeredCountry") or "").strip()
    unknown = set(data.keys()) - {"ids"} - _BATCH_EDIT_FIELDS
    if unknown:
        return {}, f"不支持批量修改字段：{', '.join(sorted(unknown))}"
    if not payload:
        return {}, "请至少指定一项要修改的内容"
    return payload, None


@document_control_bp.post("/api/document-control/documents/batch-update")
def api_document_control_batch_update():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    data = request.get_json(silent=True) or {}
    ids = _parse_batch_ids(data.get("ids"))
    if not ids:
        return jsonify({"message": "请先选择要修改的记录"}), 400
    payload, err = _build_batch_update_payload(data)
    if err:
        return jsonify({"message": err}), 400
    docs = (
        ControlledDocument.query.filter(
            ControlledDocument.organization_id == org_id,
            ControlledDocument.id.in_(ids),
        )
        .all()
    )
    found_ids = {doc.id for doc in docs}
    missing = [doc_id for doc_id in ids if doc_id not in found_ids]
    updated = 0
    failed: list[dict[str, str]] = []
    for doc_id in missing:
        failed.append({"id": doc_id, "message": "记录不存在"})
    for doc in docs:
        next_status = (
            payload["status"]
            if "status" in payload
            else (doc.status or _DOC_STATUS_CONTROLLED)
        )
        if next_status == _DOC_STATUS_CONTROLLED:
            conflict_msg = controlled_number_conflict_message(
                org_id, doc.normalized_document_number, exclude_id=doc.id
            )
            if conflict_msg:
                failed.append({"id": doc.id, "message": conflict_msg})
                continue
        apply_err = _apply_document_payload(doc, payload)
        if apply_err:
            failed.append({"id": doc.id, "message": apply_err})
            continue
        updated += 1
    if updated:
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({"message": "批量保存失败：存在受控编号冲突"}), 409
    else:
        db.session.rollback()
    message = f"已更新 {updated} 条"
    if failed:
        message += f"，失败 {len(failed)} 条"
    return jsonify({"message": message, "updated": updated, "failed": failed})


@document_control_bp.post("/api/document-control/documents/batch-delete")
def api_document_control_batch_delete():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    data = request.get_json(silent=True) or {}
    ids = _parse_batch_ids(data.get("ids"))
    if not ids:
        return jsonify({"message": "请先选择要删除的记录"}), 400
    docs = (
        ControlledDocument.query.filter(
            ControlledDocument.organization_id == org_id,
            ControlledDocument.id.in_(ids),
        )
        .all()
    )
    deleted = len(docs)
    for doc in docs:
        db.session.delete(doc)
    db.session.commit()
    missing = len(ids) - deleted
    message = f"已删除 {deleted} 条"
    if missing:
        message += f"，未找到 {missing} 条"
    return jsonify({"message": message, "deleted": deleted, "missing": missing})


@document_control_bp.get("/api/document-control/categories")
def api_document_control_categories():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    all_items = _list_sheet_categories(org_id)
    only_sheet = (request.args.get("sheetCategory") or "").strip()
    items_to_count = [only_sheet] if only_sheet else all_items
    counts: dict[str, int] = {}
    for name in items_to_count:
        q = _documents_base_query(org_id)
        q = _apply_document_filters(q)
        q = _apply_sheet_category_filter(q, name)
        counts[name] = q.count()
    if only_sheet:
        visible_items = [only_sheet] if counts.get(only_sheet, 0) > 0 else []
    else:
        visible_items = [name for name in all_items if counts.get(name, 0) > 0]
    visible_items = _sort_sheet_categories(visible_items, org_id)
    sheet_order = _load_sheet_order_map().get(org_id) or []
    return jsonify(
        {
            "items": visible_items,
            "counts": counts,
            "allItems": all_items,
            "sheetOrder": sheet_order,
        }
    )


def _serialize_import_log(row: DocumentControlImportLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "batchId": row.import_batch_id,
        "eventType": row.event_type,
        "documentNumber": row.document_number,
        "sheetName": row.sheet_name,
        "rowIndex": row.row_index,
        "reason": row.reason,
        "controlledDocumentId": row.controlled_document_id,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


def _import_logs_base_query(org_id: str):
    return DocumentControlImportLog.query.filter_by(organization_id=org_id)


def _import_log_batch_summaries(
    org_id: str, *, batch_id: Optional[str] = None
) -> list[dict[str, Any]]:
    q = _import_logs_base_query(org_id)
    if batch_id:
        q = q.filter(DocumentControlImportLog.import_batch_id == batch_id)
    q = q.filter(DocumentControlImportLog.import_batch_id.isnot(None))
    q = q.filter(DocumentControlImportLog.import_batch_id != "")
    rows = (
        q.with_entities(
            DocumentControlImportLog.import_batch_id.label("batch_id"),
            func.min(DocumentControlImportLog.created_at).label("started_at"),
            func.count().label("total"),
            func.sum(
                case((DocumentControlImportLog.event_type == "import_success", 1), else_=0)
            ).label("success"),
            func.sum(
                case((DocumentControlImportLog.event_type == "import_update", 1), else_=0)
            ).label("updated"),
            func.sum(
                case((DocumentControlImportLog.event_type == "import_skip", 1), else_=0)
            ).label("skip"),
            func.sum(
                case((DocumentControlImportLog.event_type == "import_fail", 1), else_=0)
            ).label("fail"),
            func.sum(
                case((DocumentControlImportLog.event_type == "registration_link", 1), else_=0)
            ).label("registrationLink"),
        )
        .group_by(DocumentControlImportLog.import_batch_id)
        .order_by(func.min(DocumentControlImportLog.created_at).desc())
        .all()
    )
    summaries: list[dict[str, Any]] = []
    for row in rows:
        summaries.append(
            {
                "batchId": row.batch_id,
                "startedAt": row.started_at.isoformat() if row.started_at else None,
                "total": int(row.total or 0),
                "success": int(row.success or 0),
                "updated": int(row.updated or 0),
                "skip": int(row.skip or 0),
                "fail": int(row.fail or 0),
                "registrationLink": int(row.registrationLink or 0),
            }
        )
    return summaries


@document_control_bp.get("/api/document-control/import/logs")
def api_document_control_import_logs():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    batch_id = (request.args.get("batchId") or "").strip()
    event_type = (request.args.get("eventType") or "").strip()
    page = max(1, int(request.args.get("page") or 1))
    page_size = min(500, max(10, int(request.args.get("pageSize") or 100)))
    q = _import_logs_base_query(org_id)
    if batch_id:
        q = q.filter(DocumentControlImportLog.import_batch_id == batch_id)
    if event_type:
        q = q.filter(DocumentControlImportLog.event_type == event_type)
    total = q.count()
    rows = (
        q.order_by(
            DocumentControlImportLog.created_at.desc(),
            DocumentControlImportLog.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    batches = _import_log_batch_summaries(org_id, batch_id=batch_id or None)
    return jsonify(
        {
            "items": [_serialize_import_log(row) for row in rows],
            "batches": batches,
            "total": total,
            "page": page,
            "pageSize": page_size,
        }
    )


@document_control_bp.get("/api/document-control/search")
def api_document_control_search():
    return api_document_control_documents()


@document_control_bp.route("/api/document-control/schemes", methods=["GET", "POST"])
def api_document_control_schemes():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    if request.method == "GET":
        rows = (
            NumberingScheme.query.filter_by(organization_id=org_id)
            .order_by(NumberingScheme.created_at.desc())
            .all()
        )
        return jsonify({"items": [_serialize_scheme(x) for x in rows]})
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    doc_type = (data.get("docTypeCode") or "").strip().upper()
    if not name or not doc_type:
        return jsonify({"message": "name 与 docTypeCode 必填"}), 400
    row = NumberingScheme(
        organization_id=org_id,
        name=name,
        doc_type_code=doc_type,
        pattern_regex=(data.get("patternRegex") or "").strip() or None,
        render_template=(data.get("renderTemplate") or "").strip()
        or "{prefix}-{type}-{seq:03d}",
        prefix_source=(data.get("prefixSource") or "fixed").strip() or "fixed",
        fixed_prefix=(data.get("fixedPrefix") or "").strip() or None,
        seq_scope=(data.get("seqScope") or "per_company").strip() or "per_company",
        seq_start=max(1, int(data.get("seqStart") or 1)),
        seq_pad=max(1, int(data.get("seqPad") or 3)),
        is_active=bool(data.get("isActive", True)),
        kb_rule_excerpt=(data.get("kbRuleExcerpt") or "").strip() or None,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({"message": "已创建", "item": _serialize_scheme(row)})


@document_control_bp.route("/api/document-control/schemes/<scheme_id>", methods=["PATCH", "DELETE"])
def api_document_control_scheme_update(scheme_id: str):
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    row = NumberingScheme.query.filter_by(id=scheme_id, organization_id=org_id).first()
    if not row:
        return jsonify({"message": "规则不存在"}), 404
    if request.method == "DELETE":
        db.session.delete(row)
        db.session.commit()
        return jsonify({"message": "已删除"})
    data = request.get_json(force=True) or {}
    for attr, key in (
        ("name", "name"),
        ("doc_type_code", "docTypeCode"),
        ("pattern_regex", "patternRegex"),
        ("render_template", "renderTemplate"),
        ("prefix_source", "prefixSource"),
        ("fixed_prefix", "fixedPrefix"),
        ("seq_scope", "seqScope"),
        ("kb_rule_excerpt", "kbRuleExcerpt"),
    ):
        if key in data:
            setattr(row, attr, (data.get(key) or "").strip() or None)
    if "seqStart" in data:
        row.seq_start = max(1, int(data.get("seqStart") or 1))
    if "seqPad" in data:
        row.seq_pad = max(1, int(data.get("seqPad") or 3))
    if "isActive" in data:
        row.is_active = bool(data.get("isActive"))
    db.session.add(row)
    db.session.commit()
    return jsonify({"message": "已更新", "item": _serialize_scheme(row)})


@document_control_bp.post("/api/document-control/allocate/preview")
def api_document_control_allocate_preview():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    data = request.get_json(force=True) or {}
    scheme_id = (data.get("schemeId") or "").strip()
    doc_type = (data.get("docTypeCode") or "").strip().upper()
    scheme = None
    if scheme_id:
        scheme = NumberingScheme.query.filter_by(id=scheme_id, organization_id=org_id).first()
    elif doc_type:
        scheme = NumberingScheme.query.filter_by(
            organization_id=org_id, doc_type_code=doc_type, is_active=True
        ).first()
    if not scheme:
        return jsonify({"message": "未找到可用编号规则"}), 404
    info = preview_next_number(
        organization_id=org_id,
        scheme=scheme,
        project_code=(data.get("projectCode") or "").strip() or None,
    )
    return jsonify({"item": info, "scheme": _serialize_scheme(scheme)})


@document_control_bp.post("/api/document-control/allocate/reserve")
def api_document_control_allocate_reserve():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    data = request.get_json(force=True) or {}
    scheme_id = (data.get("schemeId") or "").strip()
    scheme = NumberingScheme.query.filter_by(id=scheme_id, organization_id=org_id).first()
    if not scheme:
        return jsonify({"message": "规则不存在"}), 404
    try:
        row = reserve_number(
            organization_id=org_id,
            scheme=scheme,
            requested_title=(data.get("title") or "").strip(),
            project_id=(data.get("projectId") or "").strip() or None,
            project_code=(data.get("projectCode") or "").strip() or None,
            user_id=(session.get("user_id") or "").strip() or None,
            reserved_minutes=int(data.get("reservedMinutes") or 30),
        )
        db.session.commit()
        return jsonify(
            {
                "message": "已预留",
                "item": {
                    "id": row.id,
                    "allocatedNumber": row.allocated_number,
                    "status": row.status,
                    "reservedUntil": row.reserved_until.isoformat()
                    if row.reserved_until
                    else None,
                },
            }
        )
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"message": str(exc)}), 409


@document_control_bp.post("/api/document-control/allocate/issue")
def api_document_control_allocate_issue():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    data = request.get_json(force=True) or {}
    allocation_id = (data.get("allocationId") or "").strip()
    allocation = NumberAllocation.query.filter_by(
        id=allocation_id, organization_id=org_id
    ).first()
    if not allocation:
        return jsonify({"message": "预留记录不存在"}), 404
    doc = issue_number(
        organization_id=org_id,
        allocation=allocation,
        version=(data.get("version") or "").strip() or None,
        title=(data.get("title") or "").strip() or allocation.requested_title or "未命名文件",
        source=(data.get("source") or "").strip() or "allocated",
        upload_record_id=(data.get("uploadRecordId") or "").strip() or None,
        project_id=(data.get("projectId") or "").strip() or None,
        project_code=(data.get("projectCode") or "").strip() or None,
        user_id=(session.get("user_id") or "").strip() or None,
    )
    db.session.commit()
    return jsonify({"message": "已发放", "document": _serialize_doc(doc)})


def _excel_import_header_map() -> dict[str, str]:
    return {
        "文件编号": "documentNumber",
        "编号": "documentNumber",
        "文件号": "documentNumber",
        "受控编号": "documentNumber",
        "文档编号": "documentNumber",
        "document number": "documentNumber",
        "documentnumber": "documentNumber",
        "文件名称": "title",
        "名称": "title",
        "文档名称": "title",
        "文件名": "title",
        "文件名称（中文）": "title",
        "title": "title",
        "英文名": "titleEn",
        "文件名称（英文）": "titleEn",
        "版本号": "version",
        "版本": "version",
        "version": "version",
        "文件类型": "docTypeCode",
        "类型": "docTypeCode",
        "项目编号": "projectCode",
        "项目号": "projectCode",
        "所属项目": "projectName",
        "注册国家": "registeredCountry",
        "状态": "lifecycleStatus",
        "文件状态": "lifecycleStatus",
        "受控状态": "lifecycleStatus",
        "status": "lifecycleStatus",
    }


_EXCEL_VOIDED_STATUS_MARKERS = ("作废", "废止", "失效", "注销", "已作废", "已废止")
_EXCEL_CONTROLLED_STATUS_VALUES = frozenset(
    {
        "受控",
        "有效",
        "现行",
        "生效",
        "在用",
        "active",
        "controlled",
        "effective",
    }
)
_SHEET_ORDER_CONFIG_KEY = "DOCUMENT_CONTROL_SHEET_ORDER_BY_ORG"


def _normalize_sheet_tab_name(sheet_name: str) -> str:
    return (sheet_name or "").strip().replace(" ", "")


def _is_catalog_sheet(sheet_name: str) -> bool:
    """清单索引 Sheet：仅匹配「目录」「目录1」「目录2」等，不参与导入与操作日志。"""
    compact = _normalize_sheet_tab_name(sheet_name)
    if not compact:
        return False
    if compact == "目录":
        return True
    if compact.startswith("目录") and compact[2:].isdigit():
        return True
    return False


def _is_registration_sheet(sheet_name: str) -> bool:
    compact = _normalize_sheet_tab_name(sheet_name)
    return compact == _REGISTRATION_SHEET_NAME or compact.startswith(_REGISTRATION_SHEET_NAME)


def _should_track_registration_link_source(sheet_name: str) -> bool:
    name = (sheet_name or "").strip()
    if not name:
        return False
    if _is_registration_sheet(name) or _is_catalog_sheet(name):
        return False
    return True


def _can_registration_link_source(sheet_name: str) -> bool:
    return _should_track_registration_link_source(sheet_name)


def _load_sheet_order_map() -> dict[str, list[str]]:
    from webapp.models import AppConfig

    row = AppConfig.query.filter_by(config_key=_SHEET_ORDER_CONFIG_KEY).first()
    raw = (row.config_value if row and row.config_value is not None else "") or ""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for org_id, names in data.items():
        if isinstance(names, list):
            out[str(org_id)] = [str(x) for x in names if str(x).strip()]
    return out


def _save_org_sheet_order(org_id: str, sheet_order: list[str]) -> None:
    from webapp.models import AppConfig

    data = _load_sheet_order_map()
    cleaned = [str(x).strip() for x in sheet_order if str(x).strip()]
    data[org_id] = cleaned
    payload = json.dumps(data, ensure_ascii=False)
    row = AppConfig.query.filter_by(config_key=_SHEET_ORDER_CONFIG_KEY).first()
    if row:
        row.config_value = payload
        db.session.add(row)
    else:
        db.session.add(AppConfig(config_key=_SHEET_ORDER_CONFIG_KEY, config_value=payload))


def _sort_sheet_categories(categories: list[str], org_id: str) -> list[str]:
    order = _load_sheet_order_map().get(org_id) or []
    rank = {name: idx for idx, name in enumerate(order)}
    return sorted(categories, key=lambda name: (rank.get(name, 10_000), name))


def _note_link_source_norm(
    norm: str, sheet_name: str, link_source_norms: dict[str, str]
) -> None:
    if not norm or not _should_track_registration_link_source(sheet_name):
        return
    if norm not in link_source_norms:
        link_source_norms[norm] = (sheet_name or "").strip()


def _registration_target_hit(
    *,
    norm: str,
    document_number: str,
    sheet_name: str,
) -> dict[str, str]:
    return {
        "norm": norm,
        "documentNumber": document_number,
        "sheetName": sheet_name,
    }


def _build_registration_file_indexes(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, str]], dict[str, list[dict[str, str]]]]:
    by_norm: dict[str, dict[str, str]] = {}
    by_compare_key: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        sheet_name = (row.get("sheetName") or "").strip()
        if not _should_track_registration_link_source(sheet_name):
            continue
        doc_num = (row.get("documentNumber") or "").strip()
        norm = normalize_document_number(doc_num)
        if not norm or _is_invalid_document_number(doc_num, norm):
            continue
        hit = _registration_target_hit(
            norm=norm,
            document_number=doc_num,
            sheet_name=sheet_name,
        )
        by_norm.setdefault(norm, hit)
        compare_key = registration_compare_key(doc_num)
        if compare_key:
            bucket = by_compare_key.setdefault(compare_key, [])
            if not any(x.get("norm") == norm for x in bucket):
                bucket.append(hit)
    return by_norm, by_compare_key


def _add_registration_target(
    targets: list[dict[str, str]],
    seen_norms: set[str],
    hit: dict[str, str],
    match_type: str,
) -> None:
    norm = (hit.get("norm") or "").strip()
    if not norm or norm in seen_norms:
        return
    seen_norms.add(norm)
    targets.append({**hit, "matchType": match_type})


def _add_registration_target_from_doc(
    targets: list[dict[str, str]],
    seen_norms: set[str],
    doc: ControlledDocument,
    match_type: str,
) -> None:
    if (doc.status or "").strip().lower() == _DOC_STATUS_VOIDED:
        return
    if not _can_registration_link_source(doc.sheet_category or ""):
        return
    norm = (doc.normalized_document_number or "").strip()
    if not norm:
        return
    _add_registration_target(
        targets,
        seen_norms,
        _registration_target_hit(
            norm=norm,
            document_number=(doc.document_number or "").strip(),
            sheet_name=(doc.sheet_category or "").strip(),
        ),
        match_type,
    )


def _resolve_registration_targets(
    reg_row: dict[str, Any],
    *,
    file_by_norm: dict[str, dict[str, str]],
    file_by_compare_key: dict[str, list[dict[str, str]]],
    existing: dict[str, ControlledDocument],
) -> list[dict[str, str]]:
    doc_num = (reg_row.get("documentNumber") or "").strip()
    norm = normalize_document_number(doc_num)
    compare_key = registration_compare_key(doc_num) if doc_num else ""
    targets: list[dict[str, str]] = []
    seen_norms: set[str] = set()

    if norm and norm in file_by_norm:
        _add_registration_target(targets, seen_norms, file_by_norm[norm], "norm")
    if compare_key:
        for hit in file_by_compare_key.get(compare_key, []):
            _add_registration_target(targets, seen_norms, hit, "norm")
    if norm and norm in existing:
        _add_registration_target_from_doc(targets, seen_norms, existing[norm], "norm")
    if compare_key:
        for doc in existing.values():
            if registration_compare_key(doc.document_number or "") != compare_key:
                continue
            _add_registration_target_from_doc(targets, seen_norms, doc, "norm")

    return targets


def _registration_targets_summary(targets: list[dict[str, str]]) -> str:
    if not targets:
        return ""
    parts: list[str] = []
    by_sheet: dict[str, int] = {}
    for item in targets:
        sheet = (item.get("sheetName") or "").strip() or "未知分类"
        by_sheet[sheet] = by_sheet.get(sheet, 0) + 1
    for sheet in sorted(by_sheet):
        count = by_sheet[sheet]
        parts.append(f"{sheet} {count} 条" if count > 1 else sheet)
    return "、".join(parts)


def _excel_header_tokens(field: str) -> frozenset[str]:
    return frozenset(
        k for k, v in _excel_import_header_map().items() if v == field
    )


def _is_excel_noise_row(item: dict[str, Any]) -> bool:
    doc = (item.get("documentNumber") or "").strip()
    title = (item.get("title") or "").strip()
    lifecycle = (item.get("lifecycleStatus") or "").strip()
    if doc in _excel_header_tokens("documentNumber"):
        return True
    if title in _excel_header_tokens("title"):
        return True
    if lifecycle in _excel_header_tokens("lifecycleStatus") and not doc:
        return True
    if not doc and not title and not (item.get("version") or "").strip():
        return True
    return False


def _append_import_log(
    *,
    org_id: str,
    batch_id: str,
    user_id: Optional[str],
    event_type: str,
    row: dict[str, Any],
    reason: str,
    document_id: Optional[str] = None,
) -> None:
    doc_num = (row.get("documentNumber") or "").strip()
    db.session.add(
        DocumentControlImportLog(
            organization_id=org_id,
            import_batch_id=batch_id,
            event_type=event_type,
            document_number=doc_num or None,
            normalized_document_number=normalize_document_number(doc_num) or None,
            sheet_name=(row.get("sheetName") or row.get("sheetCategory") or "").strip() or None,
            row_index=int(row.get("rowIndex") or 0) or None,
            reason=(reason or "")[:512] or None,
            row_payload_json={
                k: row.get(k)
                for k in (
                    "title",
                    "titleEn",
                    "version",
                    "projectName",
                    "registeredCountry",
                    "lifecycleStatus",
                    "status",
                    "statusDetail",
                )
                if row.get(k)
            },
            controlled_document_id=document_id,
            created_by_user_id=user_id,
        )
    )


def _headers_have_status_column(headers: list[str]) -> bool:
    status_keys = {
        k.lower() for k, v in _excel_import_header_map().items() if v == "lifecycleStatus"
    }
    return bool(status_keys & {h.lower() for h in headers if h})


def _is_excel_lifecycle_importable(
    raw: str, *, has_status_column: bool, has_document_number: bool = False
) -> tuple[bool, str]:
    text = (raw or "").strip()
    if not has_status_column:
        return True, ""
    if not text:
        if has_document_number:
            return True, ""
        return False, "状态为空，仅导入受控文件"
    compact = text.replace(" ", "").lower()
    if any(marker in text for marker in _EXCEL_VOIDED_STATUS_MARKERS):
        return False, "状态为作废，不导入"
    if compact in {"void", "voided", "obsolete", "cancelled", "canceled", "inactive"}:
        return False, "状态为作废，不导入"
    if any(marker in text for marker in ("非受控", "不受控")):
        return False, f"状态为「{text}」，非受控"
    if text in _EXCEL_CONTROLLED_STATUS_VALUES or compact in _EXCEL_CONTROLLED_STATUS_VALUES:
        return True, ""
    if text == "受控":
        return True, ""
    return False, f"状态为「{text}」，非受控"


def _sheet_import_priority(sheet_name: str) -> int:
    if _is_catalog_sheet(sheet_name):
        return 1
    return 10


def _is_invalid_document_number(doc_num: str, norm: str) -> bool:
    raw = (doc_num or "").strip()
    if not norm:
        return True
    if raw in {"/", "-", "—", "无", "N/A", "NA", "n/a"}:
        return True
    return False


def _apply_existing_doc_status(
    status: str,
    status_detail: str,
    *,
    norm: str,
    title: str,
    existing: dict[str, ControlledDocument],
) -> tuple[str, str]:
    exists = existing.get(norm)
    if not exists:
        return status, status_detail
    return (
        "update",
        f"台账已有受控记录，将按 Excel 增量更新（编号：{exists.document_number or norm}）",
    )


def _apply_excel_row_to_document(
    doc: ControlledDocument, row: dict[str, Any]
) -> list[str]:
    updated_fields: list[str] = []
    title = (row.get("title") or "").strip()
    if title and (doc.title or "").strip() != title:
        doc.title = title
        updated_fields.append("文件名称")
    version = (row.get("version") or "").strip()
    if version != (doc.version or "").strip():
        doc.version = version or None
        if version:
            updated_fields.append("版本")
    title_en = (row.get("titleEn") or "").strip()
    if title_en != (doc.title_en or "").strip():
        doc.title_en = title_en or None
        if title_en:
            updated_fields.append("英文名")
    project_code = (row.get("projectCode") or "").strip()
    if project_code != (doc.project_code or "").strip():
        doc.project_code = project_code or None
        if project_code:
            updated_fields.append("项目编号")
    project_name = (row.get("projectName") or "").strip()
    if project_name != (doc.project_name or "").strip():
        doc.project_name = project_name or None
        if project_name:
            updated_fields.append("所属项目")
    registered_country = (row.get("registeredCountry") or "").strip()
    if registered_country != (doc.registered_country or "").strip():
        doc.registered_country = registered_country or None
        if registered_country:
            updated_fields.append("注册国家")
    doc_type = (row.get("docTypeCode") or "").strip()
    if doc_type != (doc.doc_type_code or "").strip():
        doc.doc_type_code = doc_type or None
        if doc_type:
            updated_fields.append("文件类型")
    sheet_category = (row.get("sheetName") or row.get("sheetCategory") or "").strip()
    if sheet_category and sheet_category != (doc.sheet_category or "").strip():
        doc.sheet_category = sheet_category
        updated_fields.append("分类")
    row_index = _excel_row_index_from_row(row)
    if row_index is not None and row_index != doc.excel_row_index:
        doc.excel_row_index = row_index
    batch_id = (row.get("importBatchId") or "").strip()
    meta = dict(doc.metadata_json or {}) if isinstance(doc.metadata_json, dict) else {}
    if title_en:
        meta["titleEn"] = title_en
    elif "titleEn" in meta and not title_en:
        meta.pop("titleEn", None)
    doc.metadata_json = meta or None
    doc.updated_at = now_local()
    return updated_fields


def _find_excel_header_row(rows: list[tuple]) -> tuple[int, list[str]] | None:
    header_map = _excel_import_header_map()
    doc_keys = {k.lower() for k, v in header_map.items() if v == "documentNumber"}
    for idx, row in enumerate(rows):
        headers = [str(x).strip() if x is not None else "" for x in row]
        normalized_headers = {h.lower() for h in headers if h}
        if doc_keys & normalized_headers:
            return idx, headers
    return None


def _parse_excel_row(headers: list[str], values: list[str]) -> dict[str, Any]:
    header_map = _excel_import_header_map()
    data: dict[str, str] = {}
    for header, value in zip(headers, values):
        key = header_map.get(header) or header_map.get(header.lower())
        if key:
            data[key] = value
    return {
        "documentNumber": data.get("documentNumber", ""),
        "title": data.get("title", ""),
        "titleEn": data.get("titleEn", ""),
        "version": data.get("version", ""),
        "docTypeCode": data.get("docTypeCode", ""),
        "projectCode": data.get("projectCode", ""),
        "projectName": data.get("projectName", ""),
        "registeredCountry": data.get("registeredCountry", ""),
        "lifecycleStatus": data.get("lifecycleStatus", ""),
    }


def _read_excel_rows(
    file_bytes: bytes,
) -> tuple[list[dict[str, Any]], Optional[str], bool, list[str]]:
    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    all_rows: list[dict[str, Any]] = []
    sheet_order: list[str] = []
    has_status_column = False
    parse_error: Optional[str] = None
    try:
        for ws in wb.worksheets:
            if _is_catalog_sheet(ws.title):
                continue
            raw_rows = list(ws.iter_rows(values_only=True))
            if not raw_rows:
                continue
            found = _find_excel_header_row(raw_rows)
            if found is None:
                continue
            sheet_order.append(ws.title)
            header_idx, headers = found
            sheet_has_status = _headers_have_status_column(headers)
            if sheet_has_status:
                has_status_column = True
            for idx, row in enumerate(raw_rows[header_idx + 1 :], start=header_idx + 2):
                values = [str(x).strip() if x is not None else "" for x in row]
                if not any(values):
                    continue
                item = _parse_excel_row(headers, values)
                if _is_excel_noise_row(item):
                    continue
                item["rowIndex"] = idx
                item["sheetName"] = ws.title
                item["hasStatusColumn"] = sheet_has_status
                all_rows.append(item)
        if not all_rows:
            parse_error = (
                "未识别到有效表头，请确认至少一个工作表含「文件编号/编号」等列"
                "（支持：文件名称、版本号、状态、所属项目、注册国家）"
            )
    finally:
        wb.close()
    return all_rows, parse_error, has_status_column, sheet_order


def _load_existing_docs_by_norm(org_id: str) -> dict[str, ControlledDocument]:
    """导入/判重时仅与受控台账比对；作废编号允许重复。"""
    return load_controlled_docs_by_norm(org_id)


def _build_excel_import_preview(
    rows: list[dict[str, Any]], org_id: str, *, has_status_column: bool = False
) -> list[dict[str, Any]]:
    existing = _load_existing_docs_by_norm(org_id)
    file_by_norm, file_by_compare_key = _build_registration_file_indexes(rows)
    seen_in_file: dict[str, dict[str, Any]] = {}
    link_source_norms: dict[str, str] = {}
    preview: list[dict[str, Any]] = []

    def _append_preview(row: dict[str, Any], status: str, status_detail: str) -> int:
        preview.append(
            {
                **row,
                "sheetCategory": row.get("sheetName") or "",
                "lifecycleStatus": (row.get("lifecycleStatus") or "").strip(),
                "normalizedDocumentNumber": normalize_document_number(
                    (row.get("documentNumber") or "").strip()
                ),
                "status": status,
                "statusDetail": status_detail,
            }
        )
        return len(preview) - 1

    for row in rows:
        doc_num = (row.get("documentNumber") or "").strip()
        norm = normalize_document_number(doc_num)
        title = (row.get("title") or "").strip()
        lifecycle_status = (row.get("lifecycleStatus") or "").strip()
        row_has_status_column = bool(row.get("hasStatusColumn"))
        sheet_name = row.get("sheetName") or ""
        priority = _sheet_import_priority(sheet_name)
        if (
            norm
            and not _is_invalid_document_number(doc_num, norm)
            and _should_track_registration_link_source(sheet_name)
        ):
            _note_link_source_norm(norm, sheet_name, link_source_norms)
        importable, lifecycle_detail = _is_excel_lifecycle_importable(
            lifecycle_status,
            has_status_column=row_has_status_column,
            has_document_number=bool(norm) and not _is_invalid_document_number(doc_num, norm),
        )
        status = "new"
        status_detail = ""
        if not importable:
            status = "not_controlled"
            status_detail = lifecycle_detail
        elif _is_invalid_document_number(doc_num, norm):
            status = "invalid"
            status_detail = "缺少有效文件编号"
        elif _is_registration_sheet(sheet_name):
            reg_targets = _resolve_registration_targets(
                row,
                file_by_norm=file_by_norm,
                file_by_compare_key=file_by_compare_key,
                existing=existing,
            )
            if reg_targets:
                status = "registration_update"
                row["_registrationTargets"] = reg_targets
                summary = _registration_targets_summary(reg_targets)
                status_detail = (
                    f"将关联注册文件清单至：{summary}" if summary else "将关联注册文件清单"
                )
            elif norm in seen_in_file:
                prev = seen_in_file[norm]
                status = "duplicate_in_file"
                status_detail = (
                    f"与 {prev.get('sheetName')}!{prev.get('rowIndex')} 行重复"
                )
            else:
                status, status_detail = _apply_existing_doc_status(
                    "new",
                    "",
                    norm=norm,
                    title=title,
                    existing=existing,
                )
        elif norm in seen_in_file:
            prev = seen_in_file[norm]
            if priority > int(prev.get("priority") or 0):
                preview[prev["previewIndex"]]["status"] = "duplicate_in_file"
                preview[prev["previewIndex"]]["statusDetail"] = (
                    f"与 {sheet_name} 中同编号记录重复，已保留 {sheet_name} 分类"
                )
                status, status_detail = _apply_existing_doc_status(
                    "new",
                    "",
                    norm=norm,
                    title=title,
                    existing=existing,
                )
                seen_in_file[norm] = {
                    "previewIndex": _append_preview(row, status, status_detail),
                    "priority": priority,
                    "sheetName": sheet_name,
                    "rowIndex": int(row.get("rowIndex") or 0),
                }
                _note_link_source_norm(norm, sheet_name, link_source_norms)
                continue
            status = "duplicate_in_file"
            status_detail = (
                f"与 {prev.get('sheetName')}!{prev.get('rowIndex')} 行重复"
                if prev.get("sheetName")
                else f"与第 {prev.get('rowIndex')} 行重复"
            )
        else:
            status, status_detail = _apply_existing_doc_status(
                "new",
                "",
                norm=norm,
                title=title,
                existing=existing,
            )
            preview_index = _append_preview(row, status, status_detail)
            if status in ("new", "update"):
                seen_in_file[norm] = {
                    "previewIndex": preview_index,
                    "priority": priority,
                    "sheetName": sheet_name,
                    "rowIndex": int(row.get("rowIndex") or 0),
                }
            _note_link_source_norm(norm, sheet_name, link_source_norms)
            continue

        preview_index = _append_preview(row, status, status_detail)
        if status in ("new", "update"):
            seen_in_file[norm] = {
                "previewIndex": preview_index,
                "priority": priority,
                "sheetName": sheet_name,
                "rowIndex": int(row.get("rowIndex") or 0),
            }
        _note_link_source_norm(norm, sheet_name, link_source_norms)

    return preview


def _apply_registration_update(
    doc: ControlledDocument, row: dict[str, Any]
) -> None:
    doc.registration_submitted = True
    project_name = (row.get("projectName") or "").strip()
    registered_country = (row.get("registeredCountry") or "").strip()
    title_en = (row.get("titleEn") or "").strip()
    updated_fields: list[str] = []
    if title_en:
        doc.title_en = title_en
        updated_fields.append("英文名")
    if project_name:
        doc.project_name = project_name
        updated_fields.append("所属项目")
    if registered_country:
        doc.registered_country = registered_country
        updated_fields.append("注册国家")
    meta = dict(doc.metadata_json or {})
    if title_en:
        meta["titleEn"] = title_en
    meta["registrationLinkedFromSheet"] = _REGISTRATION_SHEET_NAME
    meta["registrationLinkedAt"] = now_local().isoformat()
    doc.metadata_json = meta
    doc.updated_at = now_local()
    row["_registrationUpdatedFields"] = updated_fields


def _import_excel_rows(
    preview: list[dict[str, Any]], org_id: str, batch_id: str, user_id: Optional[str]
) -> tuple[int, int, int, list[dict[str, Any]]]:
    existing = _load_existing_docs_by_norm(org_id)
    imported_in_batch: set[str] = set()
    updated_in_batch: set[str] = set()
    imported = 0
    updated = 0
    registration_updated = 0
    skipped: list[dict[str, Any]] = []

    for row in preview:
        if row.get("status") != "new":
            continue
        doc_num = (row.get("documentNumber") or "").strip()
        norm = normalize_document_number(doc_num)
        if not norm:
            reason = "缺少文件编号"
            skipped.append({**row, "skipReason": reason})
            _append_import_log(
                org_id=org_id,
                batch_id=batch_id,
                user_id=user_id,
                event_type="import_skip",
                row=row,
                reason=reason,
            )
            continue
        if norm in imported_in_batch:
            reason = row.get("statusDetail") or "本批导入中受控编号重复"
            skipped.append({**row, "skipReason": reason})
            _append_import_log(
                org_id=org_id,
                batch_id=batch_id,
                user_id=user_id,
                event_type="import_skip",
                row=row,
                reason=reason,
            )
            continue
        conflict_msg = controlled_number_conflict_message(org_id, norm)
        if conflict_msg or norm in existing:
            reason = row.get("statusDetail") or conflict_msg or "受控编号已存在"
            skipped.append({**row, "skipReason": reason})
            _append_import_log(
                org_id=org_id,
                batch_id=batch_id,
                user_id=user_id,
                event_type="import_skip",
                row=row,
                reason=reason,
            )
            continue
        title_en = (row.get("titleEn") or "").strip()
        metadata_json = {"titleEn": title_en} if title_en else None
        doc = ControlledDocument(
            organization_id=org_id,
            document_number=doc_num,
            normalized_document_number=norm,
            version=(row.get("version") or "").strip() or None,
            title=(row.get("title") or "").strip() or "未命名文件",
            title_en=title_en or None,
            doc_type_code=(row.get("docTypeCode") or "").strip() or None,
            project_code=(row.get("projectCode") or "").strip() or None,
            project_name=(row.get("projectName") or "").strip() or None,
            registered_country=(row.get("registeredCountry") or "").strip() or None,
            sheet_category=(row.get("sheetName") or row.get("sheetCategory") or "").strip() or None,
            excel_row_index=_excel_row_index_from_row(row),
            status=_DOC_STATUS_CONTROLLED,
            metadata_json=metadata_json,
            source="excel_import",
            import_batch_id=batch_id,
            created_by_user_id=user_id,
        )
        try:
            with db.session.begin_nested():
                db.session.add(doc)
                db.session.flush()
        except IntegrityError:
            reason = "受控编号已存在（并发冲突）"
            skipped.append({**row, "skipReason": reason})
            _append_import_log(
                org_id=org_id,
                batch_id=batch_id,
                user_id=user_id,
                event_type="import_fail",
                row=row,
                reason=reason,
            )
            existing = _load_existing_docs_by_norm(org_id)
            continue
        imported_in_batch.add(norm)
        existing[norm] = doc
        imported += 1
        _append_import_log(
            org_id=org_id,
            batch_id=batch_id,
            user_id=user_id,
            event_type="import_success",
            row=row,
            reason="导入成功",
            document_id=doc.id,
        )

    for row in preview:
        if row.get("status") != "update":
            continue
        doc_num = (row.get("documentNumber") or "").strip()
        norm = normalize_document_number(doc_num)
        if not norm:
            continue
        if norm in updated_in_batch or norm in imported_in_batch:
            continue
        doc = existing.get(norm)
        if not doc:
            reason = "未找到可更新的受控台账记录"
            skipped.append({**row, "skipReason": reason})
            _append_import_log(
                org_id=org_id,
                batch_id=batch_id,
                user_id=user_id,
                event_type="import_fail",
                row=row,
                reason=reason,
            )
            continue
        row_with_batch = {**row, "importBatchId": batch_id}
        updated_fields = _apply_excel_row_to_document(doc, row_with_batch)
        doc.import_batch_id = batch_id
        updated += 1
        updated_in_batch.add(norm)
        reason = "增量更新成功"
        if updated_fields:
            reason = f"{reason}：已更新 {'、'.join(updated_fields)}"
        elif (row.get("statusDetail") or "").strip():
            reason = row.get("statusDetail") or reason
        _append_import_log(
            org_id=org_id,
            batch_id=batch_id,
            user_id=user_id,
            event_type="import_update",
            row=row,
            reason=reason,
            document_id=doc.id,
        )

    registration_linked_docs: set[str] = set()
    for row in preview:
        if row.get("status") != "registration_update":
            continue
        targets = row.get("_registrationTargets") or []
        if not targets:
            doc_num = (row.get("documentNumber") or "").strip()
            norm = normalize_document_number(doc_num)
            if norm:
                targets = [{"norm": norm, "matchType": "norm"}]
        linked = 0
        for target in targets:
            tgt_norm = (target.get("norm") or "").strip()
            if not tgt_norm or tgt_norm in registration_linked_docs:
                continue
            doc = existing.get(tgt_norm)
            if not doc:
                continue
            if not _can_registration_link_source(doc.sheet_category or ""):
                continue
            if (doc.status or "").strip().lower() == _DOC_STATUS_VOIDED:
                continue
            link_row = {
                **row,
                "statusDetail": (
                    f"注册关联（{target.get('matchType') or 'match'}）"
                    f"：{doc.sheet_category or '-'} / {doc.document_number or tgt_norm}"
                ),
            }
            _apply_registration_update(doc, link_row)
            registration_updated += 1
            registration_linked_docs.add(tgt_norm)
            linked += 1
            updated_fields = link_row.get("_registrationUpdatedFields") or []
            link_reason = link_row.get("statusDetail") or "已关联注册文件清单"
            if updated_fields:
                link_reason = f"{link_reason}；已更新：{'、'.join(updated_fields)}"
            _append_import_log(
                org_id=org_id,
                batch_id=batch_id,
                user_id=user_id,
                event_type="registration_link",
                row=link_row,
                reason=link_reason,
                document_id=doc.id,
            )
        if not linked:
            reason = "未找到可关联的受控台账记录（注册文件编号与程序文件/四级表单/SOP/DHF 规范后仍无一致编号）"
            skipped.append({**row, "skipReason": reason})
            _append_import_log(
                org_id=org_id,
                batch_id=batch_id,
                user_id=user_id,
                event_type="import_fail",
                row=row,
                reason=reason,
            )

    skip_statuses = {
        "duplicate_in_file",
        "not_controlled",
        "invalid",
    }
    for row in preview:
        status = row.get("status") or ""
        if status in ("new", "update", "registration_update", "import_success"):
            continue
        if status in skip_statuses:
            _append_import_log(
                org_id=org_id,
                batch_id=batch_id,
                user_id=user_id,
                event_type="import_skip",
                row=row,
                reason=row.get("statusDetail") or status,
            )

    db.session.commit()
    return imported, updated, registration_updated, skipped


@document_control_bp.post("/api/document-control/import/excel")
def api_document_control_import_excel():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, _ = _org_context()
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"message": "请上传 Excel 文件"}), 400
    rows, parse_error, has_status_column, sheet_order = _read_excel_rows(file.read())
    if parse_error:
        return jsonify({"message": parse_error}), 400
    preview = _build_excel_import_preview(
        rows, org_id, has_status_column=has_status_column
    )
    confirm = str(request.form.get("confirm") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    imported = 0
    updated = 0
    registration_updated = 0
    skipped: list[dict[str, Any]] = []
    batch_id = uuid.uuid4().hex[:12]
    if confirm:
        user_id = (session.get("user_id") or "").strip() or None
        try:
            imported, updated, registration_updated, skipped = _import_excel_rows(
                preview, org_id, batch_id, user_id
            )
            _save_org_sheet_order(org_id, sheet_order)
        except IntegrityError:
            db.session.rollback()
            return jsonify(
                {
                    "message": "导入失败：存在重复编号，请刷新预览后重试",
                    "preview": preview,
                    "confirm": True,
                    "imported": 0,
                    "updated": 0,
                    "registrationUpdated": 0,
                    "skipped": skipped,
                    "batchId": batch_id,
                }
            ), 409
    summary = {
        "total": len(preview),
        "new": sum(1 for x in preview if x.get("status") == "new"),
        "update": sum(1 for x in preview if x.get("status") == "update"),
        "registrationUpdate": sum(
            1 for x in preview if x.get("status") == "registration_update"
        ),
        "duplicateInFile": sum(1 for x in preview if x.get("status") == "duplicate_in_file"),
        "invalid": sum(1 for x in preview if x.get("status") == "invalid"),
        "notControlled": sum(1 for x in preview if x.get("status") == "not_controlled"),
        "hasStatusColumn": has_status_column,
        "sheetOrder": sheet_order,
    }
    return jsonify(
        {
            "preview": preview,
            "summary": summary,
            "confirm": confirm,
            "imported": imported,
            "updated": updated,
            "registrationUpdated": registration_updated,
            "skipped": skipped,
            "batchId": batch_id if confirm else None,
        }
    )


@document_control_bp.post("/api/document-control/import/files")
def api_document_control_import_files():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, collection = _org_context()
    base = integration_api_base()
    if not base:
        return jsonify({"message": "未配置文档服务地址"}), 400
    files = request.files.getlist("files")
    multipart = [("files", (f.filename, f.stream, f.mimetype)) for f in files if f and f.filename]
    if not multipart:
        return jsonify({"message": "请上传文件"}), 400
    try:
        resp = requests.post(
            f"{base}/api/integration/document-control/extract-batch",
            data={"collection": collection},
            files=multipart,
            headers=upstream_headers(for_multipart=True, organization_id=org_id),
            timeout=integration_requests_timeout(read_seconds=180),
        )
    except requests.RequestException as exc:
        return jsonify({"message": format_upstream_request_error(exc, base)}), 502
    if resp.status_code != 200:
        return jsonify(
            {
                "message": user_facing_upstream_error(
                    f"上游提取失败 HTTP {resp.status_code}",
                    "文档识别服务暂不可用，请稍后重试",
                )
            }
        ), 502
    data = resp.json()
    return jsonify(data)


@document_control_bp.post("/api/document-control/schemes/sync-from-kb")
def api_document_control_sync_from_kb():
    blocked = _require_feature()
    if blocked is not None:
        return blocked
    wall = login_wall()
    if wall is not None:
        return wall
    org_id, collection = _org_context()
    base = integration_api_base()
    if not base:
        return jsonify({"message": "未配置文档服务地址"}), 400
    body = request.get_json(force=True) or {}
    payload = {
        "collection": collection,
        "query": (body.get("query") or "文件控制程序 编号规则").strip(),
    }
    try:
        resp = requests.post(
            f"{base}/api/integration/document-control/parse-numbering-rules",
            json=payload,
            headers=upstream_headers(for_multipart=False, organization_id=org_id),
            timeout=integration_requests_timeout(read_seconds=120),
        )
    except requests.RequestException as exc:
        return jsonify({"message": format_upstream_request_error(exc, base)}), 502
    if resp.status_code != 200:
        return jsonify({"message": f"规则解析失败 HTTP {resp.status_code}"}), 502
    return jsonify(resp.json())

