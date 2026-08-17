from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy import or_

from webapp import db
from webapp.models import (
    Project,
    ProjectKnowledgeDocumentVersion,
    ProjectKnowledgeSyncOutbox,
    UploadRecord,
    generate_uuid,
)


def normalize_project_kb_document_number(value: str) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    text = re.sub(r"[\s_]+", "-", text)
    text = text.replace("—", "-").replace("–", "-").replace("－", "-")
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")


def _project_task_match_keys(project: Any) -> list[str]:
    name = str(getattr(project, "name", "") or "").strip()
    country = str(getattr(project, "registered_country", "") or "").strip()
    category = str(getattr(project, "registered_category", "") or "").strip()
    keys: list[str] = []
    if name:
        keys.append(name)
    if name and (country or category):
        keys.append(f"{name}（{country or '—'} / {category or '—'}）")
    return keys


def _project_kb_upload_query(*, org_id: str, project_id: str, project_name: str = "", extra_names: list[str] | None = None):
    """按页面1 项目取任务：project_id 或项目名/展示名均可命中。不读取文件二进制。"""
    pid = str(project_id or "").strip()
    names = []
    for n in [project_name, *(extra_names or [])]:
        text = str(n or "").strip()
        if text and text not in names:
            names.append(text)
    clauses = []
    if pid:
        clauses.append(UploadRecord.project_id == pid)
    if names:
        clauses.append(UploadRecord.project_name.in_(names))
    if not clauses:
        return UploadRecord.query.filter(UploadRecord.id.is_(None))
    return UploadRecord.query.filter(or_(*clauses))


def _upload_has_kb_source(
    *,
    has_blob: bool = False,
    ftp_path: str = "",
    storage_path: str = "",
    template_links: str = "",
    row: Any = None,
) -> bool:
    if row is not None:
        has_blob = bool(getattr(row, "template_file_blob", None) or has_blob)
        ftp_path = str(getattr(row, "ftp_path", "") or ftp_path)
        storage_path = str(getattr(row, "storage_path", "") or storage_path)
        template_links = str(getattr(row, "template_links", "") or template_links)
    return bool(
        has_blob
        or str(ftp_path or "").strip()
        or str(storage_path or "").strip()
        or str(template_links or "").strip()
    )


def _classify_project_kb_task(*, has_source: bool, document_number: str, sync_state: str) -> str:
    if not has_source:
        return "no_file"
    if not str(document_number or "").strip():
        return "missing_number"
    state = str(sync_state or "").strip().lower()
    if state == "synced":
        return "synced"
    if state == "failed":
        return "failed"
    if state in {"pending", "syncing"}:
        return "pending"
    return "ready"


def _upload_ids_with_blob(upload_ids: list[str]) -> set[str]:
    ids = [str(x or "").strip() for x in upload_ids if str(x or "").strip()]
    if not ids:
        return set()
    rows = (
        db.session.query(UploadRecord.id)
        .filter(
            UploadRecord.id.in_(ids),
            UploadRecord.template_file_blob.isnot(None),
        )
        .all()
    )
    return {str(row[0]).strip() for row in rows if row and row[0]}


def _empty_project_kb_stats() -> dict[str, Any]:
    return {
        "taskCount": 0,
        "syncedCount": 0,
        "failedCount": 0,
        "pendingCount": 0,
        "readyCount": 0,
        "missingDocumentNumberCount": 0,
        "noFileCount": 0,
        "latestCount": 0,
        "lastUpdatedAt": "",
    }


