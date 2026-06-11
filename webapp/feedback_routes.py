# -*- coding: utf-8 -*-
"""用户问题反馈：页面0–3 提交，页面4 超管处理。"""
from __future__ import annotations

import os
import re
from typing import Any, Optional

from flask import Blueprint, Response, jsonify, request, session

from . import db
from .authz import is_page13_super_admin, super_admin_required
from .models import User, UserFeedback, now_local

feedback_bp = Blueprint("feedback", __name__)

FEEDBACK_FAB_EXCLUDED_ENDPOINTS = frozenset(
    {
        "pages.login_page",
        "admin.admin_page",
    }
)

FEEDBACK_FEATURE_MODULES: tuple[tuple[str, str], ...] = (
    ("page0", "页面0 · 公司总览"),
    ("page1_upload", "页面1 · 任务上传/登记"),
    ("page1_draft", "页面1 · 初稿生成"),
    ("page1_audit", "页面1 · 文档审核"),
    ("page1_audit_modify", "页面1 · 审核后修改"),
    ("page1_translate", "页面1 · 翻译"),
    ("page1_exam_student", "考试训练中心 · 学生端"),
    ("page1_exam_teacher", "考试训练中心 · 老师端"),
    ("page1_exam_analytics", "考试训练中心 · 统计端"),
    ("page1_sign_print", "页面1 · 签批/打印"),
    ("page2", "页面2 · 生成"),
    ("page3", "页面3 · 统计"),
    ("other", "其他"),
)

FEEDBACK_PRIORITIES: tuple[tuple[str, str], ...] = (
    ("low", "低"),
    ("normal", "普通"),
    ("high", "高"),
    ("urgent", "紧急"),
)

FEEDBACK_STATUSES: tuple[tuple[str, str], ...] = (
    ("pending", "待处理"),
    ("processing", "处理中"),
    ("resolved", "已解决"),
    ("closed", "已关闭"),
)

_FEATURE_KEYS = {k for k, _ in FEEDBACK_FEATURE_MODULES}
_PRIORITY_KEYS = {k for k, _ in FEEDBACK_PRIORITIES}
_STATUS_KEYS = {k for k, _ in FEEDBACK_STATUSES}

_LEGACY_FEATURE_LABELS = {
    "page1_exam": "考试训练中心（旧）",
}

_MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
_ALLOWED_SCREENSHOT_MIMES = frozenset(
    {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/bmp"}
)


def feedback_fab_enabled() -> bool:
    from flask import request as req

    if not session.get("user_id"):
        return False
    ep = req.endpoint or ""
    if ep in FEEDBACK_FAB_EXCLUDED_ENDPOINTS:
        return False
    return bool(ep)


def _label_for(key: str, pairs: tuple[tuple[str, str], ...]) -> str:
    for k, label in pairs:
        if k == key:
            return label
    return _LEGACY_FEATURE_LABELS.get(key, key)


def _safe_screenshot_filename(name: str) -> str:
    base = os.path.basename(name or "screenshot.png")
    base = base.strip() or "screenshot.png"
    base = re.sub(r'[\x00-\x1f\\/:*?"<>|]+', "_", base)
    base = re.sub(r"\s+", " ", base).strip()
    if not re.search(r"\.(png|jpe?g|gif|webp|bmp)$", base, re.I):
        base = f"{base}.png"
    return (base or "screenshot.png")[:200]


def _serialize(row: UserFeedback, *, include_admin_fields: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.id,
        "featureModule": row.feature_module,
        "featureModuleLabel": _label_for(row.feature_module, FEEDBACK_FEATURE_MODULES),
        "description": row.description,
        "priority": row.priority,
        "priorityLabel": _label_for(row.priority, FEEDBACK_PRIORITIES),
        "status": row.status,
        "statusLabel": _label_for(row.status, FEEDBACK_STATUSES),
        "hasScreenshot": bool(row.screenshot_ftp_path),
        "screenshotOriginalName": row.screenshot_original_name,
        "screenshotUploadError": row.screenshot_upload_error,
        "resolution": row.resolution,
        "resolvedAt": row.resolved_at.isoformat(sep=" ", timespec="seconds") if row.resolved_at else None,
        "createdAt": row.created_at.isoformat(sep=" ", timespec="seconds") if row.created_at else None,
        "updatedAt": row.updated_at.isoformat(sep=" ", timespec="seconds") if row.updated_at else None,
    }
    if include_admin_fields:
        out.update(
            {
                "userId": row.user_id,
                "submitterUsername": row.submitter_username,
                "submitterDisplayName": row.submitter_display_name,
                "resolvedByLabel": row.resolved_by_label,
            }
        )
    return out


def _login_user_required():
    uid = session.get("user_id")
    if not uid:
        return None, (jsonify({"message": "请先登录后再提交反馈", "needsLogin": True}), 401)
    user = User.query.get(uid)
    if not user:
        return None, (jsonify({"message": "账号不存在或已失效", "needsLogin": True}), 401)
    return user, None


@feedback_bp.get("/api/feedback/meta")
def feedback_meta():
    return jsonify(
        {
            "featureModules": [{"key": k, "label": v} for k, v in FEEDBACK_FEATURE_MODULES],
            "priorities": [{"key": k, "label": v} for k, v in FEEDBACK_PRIORITIES],
            "statuses": [{"key": k, "label": v} for k, v in FEEDBACK_STATUSES],
        }
    )


@feedback_bp.post("/api/feedback")
def create_feedback():
    user, err = _login_user_required()
    if err:
        return err

    feature = (request.form.get("feature_module") or "").strip()
    description = (request.form.get("description") or "").strip()
    priority = (request.form.get("priority") or "normal").strip()

    if feature not in _FEATURE_KEYS:
        return jsonify({"message": "请选择有效的功能模块"}), 400
    if not description:
        return jsonify({"message": "请填写问题描述"}), 400
    if len(description) > 8000:
        return jsonify({"message": "问题描述过长（最多 8000 字）"}), 400
    if priority not in _PRIORITY_KEYS:
        return jsonify({"message": "请选择有效的优先级"}), 400

    row = UserFeedback(
        user_id=user.id,
        submitter_username=user.username,
        submitter_display_name=user.display_name or user.username,
        feature_module=feature,
        description=description,
        priority=priority,
        status="pending",
    )
    db.session.add(row)
    db.session.flush()

    shot = request.files.get("screenshot")
    if shot and shot.filename:
        data = shot.read()
        if len(data) > _MAX_SCREENSHOT_BYTES:
            db.session.rollback()
            return jsonify({"message": "截图过大（最大 5MB）"}), 400
        mime = (shot.mimetype or "").split(";")[0].strip().lower()
        if mime and mime not in _ALLOWED_SCREENSHOT_MIMES:
            db.session.rollback()
            return jsonify({"message": "截图格式不支持，请上传 PNG/JPEG/GIF/WebP"}), 400
        safe = _safe_screenshot_filename(shot.filename)
        row.screenshot_original_name = safe
        from .ftp_store import try_upload_bytes

        rel = f"user_feedback/{row.id}/{safe}"
        pth, ftp_err = try_upload_bytes(data, rel)
        if pth:
            row.screenshot_ftp_path = pth
            row.screenshot_upload_error = None
        elif ftp_err:
            row.screenshot_upload_error = (ftp_err or "")[:512]
        # FTP 未配置时不阻断反馈提交

    db.session.commit()
    return jsonify({"success": True, "item": _serialize(row)})


@feedback_bp.get("/api/feedback/mine")
def list_my_feedback():
    user, err = _login_user_required()
    if err:
        return err
    rows = (
        UserFeedback.query.filter_by(user_id=user.id)
        .order_by(UserFeedback.created_at.desc())
        .limit(200)
        .all()
    )
    return jsonify({"items": [_serialize(r) for r in rows]})


@feedback_bp.get("/api/feedback")
@super_admin_required
def list_all_feedback():
    status = (request.args.get("status") or "").strip()
    q = UserFeedback.query
    if status and status in _STATUS_KEYS:
        q = q.filter(UserFeedback.status == status)
    rows = q.order_by(UserFeedback.created_at.desc()).limit(500).all()
    return jsonify({"items": [_serialize(r, include_admin_fields=True) for r in rows]})


@feedback_bp.patch("/api/feedback/<feedback_id>")
@super_admin_required
def update_feedback(feedback_id: str):
    row = UserFeedback.query.get(feedback_id)
    if not row:
        return jsonify({"message": "反馈不存在"}), 404

    body = request.get_json(silent=True) or {}
    status = body.get("status")
    resolution = body.get("resolution")

    if status is not None:
        status = str(status).strip()
        if status not in _STATUS_KEYS:
            return jsonify({"message": "无效的状态"}), 400
        row.status = status
        if status in ("resolved", "closed"):
            row.resolved_at = now_local()
            row.resolved_by_label = "超级管理员"
        elif status in ("pending", "processing"):
            row.resolved_at = None
            row.resolved_by_label = None

    if resolution is not None:
        text = str(resolution).strip()
        if len(text) > 8000:
            return jsonify({"message": "处理方案过长"}), 400
        row.resolution = text or None

    db.session.commit()
    return jsonify({"success": True, "item": _serialize(row, include_admin_fields=True)})


@feedback_bp.delete("/api/feedback/<feedback_id>")
@super_admin_required
def delete_feedback(feedback_id: str):
    row = UserFeedback.query.get(feedback_id)
    if not row:
        return jsonify({"message": "反馈不存在"}), 404

    if row.screenshot_ftp_path:
        from .ftp_store import delete_path, ftp_upload_configured

        if ftp_upload_configured():
            try:
                delete_path(row.screenshot_ftp_path)
            except Exception:
                pass

    db.session.delete(row)
    db.session.commit()
    return jsonify({"success": True})


def _feedback_visible_to_request(row: UserFeedback) -> bool:
    if is_page13_super_admin():
        return True
    uid = session.get("user_id")
    return bool(uid and row.user_id == uid)


@feedback_bp.get("/api/feedback/<feedback_id>/screenshot")
def download_feedback_screenshot(feedback_id: str):
    row = UserFeedback.query.get(feedback_id)
    if not row or not row.screenshot_ftp_path:
        return jsonify({"message": "截图不存在"}), 404
    if not _feedback_visible_to_request(row):
        return jsonify({"message": "无权查看该截图"}), 403

    from .ftp_store import download_bytes, ftp_upload_configured

    if not ftp_upload_configured():
        return jsonify({"message": "FTP 未配置，无法读取截图"}), 503
    try:
        data = download_bytes(row.screenshot_ftp_path)
    except Exception as exc:
        return jsonify({"message": f"读取截图失败：{exc}"}), 502

    fname = row.screenshot_original_name or "screenshot.png"
    mime = "image/png"
    low = fname.lower()
    if low.endswith((".jpg", ".jpeg")):
        mime = "image/jpeg"
    elif low.endswith(".gif"):
        mime = "image/gif"
    elif low.endswith(".webp"):
        mime = "image/webp"
    elif low.endswith(".bmp"):
        mime = "image/bmp"

    return Response(
        data,
        mimetype=mime,
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


def register_feedback_blueprint(app):
    app.register_blueprint(feedback_bp)
