"""集成 API 路由：供 AISystem 网关调用，实现跨系统任务流转。
独立 Blueprint，不影响原有路由。
"""

from __future__ import annotations

import os
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file

from . import db
from .models import UploadRecord, now_local

bp = Blueprint("integration", __name__, url_prefix="/api/integration")


def _check_integration_secret(f):
    """集成 API 鉴权：通过共享密钥验证调用方身份"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        secret = current_app.config.get("INTEGRATION_SECRET") or os.getenv("INTEGRATION_SECRET", "")
        if secret:
            provided = request.headers.get("X-Integration-Secret", "")
            if provided != secret:
                return jsonify({"message": "集成密钥无效"}), 403
        return f(*args, **kwargs)
    return wrapper


@bp.get("/health")
def health():
    return jsonify({"status": "ok", "service": "aiword"})


@bp.get("/tasks")
@_check_integration_secret
def list_tasks():
    """获取任务列表，支持按项目和状态过滤"""
    project = request.args.get("projectName", "").strip()
    status = request.args.get("status", "").strip()

    query = UploadRecord.query
    if project:
        query = query.filter(UploadRecord.project_name == project)
    if status == "completed":
        query = query.filter(UploadRecord.completion_status.isnot(None))
    elif status == "pending":
        query = query.filter(UploadRecord.completion_status.is_(None))

    records = query.order_by(
        UploadRecord.sort_order.asc(), UploadRecord.created_at.asc()
    ).all()

    return jsonify({
        "records": [_task_to_dict(r, idx) for idx, r in enumerate(records)]
    })


@bp.get("/tasks/<task_id>")
@_check_integration_secret
def get_task(task_id: str):
    """获取单个任务详情"""
    record = UploadRecord.query.get(task_id)
    if not record:
        return jsonify({"message": "任务不存在"}), 404
    return jsonify(_task_to_dict(record))


@bp.get("/tasks/<task_id>/document")
@_check_integration_secret
def download_document(task_id: str):
    """下载任务关联的文档文件"""
    record = UploadRecord.query.get(task_id)
    if not record:
        return jsonify({"message": "任务不存在"}), 404

    if record.storage_path and Path(record.storage_path).exists():
        return send_file(
            record.storage_path,
            as_attachment=True,
            download_name=record.original_file_name or "document.docx",
        )

    links = record.get_template_links_list()
    if links:
        first_link = links[0]
        if first_link.lower().endswith(('.docx', '.doc')):
            try:
                from .doc_service import download_template_from_url
                uploads_dir = Path(current_app.config["UPLOAD_FOLDER"])
                temp_path = uploads_dir / f"integration_{task_id}.docx"
                download_template_from_url(first_link, str(temp_path))
                return send_file(
                    str(temp_path),
                    as_attachment=True,
                    download_name=f"{record.file_name or 'document'}.docx",
                )
            except Exception as e:
                return jsonify({"message": f"下载文档失败: {e}"}), 500

    return jsonify({"message": "该任务没有可下载的文档"}), 404


@bp.post("/update-audit")
@_check_integration_secret
def update_audit():
    """接收审核结果并更新任务的审核状态，将问题摘要写入下发任务备注"""
    data = request.get_json(force=True) or {}
    task_id = (data.get("taskId") or "").strip()
    audit_status = (data.get("auditStatus") or "").strip()

    if not task_id:
        return jsonify({"message": "缺少 taskId"}), 400

    record = UploadRecord.query.get(task_id)
    if not record:
        return jsonify({"message": "任务不存在"}), 404

    if audit_status:
        record.audit_status = audit_status
        if audit_status == "审核不通过待修改":
            record.audit_reject_count = (getattr(record, "audit_reject_count", 0) or 0) + 1

    review_summary = (data.get("reviewSummary") or "").strip()
    if review_summary:
        existing_notes = record.notes or ""
        separator = "\n---\n" if existing_notes else ""
        record.notes = f"{existing_notes}{separator}[AI审核] {review_summary}"

    db.session.commit()
    return jsonify({
        "success": True,
        "message": "审核状态已更新",
        "taskId": task_id,
        "auditStatus": record.audit_status,
    })


@bp.post("/create-task")
@_check_integration_secret
def create_task():
    """从外部系统创建任务（如审核结果生成修改任务）"""
    data = request.get_json(force=True) or {}
    project_name = (data.get("projectName") or "").strip()
    file_name = (data.get("fileName") or "").strip()
    author = (data.get("author") or "").strip()

    if not project_name or not file_name or not author:
        return jsonify({"success": False, "message": "projectName / fileName / author 为必填"}), 400

    task_type = (data.get("taskType") or "").strip() or None
    existing = UploadRecord.query.filter_by(
        project_name=project_name,
        file_name=file_name,
        task_type=task_type,
        author=author,
    ).first()

    if existing:
        return jsonify({
            "success": False,
            "message": "同名任务已存在",
            "existingId": existing.id,
        }), 409

    template_links = (data.get("templateLinks") or "").strip() or None

    record = UploadRecord(
        project_name=project_name,
        file_name=file_name,
        task_type=task_type,
        author=author,
        assignee_name=(data.get("assigneeName") or author).strip(),
        notes=(data.get("notes") or "").strip() or None,
        template_links=template_links,
    )

    due_date_str = (data.get("dueDate") or "").strip()
    if due_date_str:
        from datetime import datetime
        try:
            record.due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    db.session.add(record)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "任务已创建",
        "taskId": record.id,
        "projectName": project_name,
        "fileName": file_name,
    })


@bp.get("/project-names")
@_check_integration_secret
def project_names():
    """获取项目名称列表"""
    names = (
        db.session.query(UploadRecord.project_name)
        .filter(UploadRecord.project_name.isnot(None), UploadRecord.project_name != "")
        .distinct()
        .order_by(UploadRecord.project_name)
        .all()
    )
    return jsonify({"projectNames": [n[0] for n in names if (n[0] or "").strip()]})


def _task_to_dict(r: UploadRecord, idx: int = 0) -> dict:
    return {
        "id": r.id,
        "seq": idx + 1,
        "projectName": r.project_name,
        "fileName": r.file_name,
        "taskType": r.task_type,
        "author": r.author,
        "hasFile": bool(r.storage_path),
        "hasLinks": bool(r.template_links),
        "templateLinks": r.template_links,
        "linksCount": len(r.get_template_links_list()),
        "assigneeName": r.assignee_name,
        "dueDate": r.due_date.strftime("%Y-%m-%d") if r.due_date else None,
        "taskStatus": r.task_status,
        "completionStatus": r.completion_status,
        "auditStatus": r.audit_status,
        "quickCompleted": r.quick_completed,
        "businessSide": r.business_side,
        "product": r.product,
        "country": r.country,
        "projectCode": getattr(r, "project_code", None),
        "fileVersion": getattr(r, "file_version", None),
        "reviewer": getattr(r, "reviewer", None),
        "approver": getattr(r, "approver", None),
        "belongingModule": getattr(r, "belonging_module", None),
        "notes": r.notes,
        "projectNotes": getattr(r, "project_notes", None),
        "executionNotes": getattr(r, "execution_notes", None),
        "createdAt": r.created_at.isoformat() if r.created_at else None,
    }