def _kb_sync_map_for_projects(*, org_id: str, project_ids: list[str]) -> dict[tuple[str, str], dict[str, Any]]:
    ids = [str(x or "").strip() for x in project_ids if str(x or "").strip()]
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if not ids:
        return out
    rows = ProjectKnowledgeDocumentVersion.query.filter(
        ProjectKnowledgeDocumentVersion.organization_id == org_id,
        ProjectKnowledgeDocumentVersion.project_id.in_(ids),
        or_(
            ProjectKnowledgeDocumentVersion.is_latest == True,
            ProjectKnowledgeDocumentVersion.sync_state == "failed",
        ),
    ).all()
    for row in rows:
        pid = str(row.project_id or "").strip()
        norm = str(row.normalized_document_number or "").strip()
        if not pid or not norm:
            continue
        key = (pid, norm)
        prev = out.get(key)
        if prev and prev.get("isLatest") and not bool(row.is_latest):
            if str(prev.get("syncState") or "").lower() != "failed" and str(row.sync_state or "").lower() == "failed":
                prev["syncState"] = "failed"
                prev["syncError"] = str(row.sync_error or "")
            continue
        out[key] = {
            "id": row.id,
            "syncState": str(row.sync_state or "").strip() or "pending",
            "syncError": str(row.sync_error or ""),
            "isLatest": bool(row.is_latest),
            "version": row.version or "",
            "updatedAt": row.updated_at,
        }
    outbox_rows = ProjectKnowledgeSyncOutbox.query.filter(
        ProjectKnowledgeSyncOutbox.organization_id == org_id,
        ProjectKnowledgeSyncOutbox.project_id.in_(ids),
        ProjectKnowledgeSyncOutbox.status == "failed",
    ).all()
    for box in outbox_rows:
        payload = dict(box.payload_json or {}) if isinstance(box.payload_json, dict) else {}
        pid = str(box.project_id or "").strip()
        norm = str(payload.get("normalizedDocumentNumber") or "").strip()
        if not pid or not norm:
            continue
        key = (pid, norm)
        item = out.get(key)
        if item:
            item["syncState"] = "failed"
            if box.last_error:
                item["syncError"] = str(box.last_error)
            continue
        out[key] = {
            "id": str((payload.get("metadata") or {}).get("versionRecordId") or box.id or "").strip(),
            "syncState": "failed",
            "syncError": str(box.last_error or ""),
            "isLatest": False,
            "version": str(payload.get("version") or ""),
            "updatedAt": box.updated_at,
        }
    return out


def _serialize_project_kb_doc(row: ProjectKnowledgeDocumentVersion) -> dict[str, Any]:
    return {
        "id": row.id,
        "projectId": row.project_id,
        "documentNumber": row.document_number,
        "normalizedDocumentNumber": row.normalized_document_number,
        "title": row.title,
        "version": row.version,
        "status": row.status,
        "fileUri": row.file_uri or "",
        "checksum": row.source_checksum or "",
        "publishedAt": row.published_at.isoformat() if row.published_at else "",
        "sourceUpdatedAt": row.source_updated_at.isoformat() if row.source_updated_at else "",
        "isLatest": bool(row.is_latest),
        "isDeleted": str(row.status or "").strip().lower() == "deleted",
        "syncState": row.sync_state,
        "syncError": row.sync_error or "",
        "syncedAt": row.synced_at.isoformat() if row.synced_at else "",
        "updatedAt": row.updated_at.isoformat() if row.updated_at else "",
        "metadata": dict(row.metadata_json or {}),
    }


def _project_kb_doc_checksum(
    *,
    normalized_document_number: str,
    version: str,
    source_updated_at: Any,
    title: str,
    status: str,
) -> str:
    raw = "|".join(
        [
            str(normalized_document_number or "").strip(),
            str(version or "").strip(),
            str(source_updated_at or ""),
            str(title or "").strip(),
            str(status or "").strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def refresh_project_kb_document_versions(
    *,
    org_id: str,
    project_id: str,
) -> list[dict[str, Any]]:
    pid = str(project_id or "").strip()
    if not pid:
        return []
    extra_names: list[str] = []
    proj = Project.query.filter_by(id=pid).first()
    if proj is not None:
        extra_names = _project_task_match_keys(proj)
    rows = (
        _project_kb_upload_query(org_id=org_id, project_id=pid, extra_names=extra_names)
        .order_by(UploadRecord.updated_at.desc(), UploadRecord.created_at.desc())
        .all()
    )
    latest_by_doc: dict[str, UploadRecord] = {}
    for row in rows:
        doc_no = str(getattr(row, "document_number", "") or "").strip()
        if not doc_no:
            # 项目知识库硬约束：必须有文件编号才允许入库。
            continue
        has_source = bool(
            (getattr(row, "template_file_blob", None))
            or str(getattr(row, "ftp_path", "") or "").strip()
            or str(getattr(row, "storage_path", "") or "").strip()
            or str(getattr(row, "template_links", "") or "").strip()
        )
        if not has_source:
            continue
        norm = normalize_project_kb_document_number(doc_no)
        if not norm:
            continue
        if norm not in latest_by_doc:
            latest_by_doc[norm] = row
    touched: list[dict[str, Any]] = []
    stale_latest = (
        ProjectKnowledgeDocumentVersion.query.filter_by(
            organization_id=org_id,
            project_id=pid,
            is_latest=True,
        ).all()
    )
    stale_keys = {
        str(x.normalized_document_number or "").strip()
        for x in stale_latest
        if str(x.normalized_document_number or "").strip() not in latest_by_doc
    }
    for stale in stale_latest:
        stale_norm = str(stale.normalized_document_number or "").strip()
        if stale_norm not in stale_keys:
            continue
        if str(stale.sync_state or "").strip().lower() == "failed":
            # 源文件暂时对不上时仍保留失败最新版，避免「有失败、点开却是空列表」。
            continue
        stale.is_latest = False
        stale.status = "deleted"
        stale.sync_state = "pending"
        stale.sync_error = None
        db.session.add(stale)
        touched.append(
            {
                "id": stale.id,
                "organizationId": org_id,
                "projectId": pid,
                "documentNumber": stale.document_number,
                "normalizedDocumentNumber": stale.normalized_document_number,
                "version": stale.version or "UNSPECIFIED",
                "title": stale.title or "",
                "status": "deleted",
                "fileUri": stale.file_uri or "",
                "checksum": stale.source_checksum or "",
                "sourceUpdatedAt": (
                    stale.source_updated_at.isoformat() if stale.source_updated_at else ""
                ),
                "publishedAt": stale.published_at.isoformat() if stale.published_at else "",
                "isDeleted": True,
                "metadata": dict(stale.metadata_json or {}),
            }
        )
    for norm, src in latest_by_doc.items():
        version = (
            str(getattr(src, "file_version", "") or "").strip()
            or str(getattr(src, "registration_version", "") or "").strip()
            or "UNSPECIFIED"
        )
        checksum = _project_kb_doc_checksum(
            normalized_document_number=norm,
            version=version,
            source_updated_at=getattr(src, "updated_at", None) or getattr(src, "created_at", None),
            title=getattr(src, "file_name", "") or "",
            status=getattr(src, "completion_status", "") or "in_progress",
        )
        ProjectKnowledgeDocumentVersion.query.filter_by(
            organization_id=org_id,
            project_id=pid,
            normalized_document_number=norm,
            is_latest=True,
        ).update({"is_latest": False}, synchronize_session=False)
        record = ProjectKnowledgeDocumentVersion.query.filter_by(
            organization_id=org_id,
            project_id=pid,
            normalized_document_number=norm,
            version=version,
        ).first()
        if not record:
            record = ProjectKnowledgeDocumentVersion(
                id=generate_uuid(),
                organization_id=org_id,
                project_id=pid,
                document_number=str(getattr(src, "document_number", "") or "").strip() or norm,
                normalized_document_number=norm,
                version=version,
            )
            db.session.add(record)
        checksum_changed = str(record.source_checksum or "").strip() != checksum
        record.document_number = str(getattr(src, "document_number", "") or "").strip() or norm
        record.title = str(getattr(src, "file_name", "") or "").strip()
        record.status = (
            str(getattr(src, "completion_status", "") or "").strip()
            or "in_progress"
        )
        record.file_uri = str(getattr(src, "storage_path", "") or "").strip() or None
        record.source_checksum = checksum
        record.source_updated_at = getattr(src, "updated_at", None) or getattr(src, "created_at", None)
        record.published_at = getattr(src, "updated_at", None) or getattr(src, "created_at", None)
        record.is_latest = True
        if checksum_changed or not str(record.sync_state or "").strip():
            record.sync_state = "pending"
            record.sync_error = None
        record.metadata_json = {
            "uploadId": src.id,
            "projectCode": getattr(src, "project_code", None),
            "author": getattr(src, "author", None),
            "taskType": getattr(src, "task_type", None),
            "source": "upload_records",
            "ftpPath": str(getattr(src, "ftp_path", "") or "").strip(),
            "templateLinks": str(getattr(src, "template_links", "") or "").strip(),
            "originalFileName": str(getattr(src, "original_file_name", "") or "").strip(),
            "fileName": str(getattr(src, "file_name", "") or "").strip(),
        }
        touched.append(
            {
                "id": record.id,
                "organizationId": org_id,
                "projectId": pid,
                "documentNumber": record.document_number,
                "normalizedDocumentNumber": record.normalized_document_number,
                "version": record.version,
                "title": record.title,
                "status": record.status,
                "fileUri": record.file_uri or "",
                "checksum": checksum,
                "sourceUpdatedAt": (
                    record.source_updated_at.isoformat() if record.source_updated_at else ""
                ),
                "publishedAt": record.published_at.isoformat() if record.published_at else "",
                "isDeleted": False,
                "metadata": dict(record.metadata_json or {}),
            }
        )
    return touched


def enqueue_project_kb_sync_events(
    *,
    org_id: str,
    project_id: str,
    documents: list[dict[str, Any]],
    trigger: str = "manual",
    force_retry: bool = False,
) -> int:
    queued = 0
    for item in documents or []:
        norm = str(item.get("normalizedDocumentNumber") or "").strip()
        version = str(item.get("version") or "").strip()
        checksum = str(item.get("checksum") or "").strip()
        if not norm:
            continue
        event_key = f"{org_id}:{project_id}:{norm}:{version}"
        payload = {
            "organizationId": org_id,
            "projectId": str(project_id or "").strip(),
            "documentNumber": str(item.get("documentNumber") or "").strip(),
            "normalizedDocumentNumber": norm,
            "title": str(item.get("title") or "").strip(),
            "version": version,
            "status": str(item.get("status") or "controlled").strip() or "controlled",
            "fileUri": str(item.get("fileUri") or "").strip(),
            "checksum": checksum,
            "publishedAt": str(item.get("publishedAt") or "").strip(),
            "sourceUpdatedAt": str(item.get("sourceUpdatedAt") or "").strip(),
            "isLatest": True,
            "eventType": "DELETE" if bool(item.get("isDeleted")) else "UPSERT",
            "isDeleted": bool(item.get("isDeleted")),
            "metadata": {
                "trigger": trigger,
                "versionRecordId": str(item.get("id") or "").strip(),
                **(
                    dict(item.get("metadata") or {})
                    if isinstance(item.get("metadata"), dict)
                    else {}
                ),
            },
        }
        meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        file_name = str(meta.get("originalFileName") or meta.get("fileName") or "").strip()
        if file_name:
            payload["fileName"] = file_name
        row = ProjectKnowledgeSyncOutbox.query.filter_by(event_key=event_key).first()
        if not row:
            row = ProjectKnowledgeSyncOutbox(
                organization_id=org_id,
                project_id=str(project_id or "").strip(),
                event_key=event_key,
                event_type="DELETE" if bool(item.get("isDeleted")) else "UPSERT",
                payload_json=payload,
                status="pending",
            )
            db.session.add(row)
            queued += 1
            continue
        if force_retry or row.status in {"failed", "pending", "syncing"}:
            row.payload_json = payload
            row.status = "pending"
            row.last_error = None
            queued += 1
    return queued


def list_project_kb_latest_documents(*, org_id: str, project_id: str) -> list[dict[str, Any]]:
    pid = str(project_id or "").strip()
    latest_rows = (
        ProjectKnowledgeDocumentVersion.query.filter_by(
            organization_id=org_id,
            project_id=pid,
            is_latest=True,
        )
        .order_by(
            ProjectKnowledgeDocumentVersion.updated_at.desc(),
            ProjectKnowledgeDocumentVersion.created_at.desc(),
        )
        .all()
    )
    failed_rows = (
        ProjectKnowledgeDocumentVersion.query.filter_by(
            organization_id=org_id,
            project_id=pid,
            sync_state="failed",
        )
        .order_by(
            ProjectKnowledgeDocumentVersion.updated_at.desc(),
            ProjectKnowledgeDocumentVersion.created_at.desc(),
        )
        .all()
    )
    seen_ids: set[str] = set()
    merged: list[ProjectKnowledgeDocumentVersion] = []
    for row in list(failed_rows) + list(latest_rows):
        rid = str(getattr(row, "id", "") or "").strip()
        if not rid or rid in seen_ids:
            continue
        seen_ids.add(rid)
        merged.append(row)
    items = [_serialize_project_kb_doc(row) for row in merged]
    outbox_failed = (
        ProjectKnowledgeSyncOutbox.query.filter_by(
            organization_id=org_id,
            project_id=pid,
            status="failed",
        )
        .order_by(ProjectKnowledgeSyncOutbox.updated_at.desc())
        .all()
    )
    seen_keys = {
        (
            str(item.get("normalizedDocumentNumber") or "").strip(),
            str(item.get("version") or "").strip() or "UNSPECIFIED",
        )
        for item in items
    }
    outbox_by_key: dict[tuple[str, str], ProjectKnowledgeSyncOutbox] = {}
    for box in outbox_failed:
        payload = dict(box.payload_json or {}) if isinstance(box.payload_json, dict) else {}
        norm = str(payload.get("normalizedDocumentNumber") or "").strip()
        version = str(payload.get("version") or "").strip() or "UNSPECIFIED"
        if not norm:
            continue
        outbox_by_key[(norm, version)] = box
    for item in items:
        key = (
            str(item.get("normalizedDocumentNumber") or "").strip(),
            str(item.get("version") or "").strip() or "UNSPECIFIED",
        )
        box = outbox_by_key.get(key)
        if not box:
            continue
        item["syncState"] = "failed"
        item["syncError"] = str(box.last_error or item.get("syncError") or "").strip()
    for key, box in outbox_by_key.items():
        if key in seen_keys:
            continue
        norm, version = key
        payload = dict(box.payload_json or {}) if isinstance(box.payload_json, dict) else {}
        row = ProjectKnowledgeDocumentVersion.query.filter_by(
            organization_id=org_id,
            project_id=pid,
            normalized_document_number=norm,
            version=version,
        ).first()
        if row:
            item = _serialize_project_kb_doc(row)
            item["syncState"] = "failed"
            item["syncError"] = str(box.last_error or item.get("syncError") or "").strip()
            items.append(item)
            seen_keys.add(key)
            continue
        meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        items.append(
            {
                "id": str(meta.get("versionRecordId") or box.id or "").strip(),
                "projectId": pid,
                "documentNumber": str(payload.get("documentNumber") or norm).strip(),
                "normalizedDocumentNumber": norm,
                "title": str(payload.get("title") or payload.get("fileName") or "").strip(),
                "version": version,
                "status": str(payload.get("status") or "").strip() or "failed",
                "fileUri": str(payload.get("fileUri") or "").strip(),
                "checksum": str(payload.get("checksum") or "").strip(),
                "publishedAt": str(payload.get("publishedAt") or "").strip(),
                "sourceUpdatedAt": str(payload.get("sourceUpdatedAt") or "").strip(),
                "isLatest": False,
                "isDeleted": bool(payload.get("isDeleted")),
                "syncState": "failed",
                "syncError": str(box.last_error or "").strip(),
                "syncedAt": "",
                "updatedAt": box.updated_at.isoformat() if box.updated_at else "",
                "metadata": dict(meta),
            }
        )
        seen_keys.add(key)
    return items


def list_project_kb_document_history(
    *,
    org_id: str,
    project_id: str,
    normalized_document_number: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    norm = normalize_project_kb_document_number(normalized_document_number)
    if not norm:
        return []
    rows = (
        ProjectKnowledgeDocumentVersion.query.filter_by(
            organization_id=org_id,
            project_id=str(project_id or "").strip(),
            normalized_document_number=norm,
        )
        .order_by(ProjectKnowledgeDocumentVersion.updated_at.desc())
        .limit(max(1, min(int(limit or 50), 200)))
        .all()
    )
    return [
        {
            "id": row.id,
            "documentNumber": row.document_number,
            "normalizedDocumentNumber": row.normalized_document_number,
            "title": row.title,
            "version": row.version,
            "status": row.status,
            "checksum": row.source_checksum or "",
            "isLatest": bool(row.is_latest),
            "syncState": row.sync_state,
            "syncError": row.sync_error or "",
            "publishedAt": row.published_at.isoformat() if row.published_at else "",
            "sourceUpdatedAt": row.source_updated_at.isoformat() if row.source_updated_at else "",
            "syncedAt": row.synced_at.isoformat() if row.synced_at else "",
            "updatedAt": row.updated_at.isoformat() if row.updated_at else "",
            "metadata": dict(row.metadata_json or {}),
        }
        for row in rows
    ]


def get_project_kb_missing_document_numbers(
    *,
    org_id: str,
    project_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    extra_names: list[str] = []
    proj = Project.query.filter_by(id=str(project_id or "").strip()).first()
    if proj is not None:
        extra_names = _project_task_match_keys(proj)
    rows = (
        _project_kb_upload_query(
            org_id=org_id,
            project_id=project_id,
            extra_names=extra_names,
        )
        .order_by(UploadRecord.updated_at.desc(), UploadRecord.created_at.desc())
        .all()
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        has_source = bool(
            (getattr(row, "template_file_blob", None))
            or str(getattr(row, "ftp_path", "") or "").strip()
            or str(getattr(row, "storage_path", "") or "").strip()
            or str(getattr(row, "template_links", "") or "").strip()
        )
        if not has_source:
            continue
        if str(getattr(row, "document_number", "") or "").strip():
            continue
        out.append(
            {
                "uploadId": str(getattr(row, "id", "") or "").strip(),
                "fileName": str(getattr(row, "file_name", "") or "").strip(),
                "author": str(getattr(row, "author", "") or "").strip(),
                "taskType": str(getattr(row, "task_type", "") or "").strip(),
                "updatedAt": (
                    getattr(row, "updated_at", None).isoformat()
                    if getattr(row, "updated_at", None)
                    else ""
                ),
            }
        )
        if len(out) >= max(1, min(int(limit or 20), 100)):
            break
    return out


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def list_project_kb_overview_stats(
    *,
    org_id: str,
    projects: list[Any] | None = None,
    project_ids: list[str] | None = None,
    project_names: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """按页面1 任务全量分区统计，各状态之和等于任务总数。只读，不触发 refresh。"""
    proj_rows = list(projects or [])
    ids = [str(getattr(p, "id", "") or "").strip() for p in proj_rows if str(getattr(p, "id", "") or "").strip()]
    if not ids:
        ids = [str(x or "").strip() for x in (project_ids or []) if str(x or "").strip()]
    if not ids:
        return {}
    label_to_id: dict[str, str] = {}
    for p in proj_rows:
        pid = str(getattr(p, "id", "") or "").strip()
        if not pid:
            continue
        for key in _project_task_match_keys(p):
            label_to_id.setdefault(key, pid)
    for pid, name in (project_names or {}).items():
        text = str(name or "").strip()
        pid_s = str(pid or "").strip()
        if text and pid_s:
            label_to_id.setdefault(text, pid_s)
    out: dict[str, dict[str, Any]] = {pid: _empty_project_kb_stats() for pid in ids}
    last_updated: dict[str, Any] = {}
    kb_map = _kb_sync_map_for_projects(org_id=org_id, project_ids=ids)
    id_set = set(ids)

    clauses = [UploadRecord.project_id.in_(ids)]
    if label_to_id:
        clauses.append(UploadRecord.project_name.in_(list(label_to_id.keys())))
    upload_rows = (
        db.session.query(
            UploadRecord.id,
            UploadRecord.project_id,
            UploadRecord.project_name,
            UploadRecord.document_number,
            UploadRecord.ftp_path,
            UploadRecord.storage_path,
            UploadRecord.template_links,
            UploadRecord.updated_at,
        )
        .filter(or_(*clauses))
        .all()
    )
    maybe_blob_ids = []
    classified: list[tuple[str, Any]] = []
    for row in upload_rows:
        pid = str(getattr(row, "project_id", "") or "").strip()
        if pid not in id_set:
            pid = label_to_id.get(str(getattr(row, "project_name", "") or "").strip(), "")
        if not pid or pid not in out:
            continue
        has_path_source = _upload_has_kb_source(
            has_blob=False,
            ftp_path=str(getattr(row, "ftp_path", "") or ""),
            storage_path=str(getattr(row, "storage_path", "") or ""),
            template_links=str(getattr(row, "template_links", "") or ""),
        )
        uid = str(getattr(row, "id", "") or "").strip()
        classified.append((pid, row, uid, has_path_source))
        if uid and not has_path_source:
            maybe_blob_ids.append(uid)
    blob_ids = _upload_ids_with_blob(maybe_blob_ids)
    for pid, row, uid, has_path_source in classified:
        has_source = has_path_source or (uid in blob_ids)
        doc_no = str(getattr(row, "document_number", "") or "").strip()
        norm = normalize_project_kb_document_number(doc_no)
        kb = kb_map.get((pid, norm)) if norm else None
        bucket = _classify_project_kb_task(
            has_source=has_source,
            document_number=doc_no,
            sync_state=str((kb or {}).get("syncState") or ""),
        )
        item = out[pid]
        item["taskCount"] += 1
        if bucket == "synced":
            item["syncedCount"] += 1
        elif bucket == "failed":
            item["failedCount"] += 1
        elif bucket == "pending":
            item["pendingCount"] += 1
        elif bucket == "ready":
            item["readyCount"] += 1
        elif bucket == "missing_number":
            item["missingDocumentNumberCount"] += 1
        else:
            item["noFileCount"] += 1
        updated_at = getattr(row, "updated_at", None)
        if updated_at and (pid not in last_updated or updated_at > last_updated[pid]):
            last_updated[pid] = updated_at
    for pid, item in out.items():
        item["latestCount"] = (
            _as_int(item["syncedCount"])
            + _as_int(item["failedCount"])
            + _as_int(item["pendingCount"])
        )
        ts = last_updated.get(pid)
        item["lastUpdatedAt"] = ts.isoformat() if ts else ""
    return out


def list_project_kb_task_records(*, org_id: str, project_id: str) -> list[dict[str, Any]]:
    """返回该项目全部任务记录及知识库状态，供查看明细。"""
    pid = str(project_id or "").strip()
    if not pid:
        return []
    proj = Project.query.filter_by(id=pid).first()
    extra_names = _project_task_match_keys(proj) if proj is not None else []
    kb_map = _kb_sync_map_for_projects(org_id=org_id, project_ids=[pid])
    clauses = [UploadRecord.project_id == pid]
    if extra_names:
        clauses.append(UploadRecord.project_name.in_(extra_names))
    rows = (
        db.session.query(
            UploadRecord.id,
            UploadRecord.file_name,
            UploadRecord.document_number,
            UploadRecord.file_version,
            UploadRecord.registration_version,
            UploadRecord.completion_status,
            UploadRecord.task_status,
            UploadRecord.author,
            UploadRecord.task_type,
            UploadRecord.ftp_path,
            UploadRecord.storage_path,
            UploadRecord.template_links,
            UploadRecord.created_at,
            UploadRecord.updated_at,
        )
        .filter(or_(*clauses))
        .order_by(UploadRecord.sort_order.asc(), UploadRecord.created_at.asc())
        .all()
    )
    blob_ids = _upload_ids_with_blob(
        [
            str(getattr(row, "id", "") or "").strip()
            for row in rows
            if not _upload_has_kb_source(
                has_blob=False,
                ftp_path=str(getattr(row, "ftp_path", "") or ""),
                storage_path=str(getattr(row, "storage_path", "") or ""),
                template_links=str(getattr(row, "template_links", "") or ""),
            )
        ]
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        doc_no = str(getattr(row, "document_number", "") or "").strip()
        norm = normalize_project_kb_document_number(doc_no)
        uid = str(getattr(row, "id", "") or "").strip()
        has_source = _upload_has_kb_source(
            has_blob=uid in blob_ids,
            ftp_path=str(getattr(row, "ftp_path", "") or ""),
            storage_path=str(getattr(row, "storage_path", "") or ""),
            template_links=str(getattr(row, "template_links", "") or ""),
        )
        kb = kb_map.get((pid, norm)) if norm else None
        bucket = _classify_project_kb_task(
            has_source=has_source,
            document_number=doc_no,
            sync_state=str((kb or {}).get("syncState") or ""),
        )
        version = (
            str(getattr(row, "file_version", "") or "").strip()
            or str(getattr(row, "registration_version", "") or "").strip()
            or str((kb or {}).get("version") or "").strip()
            or ""
        )
        status = (
            str(getattr(row, "completion_status", "") or "").strip()
            or str(getattr(row, "task_status", "") or "").strip()
            or "-"
        )
        updated_at = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
        items.append(
            {
                "id": str((kb or {}).get("id") or getattr(row, "id", "") or "").strip(),
                "uploadId": str(getattr(row, "id", "") or "").strip(),
                "projectId": pid,
                "documentNumber": doc_no,
                "normalizedDocumentNumber": norm,
                "title": str(getattr(row, "file_name", "") or "").strip(),
                "version": version or "-",
                "status": status,
                "fileUri": str(getattr(row, "storage_path", "") or "").strip(),
                "checksum": "",
                "publishedAt": "",
                "sourceUpdatedAt": updated_at.isoformat() if updated_at else "",
                "isLatest": bool((kb or {}).get("isLatest")),
                "isDeleted": False,
                "syncState": bucket,
                "syncError": str((kb or {}).get("syncError") or ""),
                "syncedAt": "",
                "updatedAt": updated_at.isoformat() if updated_at else "",
                "bucket": bucket,
                "hasSource": has_source,
                "metadata": {
                    "uploadId": str(getattr(row, "id", "") or "").strip(),
                    "author": str(getattr(row, "author", "") or "").strip(),
                    "taskType": str(getattr(row, "task_type", "") or "").strip(),
                    "fileName": str(getattr(row, "file_name", "") or "").strip(),
                },
            }
        )
    return items
