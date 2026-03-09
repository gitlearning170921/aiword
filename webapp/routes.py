# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import secrets
import hashlib
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Optional

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from . import db
from .doc_service import extract_placeholders, generate_document, download_template_from_url
from .models import (
    GenerateRecord, GenerationSummary, UploadRecord, User,
    TaskTypeConfig, CompletionStatusConfig, AuditStatusConfig, NotifyTemplateConfig, AppConfig,
    ModuleCascadeReminder, now_local,
)
from . import dingtalk_service

bp = Blueprint("pages", __name__)


# ---------- 辅助函数 ----------

def _save_file(file_storage, target_dir: Path) -> tuple[str, str]:
    filename = secure_filename(file_storage.filename)
    generated_name = f"{now_local().strftime('%Y%m%d%H%M%S%f')}_{filename}"
    file_path = target_dir / generated_name
    file_storage.save(file_path)
    return generated_name, str(file_path)


def _normalize_doc_link(line: str) -> str:
    """截断 https 之前的内容，返回从 http(s) 开始的有效可打开地址。"""
    line = (line or "").strip()
    if not line:
        return line
    lower = line.lower()
    for prefix in ("https://", "http://"):
        idx = lower.find(prefix)
        if idx != -1:
            return line[idx:]
    return line


def _normalize_template_links(value: str) -> str:
    """多行文档地址，每行截断 https 之前的信息后合并。"""
    if not value or not value.strip():
        return value.strip() or ""
    lines = [_normalize_doc_link(ln) for ln in value.split("\n") if ln.strip()]
    return "\n".join(ln for ln in lines if ln)


def _is_valid_doc_link(value: str) -> bool:
    """校验文档链接是否合理：每行经归一化后需以 http:// 或 https:// 开头。"""
    if not value or not value.strip():
        return True
    for line in value.strip().split("\n"):
        ln = (line or "").strip()
        if not ln:
            continue
        normalized = _normalize_doc_link(ln)
        lower = normalized.lower()
        if not (lower.startswith("http://") or lower.startswith("https://")):
            return False
    return True


def _prepare_summary(upload: UploadRecord) -> GenerationSummary:
    if upload.summary:
        return upload.summary
    summary = GenerationSummary(
        upload=upload,
        project_name=upload.project_name,
        file_name=upload.file_name,
        author=upload.author,
    )
    db.session.add(summary)
    return summary


def _get_template_path_for_upload(upload: UploadRecord, link_index: int = 0) -> str:
    """返回上传记录对应的模板本地路径：文件则用 storage_path，链接则下载到 uploads/。"""
    if upload.storage_path and Path(upload.storage_path).exists():
        return upload.storage_path
    links = upload.get_template_links_list()
    if links and link_index < len(links):
        uploads_dir = Path(current_app.config["UPLOAD_FOLDER"])
        save_path = uploads_dir / f"link_{upload.id}_{link_index}.docx"
        if not save_path.exists():
            download_template_from_url(links[link_index], str(save_path))
        return str(save_path)
    raise ValueError("上传记录未关联有效模板（文件或链接）")


def _build_option_tree(records: list[UploadRecord]) -> list[dict[str, Any]]:
    projects: dict[str, dict[str, Any]] = {}
    for record in records:
        proj = projects.setdefault(
            record.project_name,
            {"projectName": record.project_name, "files": {}},
        )
        file_entry = proj["files"].setdefault(
            record.file_name,
            {"fileName": record.file_name, "authors": []},
        )
        file_entry["authors"].append(
            {
                "author": record.author,
                "uploadId": record.id,
                "hasLinks": bool(record.template_links),
                "taskStatus": record.task_status,
                "quickCompleted": record.quick_completed,
            }
        )
    formatted = []
    for project in projects.values():
        files = list(project["files"].values())
        project["files"] = files
        formatted.append(project)
    return formatted


def _summary_payload():
    """
    统计逻辑：
    - completion_status 有值 => 已完成
    - completion_status 为空 => 未完成
    - 项目+人员统计融合各完成状态数量
    """
    uploads = UploadRecord.query.order_by(
        UploadRecord.sort_order.asc(), UploadRecord.created_at.asc()
    ).all()
    total_files = len(uploads)
    
    def _rate(done: int, total: int) -> float:
        return round(done / total, 4) if total else 0.0
    
    completed_files = sum(1 for u in uploads if u.completion_status)
    
    by_project: dict[str, dict[str, Any]] = {}
    by_author: dict[str, dict[str, Any]] = {}
    by_project_author: dict[str, dict[str, Any]] = {}

    for u in uploads:
        proj_key = u.project_name
        auth_key = u.author
        proj_auth_key = f"{u.project_name}__{u.author}"
        is_completed = bool(u.completion_status)
        status = u.completion_status or "未完成"

        for bucket, key in (
            (by_project, proj_key),
            (by_author, auth_key),
            (by_project_author, proj_auth_key),
        ):
            stats = bucket.setdefault(key, {
                "total": 0, "completed": 0, "pending": 0,
                "byStatus": {}, "pendingAuthors": set(),
                "auditRejectCount": 0,
            })
            stats["total"] += 1
            if is_completed:
                stats["completed"] += 1
            else:
                stats["pending"] += 1
                stats["pendingAuthors"].add(u.author)
            stats["byStatus"][status] = stats["byStatus"].get(status, 0) + 1
            stats["auditRejectCount"] = stats.get("auditRejectCount", 0) + (getattr(u, "audit_reject_count", None) or 0)

    def _format_with_status(bucket: dict[str, dict[str, Any]], label_join: str = "", include_project_author_keys: bool = False):
        formatted = []
        for key, stats in bucket.items():
            label = key
            if label_join and "__" in key:
                parts = key.split("__")
                label = label_join.join(parts)
            by_status_list = [
                {"status": s, "count": c}
                for s, c in sorted(stats["byStatus"].items(), key=lambda x: (x[0] != "未完成", -x[1]))
            ]
            item = {
                "label": label,
                "completed": stats["completed"],
                "pending": stats["pending"],
                "total": stats["total"],
                "rate": _rate(stats["completed"], stats["total"]),
                "byStatus": by_status_list,
                "pendingAuthors": list(stats["pendingAuthors"]),
                "auditRejectCount": stats.get("auditRejectCount", 0),
            }
            if include_project_author_keys and "__" in key:
                p, a = key.split("__", 1)
                item["projectName"] = p
                item["author"] = a
            formatted.append(item)
        return formatted

    detail_rows = [
        {
            "seq": idx + 1,
            "uploadId": u.id,
            "projectName": u.project_name,
            "fileName": u.file_name,
            "taskType": u.task_type,
            "author": u.author,
            "completionStatus": u.completion_status,
            "isCompleted": bool(u.completion_status),
            "dueDate": u.due_date.strftime("%Y-%m-%d") if u.due_date else None,
            "sortOrder": u.sort_order,
            "businessSide": u.business_side,
            "product": u.product,
            "country": u.country,
            "projectCode": getattr(u, "project_code", None),
            "fileVersion": getattr(u, "file_version", None),
            "documentDisplayDate": (lambda d: d.strftime("%Y-%m-%d") if d else None)(getattr(u, "document_display_date", None)),
            "reviewer": getattr(u, "reviewer", None),
            "approver": getattr(u, "approver", None),
            "belongingModule": getattr(u, "belonging_module", None),
            "docLink": (u.get_template_links_list() or [None])[0] or None,
            "createdAt": u.created_at.isoformat() if u.created_at else None,
            "notes": u.notes,
            "projectNotes": getattr(u, "project_notes", None),
            "executionNotes": u.execution_notes,
        }
        for idx, u in enumerate(uploads)
    ]

    return {
        "overall": {
            "completed": completed_files,
            "pending": total_files - completed_files,
            "total": total_files,
            "rate": _rate(completed_files, total_files),
        },
        "byProject": _format_with_status(by_project),
        "byAuthor": _format_with_status(by_author),
        "byProjectAuthor": _format_with_status(by_project_author, label_join=" / ", include_project_author_keys=True),
        "detail": detail_rows,
    }


# ---------- 登录验证装饰器 ----------

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"message": "请先登录", "needsLogin": True}), 401
            return redirect(url_for("pages.login_page"))
        return f(*args, **kwargs)
    return decorated_function


def _page13_or_login_required(f):
    """登录 或 已通过页面1/3 访问密码 任一即可（供页面1 未登录时也能加载配置、页面2 仅登录即可）。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not _page13_password_configured():
            return f(*args, **kwargs)
        if session.get("user_id"):
            return f(*args, **kwargs)
        if session.get("page13_authenticated"):
            return f(*args, **kwargs)
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.path.startswith("/api/"):
            return jsonify({"message": "需要输入访问密码", "needsPage13Auth": True}), 401
        next_url = request.path or "/upload"
        return render_template("page13_gate.html", next_url=next_url, gate_page=True)
    return decorated_function


def _page13_password_configured() -> bool:
    """是否已配置页面1/3 访问密码（从 config.json 读取）"""
    p = current_app.config.get("PAGE13_ACCESS_PASSWORD")
    return bool(p and str(p).strip())


def page13_access_required(f):
    """页面1、页面3 及其相关 API 的访问密码校验。密码不在网络中传输，使用 nonce+hash 校验。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not _page13_password_configured():
            return f(*args, **kwargs)
        if session.get("page13_authenticated"):
            return f(*args, **kwargs)
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.path.startswith("/api/"):
            return jsonify({"message": "需要输入访问密码", "needsPage13Auth": True}), 401
        next_url = request.path or "/upload"
        return render_template("page13_gate.html", next_url=next_url, gate_page=True)
    return decorated_function


# ---------- 页面路由 ----------

@bp.route("/favicon.ico")
def favicon():
    """避免浏览器请求 favicon 时 404，返回空响应。"""
    return "", 204


@bp.route("/")
def index():
    return redirect(url_for("pages.upload_page"))


@bp.route("/upload")
@page13_access_required
def upload_page():
    return render_template("upload.html")


@bp.route("/login")
def login_page():
    return render_template("login.html")


@bp.route("/generate")
@login_required
def generate_page():
    return render_template("generate.html")


@bp.route("/dashboard")
@page13_access_required
def dashboard_page():
    return render_template("dashboard.html")


# ---------- 认证 API ----------

@bp.post("/api/login")
def api_login():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"message": "用户名和密码不能为空"}), 400
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({"message": "用户名或密码错误"}), 401
    session["user_id"] = user.id
    session["username"] = user.username
    session["display_name"] = user.display_name or user.username
    return jsonify({
        "message": "登录成功",
        "user": {
            "id": user.id,
            "username": user.username,
            "displayName": user.display_name,
        },
    })


@bp.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"message": "已退出登录"})


@bp.get("/api/me")
def api_me():
    if not session.get("user_id"):
        return jsonify({"loggedIn": False})
    return jsonify({
        "loggedIn": True,
        "user": {
            "id": session.get("user_id"),
            "username": session.get("username"),
            "displayName": session.get("display_name"),
        },
    })


@bp.get("/api/page13-auth-state")
def api_page13_auth_state():
    """获取页面1/3 是否需密码及本次验证用的 nonce（不校验身份，任何人可调）。"""
    required = _page13_password_configured()
    authenticated = bool(session.get("page13_authenticated"))
    if not required:
        return jsonify({"required": False, "authenticated": True})
    if authenticated:
        return jsonify({"required": True, "authenticated": True})
    nonce = secrets.token_hex(16)
    session["page13_nonce"] = nonce
    return jsonify({"required": True, "authenticated": False, "nonce": nonce})


@bp.post("/api/page13-auth")
def api_page13_auth():
    """提交 hash(nonce+password)，校验通过后设置 session，密码不明文传输。"""
    if not _page13_password_configured():
        return jsonify({"success": True, "message": "未配置访问密码"})
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    client_hash = (data.get("hash") or "").strip()
    if not client_hash:
        return jsonify({"message": "缺少校验参数"}), 400
    nonce = session.get("page13_nonce")
    if not nonce:
        return jsonify({"message": "请先获取验证码（刷新页面后重试）"}), 400
    raw = current_app.config.get("PAGE13_ACCESS_PASSWORD")
    password = (str(raw).replace("\ufeff", "").strip() if raw else "")
    expected = hashlib.sha256((nonce + password).encode("utf-8")).hexdigest()
    session.pop("page13_nonce", None)
    if not secrets.compare_digest(expected, client_hash):
        return jsonify({"message": "访问密码错误"}), 401
    session["page13_authenticated"] = True
    return jsonify({"success": True, "message": "验证成功"})


# ---------- 用户管理 API（页面1管理账号） ----------

@bp.get("/api/users")
@page13_access_required
def api_users_list():
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify({
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "displayName": u.display_name,
                "mobile": getattr(u, "mobile", None) or None,
                "createdAt": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ]
    })


@bp.post("/api/users")
@page13_access_required
def api_users_create():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    display_name = (data.get("displayName") or "").strip() or None
    mobile = (data.get("mobile") or "").strip() or None
    if not username or not password:
        return jsonify({"message": "用户名和密码不能为空"}), 400
    existing = User.query.filter_by(username=username).first()
    if existing:
        return jsonify({"message": "用户名已存在"}), 409
    user = User(username=username, display_name=display_name, mobile=mobile)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({
        "message": "用户创建成功",
        "user": {
            "id": user.id,
            "username": user.username,
            "displayName": user.display_name,
            "mobile": user.mobile,
        },
    })


@bp.patch("/api/users/<user_id>")
@page13_access_required
def api_users_update(user_id: str):
    """更新用户显示名称、手机号（钉钉 @ 用）"""
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "用户不存在"}), 404
    data = request.get_json(force=True) or {}
    if "displayName" in data:
        user.display_name = (data["displayName"] or "").strip() or None
    if "mobile" in data:
        user.mobile = (data["mobile"] or "").strip() or None
    db.session.add(user)
    db.session.commit()
    return jsonify({"message": "已更新", "user": {"id": user.id, "username": user.username, "displayName": user.display_name, "mobile": user.mobile}})


@bp.delete("/api/users/<user_id>")
@page13_access_required
def api_users_delete(user_id: str):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "用户不存在"}), 404
    db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "用户已删除"})


# ---------- 配置项 API ----------

@bp.get("/api/configs/task-types")
@_page13_or_login_required
def api_task_types():
    """获取任务类型配置列表"""
    items = TaskTypeConfig.query.filter_by(is_active=True).order_by(TaskTypeConfig.sort_order).all()
    return jsonify({
        "taskTypes": [{"id": t.id, "name": t.name} for t in items]
    })


@bp.post("/api/configs/task-types")
@page13_access_required
def api_task_types_create():
    """新增任务类型"""
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"message": "名称不能为空"}), 400
    existing = TaskTypeConfig.query.filter_by(name=name).first()
    if existing:
        return jsonify({"message": "该类型已存在"}), 409
    max_order = db.session.query(db.func.max(TaskTypeConfig.sort_order)).scalar() or 0
    item = TaskTypeConfig(name=name, sort_order=max_order + 1)
    db.session.add(item)
    db.session.commit()
    return jsonify({"message": "创建成功", "id": item.id, "name": item.name})


@bp.delete("/api/configs/task-types/<item_id>")
@page13_access_required
def api_task_types_delete(item_id: str):
    """删除任务类型"""
    item = TaskTypeConfig.query.get(item_id)
    if not item:
        return jsonify({"message": "不存在"}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "已删除"})


@bp.get("/api/configs/completion-statuses")
@_page13_or_login_required
def api_completion_statuses():
    """获取完成状态配置列表"""
    items = CompletionStatusConfig.query.filter_by(is_active=True).order_by(CompletionStatusConfig.sort_order).all()
    return jsonify({
        "completionStatuses": [{"id": s.id, "name": s.name} for s in items]
    })


@bp.post("/api/configs/completion-statuses")
@page13_access_required
def api_completion_statuses_create():
    """新增完成状态"""
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"message": "名称不能为空"}), 400
    existing = CompletionStatusConfig.query.filter_by(name=name).first()
    if existing:
        return jsonify({"message": "该状态已存在"}), 409
    max_order = db.session.query(db.func.max(CompletionStatusConfig.sort_order)).scalar() or 0
    item = CompletionStatusConfig(name=name, sort_order=max_order + 1)
    db.session.add(item)
    db.session.commit()
    return jsonify({"message": "创建成功", "id": item.id, "name": item.name})


@bp.delete("/api/configs/completion-statuses/<item_id>")
@page13_access_required
def api_completion_statuses_delete(item_id: str):
    """删除完成状态"""
    item = CompletionStatusConfig.query.get(item_id)
    if not item:
        return jsonify({"message": "不存在"}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "已删除"})


@bp.get("/api/configs/audit-statuses")
@_page13_or_login_required
def api_audit_statuses():
    """获取审核状态配置列表（页面1使用）"""
    items = AuditStatusConfig.query.filter_by(is_active=True).order_by(AuditStatusConfig.sort_order).all()
    return jsonify({
        "auditStatuses": [{"id": s.id, "name": s.name} for s in items]
    })


@bp.post("/api/configs/audit-statuses")
@page13_access_required
def api_audit_statuses_create():
    """新增审核状态"""
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"message": "名称不能为空"}), 400
    existing = AuditStatusConfig.query.filter_by(name=name).first()
    if existing:
        return jsonify({"message": "该状态已存在"}), 409
    max_order = db.session.query(db.func.max(AuditStatusConfig.sort_order)).scalar() or 0
    item = AuditStatusConfig(name=name, sort_order=max_order + 1)
    db.session.add(item)
    db.session.commit()
    return jsonify({"message": "创建成功", "id": item.id, "name": item.name})


@bp.delete("/api/configs/audit-statuses/<item_id>")
@page13_access_required
def api_audit_statuses_delete(item_id: str):
    """删除审核状态"""
    item = AuditStatusConfig.query.get(item_id)
    if not item:
        return jsonify({"message": "不存在"}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "已删除"})


# ---------- 上传与任务管理 API ----------

@bp.post("/api/upload")
@page13_access_required
def api_upload():
    project_name = request.form.get("projectName", "").strip()
    project_code = request.form.get("projectCode", "").strip() or None
    file_name = request.form.get("fileName", "").strip()
    task_type = request.form.get("taskType", "").strip() or None
    author = request.form.get("author", "").strip()
    notes = request.form.get("notes", "").strip() or None
    project_notes = request.form.get("projectNotes", "").strip() or None
    replace = request.form.get("replace") == "true"
    file = request.files.get("file")
    template_links = request.form.get("templateLinks", "").strip() or None
    if template_links:
        template_links = _normalize_template_links(template_links) or None
    assignee_name = request.form.get("assigneeName", "").strip() or None
    due_date_str = request.form.get("dueDate", "").strip() or None
    business_side = request.form.get("businessSide", "").strip() or None
    product = request.form.get("product", "").strip() or None
    country = request.form.get("country", "").strip() or None
    file_version = request.form.get("fileVersion", "").strip() or None
    document_display_date_str = request.form.get("documentDisplayDate", "").strip() or None
    reviewer = request.form.get("reviewer", "").strip() or None
    approver = request.form.get("approver", "").strip() or None
    belonging_module = request.form.get("belongingModule", "").strip() or None

    if not project_name or not file_name or not author:
        return (
            jsonify({"message": "项目名称、文件名称、编写人员为必填项。"}),
            400,
        )
    # 链接和文件均可为空保存，后续可在页面2补充链接

    existing = UploadRecord.query.filter_by(
        project_name=project_name, file_name=file_name, task_type=task_type, author=author
    ).first()

    if existing and not replace:
        return (
            jsonify(
                {
                    "message": f"存在同名项目+文件+类型+编写人({task_type or '无'}/{author})，是否需要替换原有内容？",
                    "needsConfirmation": True,
                }
            ),
            409,
        )

    uploads_dir = Path(current_app.config["UPLOAD_FOLDER"])
    stored_file_name = None
    storage_path = None
    original_file_name = None
    placeholders = []

    if file and file.filename:
        stored_file_name, storage_path = _save_file(file, uploads_dir)
        original_file_name = file.filename
        try:
            placeholders = extract_placeholders(storage_path)
        except Exception as exc:
            Path(storage_path).unlink(missing_ok=True)
            return jsonify({"message": f"解析模板失败：{exc}"}), 400
    elif template_links:
        links = [line.strip() for line in template_links.split("\n") if line.strip()]
        if links:
            first_link = links[0].lower()
            is_direct_docx = first_link.endswith('.docx') or first_link.endswith('.doc')
            if is_direct_docx:
                try:
                    temp_path = uploads_dir / f"temp_{now_local().strftime('%Y%m%d%H%M%S%f')}.docx"
                    download_template_from_url(links[0], str(temp_path))
                    placeholders = extract_placeholders(str(temp_path))
                    temp_path.unlink(missing_ok=True)
                except Exception as exc:
                    temp_path.unlink(missing_ok=True) if 'temp_path' in dir() else None
                    return jsonify({"message": f"下载或解析模板链接失败：{exc}"}), 400

    due_date = None
    if due_date_str:
        try:
            due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"message": "截止日期格式应为 YYYY-MM-DD"}), 400
    document_display_date = None
    if document_display_date_str:
        try:
            document_display_date = datetime.strptime(document_display_date_str, "%Y-%m-%d").date()
        except ValueError:
            document_display_date = None

    if existing and replace:
        if existing.storage_path:
            previous_path = Path(existing.storage_path)
            if previous_path.exists():
                previous_path.unlink()

        existing.stored_file_name = stored_file_name
        existing.storage_path = storage_path
        existing.original_file_name = original_file_name
        existing.template_links = template_links
        existing.author = author
        existing.task_type = task_type
        existing.notes = notes
        existing.project_notes = project_notes
        existing.project_name = project_name
        existing.file_name = file_name
        existing.placeholders = placeholders
        existing.assignee_name = assignee_name
        existing.due_date = due_date
        existing.task_status = "pending"
        existing.completion_status = None
        existing.quick_completed = False
        existing.business_side = business_side
        existing.product = product
        existing.country = country
        existing.project_code = project_code
        existing.file_version = file_version
        existing.document_display_date = document_display_date
        existing.reviewer = reviewer
        existing.approver = approver
        existing.project_notes = project_notes
        existing.belonging_module = belonging_module
        summary = _prepare_summary(existing)
        summary.project_name = project_name
        summary.file_name = file_name
        summary.author = author
        summary.has_generated = False
        summary.total_generate_clicks = 0
        summary.last_generated_at = None
        db.session.add(existing)
        db.session.commit()

        _send_task_notification(existing, due_date_str)

        return jsonify(
            {
                "message": "已替换现有记录，状态已重置为待办。",
                "record": {
                    "id": existing.id,
                    "projectName": existing.project_name,
                    "fileName": existing.file_name,
                    "taskType": existing.task_type,
                    "author": existing.author,
                    "placeholders": placeholders,
                    "assigneeName": existing.assignee_name,
                    "dueDate": due_date_str,
                    "businessSide": existing.business_side,
                    "product": existing.product,
                    "country": existing.country,
                },
            }
        )

    upload = UploadRecord(
        project_name=project_name,
        project_code=project_code,
        file_name=file_name,
        task_type=task_type,
        author=author,
        stored_file_name=stored_file_name,
        storage_path=storage_path,
        original_file_name=original_file_name,
        template_links=template_links,
        notes=notes,
        project_notes=project_notes,
        placeholders=placeholders,
        assignee_name=assignee_name,
        due_date=due_date,
        business_side=business_side,
        product=product,
        country=country,
        file_version=file_version,
        document_display_date=document_display_date,
        reviewer=reviewer,
        approver=approver,
        belonging_module=belonging_module,
    )
    db.session.add(upload)
    summary = _prepare_summary(upload)
    db.session.add(summary)
    db.session.commit()

    _send_task_notification(upload, due_date_str)

    return jsonify(
        {
            "message": "上传信息已保存。",
            "record": {
                "id": upload.id,
                "projectName": upload.project_name,
                "fileName": upload.file_name,
                "taskType": upload.task_type,
                "author": upload.author,
                "placeholders": placeholders,
                "assigneeName": upload.assignee_name,
                "dueDate": due_date_str,
                "businessSide": upload.business_side,
                "product": upload.product,
                "country": upload.country,
            },
        }
    )


def _send_task_notification(upload: UploadRecord, due_date_str: str):
    """如果设置了负责人，发送钉钉通知"""
    if not upload.assignee_name:
        return
    webhook = current_app.config.get("DINGTALK_WEBHOOK") or os.environ.get("DINGTALK_WEBHOOK")
    secret = current_app.config.get("DINGTALK_SECRET") or os.environ.get("DINGTALK_SECRET")
    template_source = "已上传文件" if upload.storage_path else f"链接({len(upload.get_template_links_list())}个)"
    sent = dingtalk_service.notify_task_assigned(
        upload.assignee_name,
        f"{upload.project_name} - {upload.file_name}",
        due_date_str or "未设置",
        template_source,
        webhook=webhook,
        secret=secret,
    )
    if sent:
        upload.dingtalk_notified_at = now_local()
        db.session.add(upload)
        db.session.commit()


@bp.get("/api/template-options")
@bp.get("/api/upload-options")
@page13_access_required
def api_template_options():
    records = UploadRecord.query.order_by(
        UploadRecord.project_name, UploadRecord.file_name, UploadRecord.author
    ).all()
    return jsonify({"projects": _build_option_tree(records)})


@bp.get("/api/templates/<upload_id>")
@bp.get("/api/uploads/<upload_id>")
@page13_access_required
def api_template_detail(upload_id: str):
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到模板记录"}), 404
    placeholders = upload.placeholders or []
    if not placeholders and (upload.storage_path or upload.template_links):
        try:
            template_path = _get_template_path_for_upload(upload)
            placeholders = extract_placeholders(template_path)
            upload.placeholders = placeholders
            db.session.add(upload)
            db.session.commit()
        except Exception as exc:
            return jsonify({"message": f"解析模板失败：{exc}"}), 400
    return jsonify(
        {
            "id": upload.id,
            "projectName": upload.project_name,
            "fileName": upload.file_name,
            "author": upload.author,
            "placeholders": placeholders,
            "hasLinks": bool(upload.template_links),
            "linksCount": len(upload.get_template_links_list()),
            "taskStatus": upload.task_status,
            "quickCompleted": upload.quick_completed,
            "assigneeName": upload.assignee_name,
            "dueDate": upload.due_date.strftime("%Y-%m-%d") if upload.due_date else None,
        }
    )


@bp.get("/api/uploads")
@page13_access_required
def api_uploads_list():
    """获取所有上传记录列表"""
    records = UploadRecord.query.order_by(
        UploadRecord.sort_order.asc(), UploadRecord.created_at.asc()
    ).all()
    return jsonify({
        "records": [
            {
                "seq": idx + 1,
                "id": r.id,
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
                "sortOrder": r.sort_order,
                "businessSide": r.business_side,
                "product": r.product,
                "country": r.country,
                "projectCode": getattr(r, "project_code", None),
                "fileVersion": getattr(r, "file_version", None),
                "documentDisplayDate": (lambda d: d.strftime("%Y-%m-%d") if d else None)(getattr(r, "document_display_date", None)),
                "reviewer": getattr(r, "reviewer", None),
                "approver": getattr(r, "approver", None),
                "belongingModule": getattr(r, "belonging_module", None),
                "createdAt": r.created_at.isoformat() if r.created_at else None,
                "notes": r.notes,
                "projectNotes": getattr(r, "project_notes", None),
                "executionNotes": getattr(r, "execution_notes", None),
            }
            for idx, r in enumerate(records)
        ]
    })


@bp.delete("/api/uploads/<upload_id>")
@page13_access_required
def api_upload_delete(upload_id: str):
    """删除任务记录"""
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到该记录"}), 404
    
    if upload.storage_path:
        try:
            Path(upload.storage_path).unlink(missing_ok=True)
        except Exception:
            pass
    
    db.session.delete(upload)
    db.session.commit()
    return jsonify({"message": "已删除"})


@bp.patch("/api/uploads/<upload_id>")
@page13_access_required
def api_upload_update(upload_id: str):
    """更新任务记录（页面1编辑），仅更新可编辑字段，不涉及文件替换。"""
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到该记录"}), 404
    
    data = request.get_json(force=True) or {}
    
    project_name = (data.get("projectName") or "").strip() or None
    file_name = (data.get("fileName") or "").strip() or None
    task_type = (data.get("taskType") or "").strip() or None
    author = (data.get("author") or "").strip() or None
    due_date_str = (data.get("dueDate") or "").strip() or None
    business_side = (data.get("businessSide") or "").strip() or None
    product = (data.get("product") or "").strip() or None
    country = (data.get("country") or "").strip() or None
    assignee_name = (data.get("assigneeName") or "").strip() or None
    completion_status = (data.get("completionStatus") or "").strip() or None
    audit_status = (data.get("auditStatus") or "").strip() or None
    project_code = (data.get("projectCode") or "").strip() or None
    file_version = (data.get("fileVersion") or "").strip() or None
    document_display_date_str = (data.get("documentDisplayDate") or "").strip() or None
    reviewer = (data.get("reviewer") or "").strip() or None
    approver = (data.get("approver") or "").strip() or None
    project_notes = (data.get("projectNotes") or "").strip() or None
    has_project_notes = "projectNotes" in data
    belonging_module = (data.get("belongingModule") or "").strip() or None
    has_belonging_module = "belongingModule" in data

    if project_name is not None:
        upload.project_name = project_name
    if file_name is not None:
        upload.file_name = file_name
    if task_type is not None:
        upload.task_type = task_type if task_type else None
    if author is not None:
        if not author:
            return jsonify({"message": "编写人员不能为空"}), 400
        upload.author = author
    if business_side is not None:
        upload.business_side = business_side or None
    if product is not None:
        upload.product = product or None
    if country is not None:
        upload.country = country or None
    if "templateLinks" in data:
        val = data.get("templateLinks")
        s = (val if isinstance(val, str) else "").strip()
        upload.template_links = _normalize_template_links(s) or None
    if assignee_name is not None:
        upload.assignee_name = assignee_name or None
    if "notes" in data:
        val = data.get("notes")
        s = (val if isinstance(val, str) else "").strip()
        upload.notes = s or None
    if has_project_notes:
        upload.project_notes = project_notes
    if project_code is not None:
        upload.project_code = project_code
    if file_version is not None:
        upload.file_version = file_version
    if document_display_date_str is not None:
        if not document_display_date_str:
            upload.document_display_date = None
        else:
            try:
                upload.document_display_date = datetime.strptime(document_display_date_str, "%Y-%m-%d").date()
            except ValueError:
                pass
    if reviewer is not None:
        upload.reviewer = reviewer
    if approver is not None:
        upload.approver = approver
    if has_belonging_module:
        upload.belonging_module = belonging_module
    if audit_status is not None:
        upload.audit_status = audit_status or None
        if audit_status == "审核不通过待修改":
            upload.audit_reject_count = (getattr(upload, "audit_reject_count", 0) or 0) + 1
    if completion_status is not None:
        upload.completion_status = completion_status or None
        if upload.completion_status:
            upload.task_status = "completed"
        else:
            upload.task_status = "pending"
    
    if due_date_str is not None:
        if not due_date_str:
            upload.due_date = None
        else:
            try:
                upload.due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"message": "截止日期格式应为 YYYY-MM-DD"}), 400
    
    if upload.project_name and upload.file_name and upload.author:
        other = UploadRecord.query.filter(
            UploadRecord.project_name == upload.project_name,
            UploadRecord.file_name == upload.file_name,
            UploadRecord.author == upload.author,
            UploadRecord.id != upload.id,
        ).first()
        if other and (upload.task_type or None) == (other.task_type or None):
            return jsonify({"message": "项目名称+文件名称+任务类型+编写人与已有记录重复"}), 409
    
    db.session.add(upload)
    if upload.summary:
        upload.summary.project_name = upload.project_name
        upload.summary.file_name = upload.file_name
        upload.summary.author = upload.author
        db.session.add(upload.summary)
    db.session.commit()
    if upload.completion_status and (upload.belonging_module or "").strip() in ("产品", "开发"):
        _maybe_enqueue_module_cascade(upload.project_name or "", (upload.belonging_module or "").strip())

    return jsonify({
        "message": "已更新",
        "record": {
            "id": upload.id,
            "projectName": upload.project_name,
            "fileName": upload.file_name,
            "taskType": upload.task_type,
            "author": upload.author,
            "dueDate": upload.due_date.strftime("%Y-%m-%d") if upload.due_date else None,
            "businessSide": upload.business_side,
            "product": upload.product,
            "country": upload.country,
            "assigneeName": upload.assignee_name,
        },
    })


@bp.get("/api/my-tasks")
@login_required
def api_my_tasks():
    """获取当前登录用户的任务列表（页面2使用）"""
    username = session.get("username")
    display_name = session.get("display_name")
    
    records = UploadRecord.query.filter(
        db.or_(
            UploadRecord.assignee_name == username,
            UploadRecord.assignee_name == display_name,
            UploadRecord.author == username,
            UploadRecord.author == display_name,
        )
    ).order_by(UploadRecord.sort_order.asc(), UploadRecord.created_at.asc()).all()
    
    return jsonify({
        "records": [
            {
                "seq": idx + 1,
                "id": r.id,
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
                "quickCompleted": r.quick_completed,
                "placeholders": r.placeholders or [],
                "sortOrder": r.sort_order,
                "businessSide": r.business_side,
                "product": r.product,
                "country": r.country,
                "projectCode": getattr(r, "project_code", None),
                "fileVersion": getattr(r, "file_version", None),
                "documentDisplayDate": (lambda d: d.strftime("%Y-%m-%d") if d else None)(getattr(r, "document_display_date", None)),
                "reviewer": getattr(r, "reviewer", None),
                "approver": getattr(r, "approver", None),
                "belongingModule": getattr(r, "belonging_module", None),
                "createdAt": r.created_at.isoformat() if r.created_at else None,
                "notes": r.notes,
                "projectNotes": getattr(r, "project_notes", None),
                "executionNotes": getattr(r, "execution_notes", None),
            }
            for idx, r in enumerate(records)
        ]
    })


@bp.patch("/api/uploads/<upload_id>/execution-notes")
@login_required
def api_update_execution_notes(upload_id: str):
    """更新执行任务备注（仅页面2可编辑）。"""
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到该记录"}), 404
    data = request.get_json(force=True) or {}
    val = data.get("executionNotes")
    s = (val if isinstance(val, str) else "").strip() or None
    upload.execution_notes = s
    db.session.add(upload)
    db.session.commit()
    return jsonify({"message": "已更新", "executionNotes": upload.execution_notes})


@bp.patch("/api/uploads/<upload_id>/completion-status")
@login_required
def api_update_completion_status(upload_id: str):
    """更新任务的完成状态（页面2使用）。可仅更新文档链接；标记完成时需已填写文档链接。"""
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到该记录"}), 404
    
    data = request.get_json(force=True) or {}
    completion_status = data.get("completionStatus")
    template_links = (data.get("templateLinks") or "").strip() or None
    
    if template_links is not None:
        if template_links and not _is_valid_doc_link(template_links):
            return jsonify({"message": "请填写有效的文档链接（需以 http:// 或 https:// 开头）"}), 400
        upload.template_links = _normalize_template_links(template_links) or None
    
    if completion_status is not None:
        if completion_status:
            if not upload.has_template():
                return jsonify({"message": "请先填写文档链接后再标记完成状态"}), 400
            upload.completion_status = completion_status
            upload.task_status = "completed"
        else:
            upload.completion_status = None
            upload.task_status = "pending"
    
    db.session.add(upload)
    db.session.commit()
    if upload.completion_status and (upload.belonging_module or "").strip() in ("产品", "开发"):
        _maybe_enqueue_module_cascade(upload.project_name or "", (upload.belonging_module or "").strip())

    return jsonify({
        "message": "已更新完成状态",
        "uploadId": upload_id,
        "completionStatus": upload.completion_status,
        "taskStatus": upload.task_status,
    })


# ---------- 文档生成 API ----------

@bp.post("/api/generate")
@login_required
def api_generate():
    data = request.get_json(force=True) or {}
    upload_id = data.get("uploadId")
    triggered_by = data.get("triggeredBy") or session.get("username", "web")
    placeholder_values = data.get("values") or {}
    output_name = data.get("outputName")
    replace = str(data.get("replace")).lower() == "true"
    link_index = int(data.get("linkIndex", 0))

    if not upload_id:
        return jsonify({"message": "请提供 uploadId。"}), 400

    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到对应的模板记录"}), 404

    try:
        template_path = _get_template_path_for_upload(upload, link_index)
    except Exception as e:
        return jsonify({"message": str(e)}), 400

    required_placeholders = upload.placeholders or []
    if not required_placeholders:
        try:
            required_placeholders = extract_placeholders(template_path)
            upload.placeholders = required_placeholders
            db.session.add(upload)
            db.session.commit()
        except Exception as exc:
            return jsonify({"message": f"解析模板失败：{exc}"}), 400

    missing = [
        key for key in required_placeholders if not placeholder_values.get(key, "").strip()
    ]
    if missing:
        return jsonify({"message": f"以下占位符尚未填写：{', '.join(missing)}"}), 400

    existing_record = GenerateRecord.query.filter_by(upload_id=upload_id).first()
    if existing_record and not replace:
        return (
            jsonify(
                {
                    "message": "该项目与文件的生成记录已存在，是否替换原内容？",
                    "needsConfirmation": True,
                }
            ),
            409,
        )

    outputs_dir = Path(current_app.config["OUTPUT_FOLDER"])
    try:
        output_path = generate_document(
            template_path=template_path,
            output_dir=str(outputs_dir),
            data=placeholder_values,
            output_name=output_name,
        )
    except Exception as exc:
        return jsonify({"message": f"生成文档失败：{exc}"}), 500

    if existing_record and replace:
        previous_path = existing_record.output_path
        if previous_path:
            Path(previous_path).unlink(missing_ok=True)
        record = existing_record
        record.placeholder_payload = placeholder_values
        record.status = "completed"
        record.success = True
        record.completed_at = now_local()
        record.output_file_name = Path(output_path).name
        record.output_path = output_path
        record.triggered_by = triggered_by
    else:
        record = GenerateRecord(
            upload=upload,
            triggered_by=triggered_by,
            status="completed",
            success=True,
            completed_at=now_local(),
            placeholder_payload=placeholder_values,
            output_file_name=Path(output_path).name,
            output_path=output_path,
        )
    db.session.add(record)

    summary = _prepare_summary(upload)
    summary.total_generate_clicks += 1
    summary.has_generated = True
    summary.last_generated_at = now_local()
    db.session.add(summary)

    upload.task_status = "completed"
    db.session.add(upload)

    db.session.commit()

    return jsonify(
        {
            "message": "文档生成成功。",
            "recordId": record.id,
            "uploadId": upload_id,
            "outputPath": output_path,
        }
    )


# ---------- 快速完成 API ----------

@bp.post("/api/quick-complete")
@login_required
def api_quick_complete():
    """
    快速完成文档：无需填写占位符，直接在链接中填写完文档后标记完成。
    适用于页面1填写了文档链接的情况。
    """
    data = request.get_json(force=True) or {}
    upload_id = data.get("uploadId")

    if not upload_id:
        return jsonify({"message": "请提供 uploadId。"}), 400

    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到对应的记录"}), 404

    if not upload.template_links:
        return jsonify({"message": "该记录没有文档链接，无法使用快速完成功能。"}), 400

    upload.quick_completed = True
    upload.task_status = "completed"
    db.session.add(upload)

    summary = _prepare_summary(upload)
    summary.has_generated = True
    summary.total_generate_clicks += 1
    summary.last_generated_at = now_local()
    db.session.add(summary)

    db.session.commit()

    return jsonify({
        "message": "已快速完成。",
        "uploadId": upload_id,
        "taskStatus": upload.task_status,
    })


# ---------- 任务状态更新 API ----------

@bp.patch("/api/uploads/<upload_id>/status")
@page13_access_required
def api_upload_status_update(upload_id: str):
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到该记录。"}), 404
    data = request.get_json(force=True) or {}
    if data.get("status") == "completed":
        upload.task_status = "completed"
        db.session.add(upload)
        db.session.commit()
    return jsonify({
        "message": "已更新。",
        "uploadId": upload_id,
        "taskStatus": upload.task_status,
    })


@bp.get("/api/summary")
@page13_access_required
def api_summary():
    return jsonify(_summary_payload())


# ---------- 通知文案配置 API ----------

@bp.get("/api/configs/notify-templates")
@page13_access_required
def api_get_notify_templates():
    templates = NotifyTemplateConfig.query.order_by(NotifyTemplateConfig.template_key).all()
    return jsonify([
        {
            "id": t.id,
            "key": t.template_key,
            "name": t.template_name,
            "content": t.template_content,
            "isActive": t.is_active,
        }
        for t in templates
    ])


@bp.put("/api/configs/notify-templates/<template_id>")
@page13_access_required
def api_update_notify_template(template_id: str):
    template = NotifyTemplateConfig.query.get(template_id)
    if not template:
        return jsonify({"message": "未找到该通知模板"}), 404
    
    data = request.get_json(force=True) or {}
    if "content" in data:
        template.template_content = data["content"]
    if "name" in data:
        template.template_name = data["name"]
    if "isActive" in data:
        template.is_active = data["isActive"]
    
    db.session.add(template)
    db.session.commit()
    
    return jsonify({
        "message": "更新成功",
        "id": template.id,
    })


# ---------- 排序更新 API ----------

@bp.post("/api/uploads/reorder")
@login_required
def api_reorder_uploads():
    """更新任务排序"""
    data = request.get_json(force=True) or {}
    orders = data.get("orders", [])
    
    if not orders:
        return jsonify({"message": "排序数据为空"}), 400
    
    for item in orders:
        upload_id = item.get("id")
        sort_order = item.get("sortOrder", 0)
        if upload_id:
            upload = UploadRecord.query.get(upload_id)
            if upload:
                upload.sort_order = sort_order
                db.session.add(upload)
    
    db.session.commit()
    return jsonify({"message": "排序更新成功"})


# ---------- 钉钉通知推送 API ----------

def _get_notify_template(key: str) -> str:
    """获取通知文案模板"""
    template = NotifyTemplateConfig.query.filter_by(template_key=key, is_active=True).first()
    if template:
        return template.template_content
    return ""


def _resolve_mobiles_for_authors(author_names: list) -> list:
    """根据编写人员姓名解析钉钉 @ 用的手机号（从 User 表）"""
    if not author_names:
        return []
    from .models import User
    mobiles = []
    for name in author_names:
        if not name:
            continue
        user = User.query.filter(
            db.or_(
                User.username == name,
                User.display_name == name,
            )
        ).first()
        if user and getattr(user, "mobile", None) and str(user.mobile).strip():
            mobiles.append(str(user.mobile).strip())
    return mobiles


def _get_base_url() -> str:
    """获取对外访问的基础 URL（域名），用于催办等通知中的链接。优先使用配置的 BASE_URL，否则用当前请求的 host。"""
    base = (current_app.config.get("BASE_URL") or os.environ.get("BASE_URL") or "").strip()
    if base:
        return base.rstrip("/")
    if request and request.host_url:
        return request.host_url.rstrip("/")
    return ""


def _maybe_enqueue_module_cascade(project_name: str, trigger_module: str) -> None:
    """
    当某项目下所属模块为 trigger_module（产品或开发）的最后一份文档被标记为完成后，入队一条延迟发送的模块级联催办。
    产品→开发；开发→测试。同一项目同一触发模块只保留一条待执行，新入队会覆盖旧待执行。
    """
    if not project_name or (trigger_module or "").strip() not in ("产品", "开发"):
        return
    pname = (project_name or "").strip()
    tmod = (trigger_module or "").strip()
    target_module = "开发" if tmod == "产品" else "测试"
    all_in_module = UploadRecord.query.filter(
        UploadRecord.project_name == pname,
        UploadRecord.belonging_module == tmod,
    ).all()
    if not all_in_module:
        return
    if any(getattr(u, "completion_status", None) is None for u in all_in_module):
        return
    row = AppConfig.query.filter_by(config_key="MODULE_CASCADE_DELAY_MINUTES").first()
    delay_minutes = 5
    if row and row.config_value:
        try:
            delay_minutes = max(1, min(1440, int(str(row.config_value).strip())))
        except ValueError:
            pass
    from datetime import timedelta
    run_at = now_local() + timedelta(minutes=delay_minutes)
    ModuleCascadeReminder.query.filter(
        ModuleCascadeReminder.project_name == pname,
        ModuleCascadeReminder.trigger_module == tmod,
        ModuleCascadeReminder.status == "pending",
    ).delete()
    db.session.add(ModuleCascadeReminder(
        project_name=pname,
        trigger_module=tmod,
        target_module=target_module,
        run_at=run_at,
        status="pending",
    ))
    db.session.commit()


def _send_notify_to_individuals(
    title: str,
    message_markdown: str,
    at_mobiles: Optional[list] = None,
    at_names: Optional[list] = None,
):
    """群消息发送成功后，再向被@人员的个人工作通知发一份（需配置 DINGTALK_APP_KEY/APP_SECRET/AGENT_ID）。"""
    mobiles = list(at_mobiles) if at_mobiles else []
    if not mobiles and at_names:
        mobiles = _resolve_mobiles_for_authors(list(at_names))
    if not mobiles:
        return
    dingtalk_service.send_work_notification_to_mobiles(title, message_markdown, mobiles)


@bp.post("/api/notify/by-project")
@page13_access_required
def api_notify_by_project():
    """按项目推送钉钉通知"""
    data = request.get_json(force=True) or {}
    project_name = data.get("projectName")
    
    if not project_name:
        return jsonify({"message": "请提供项目名称"}), 400
    
    webhook = (current_app.config.get("DINGTALK_WEBHOOK") or os.environ.get("DINGTALK_WEBHOOK") or "").strip()
    secret = (current_app.config.get("DINGTALK_SECRET") or os.environ.get("DINGTALK_SECRET") or "").strip() or None
    
    if not webhook:
        return jsonify({"message": "未配置钉钉 Webhook，请在环境变量中设置 DINGTALK_WEBHOOK"}), 400
    
    pending_uploads = UploadRecord.query.filter(
        UploadRecord.project_name == project_name,
        UploadRecord.completion_status.is_(None)
    ).all()
    
    if not pending_uploads:
        return jsonify({"message": f"项目 {project_name} 没有未完成的任务"})
    
    assignees = list(set(u.author for u in pending_uploads if u.author))
    
    def _group_key(u):
        return (u.project_name or "", u.business_side or "", u.product or "")
    
    groups = {}
    for u in pending_uploads:
        k = _group_key(u)
        groups.setdefault(k, []).append(u)
    
    def _task_block_md(key, uploads_in_group):
        proj, bs, pr = key
        lines = []
        proj_code = getattr(uploads_in_group[0], "project_code", None) if uploads_in_group else None
        header = f"**项目：{proj or '-'}  项目编号：{proj_code or '-'}  影响业务方：{bs or '-'}  产品：{pr or '-'}**"
        lines.append(header)
        for u in uploads_in_group:
            links = u.get_template_links_list() or []
            link = links[0] if links else None
            due = u.due_date.strftime("%Y-%m-%d") if u.due_date else "-"
            due_red = f'<font color="red">{due}</font>' if due != "-" else "-"
            file_label = u.file_name or "-"
            if u.task_type:
                file_label += f" ({u.task_type})"
            fv = getattr(u, "file_version", None) or "-"
            ddd = (u.document_display_date.strftime("%Y-%m-%d") if u.document_display_date else "-") if getattr(u, "document_display_date", None) else "-"
            rev = getattr(u, "reviewer", None) or "-"
            appr = getattr(u, "approver", None) or "-"
            line = f" - 文件名称：{file_label}  文件版本号：{fv}  截止日期：{due_red}  文档体现日期：{ddd}  审核：{rev}  批准：{appr}"
            if link:
                line += f"  文档地址：[点击打开]({link})"
            lines.append(line)
        return "\n".join(lines)
    
    task_list_with_links_md = "\n\n".join(
        _task_block_md(k, grp) for k, grp in groups.items()
    )
    
    base_url = _get_base_url()
    page2_path = url_for("pages.generate_page", _external=False)
    page2_url = f"{base_url}{page2_path}" if base_url else url_for("pages.generate_page", _external=True)
    message_plain = (
        "【项目任务催办】\n\n"
        f"项目：{project_name}\n\n"
        f"未完成任务数：{len(pending_uploads)}\n\n"
        f"请以下人员尽快完成：{'、'.join(assignees)}\n\n\n"
        "未完成列表：\n\n"
        f"{task_list_with_links_md}\n\n"
        f"页面2（我的任务）：[点击打开]({page2_url})（账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456）\n\n"
        "### **编写完成后请在页面2中标记完成状态。**\n\n"
        "请抓紧处理！"
    )
    at_mobiles = _resolve_mobiles_for_authors(assignees)
    result = dingtalk_service.send_markdown_message(
        "项目任务催办",
        message_plain,
        at_all=False,
        at_mobiles=at_mobiles,
        at_names=assignees,
        webhook=webhook,
        secret=secret,
    )
    ok = result is not None and result.get("success") is True
    if ok:
        return jsonify({"success": True, "message": "通知发送成功", "atNames": list(assignees)}), 200
    err = result.get("error", "未知错误") if result else "未知错误"
    if isinstance(err, dict):
        err = "未知错误"
    return jsonify({"success": False, "message": f"通知发送失败: {err}"}), 200


@bp.post("/api/notify/by-author")
@page13_access_required
def api_notify_by_author():
    """按编写人员推送钉钉通知"""
    data = request.get_json(force=True) or {}
    author = data.get("author")
    
    if not author:
        return jsonify({"message": "请提供编写人员"}), 400
    
    webhook = (current_app.config.get("DINGTALK_WEBHOOK") or os.environ.get("DINGTALK_WEBHOOK") or "").strip()
    secret = (current_app.config.get("DINGTALK_SECRET") or os.environ.get("DINGTALK_SECRET") or "").strip() or None
    
    if not webhook:
        return jsonify({"message": "未配置钉钉 Webhook，请在环境变量中设置 DINGTALK_WEBHOOK"}), 400
    
    pending_uploads = UploadRecord.query.filter(
        UploadRecord.author == author,
        UploadRecord.completion_status.is_(None)
    ).all()
    
    if not pending_uploads:
        return jsonify({"message": f"{author} 没有未完成的任务"})
    
    def _group_key(u):
        return (u.project_name or "", u.business_side or "", u.product or "")
    
    groups = {}
    for u in pending_uploads:
        k = _group_key(u)
        groups.setdefault(k, []).append(u)
    
    def _task_block_md(key, uploads_in_group):
        proj, bs, pr = key
        lines = []
        proj_code = getattr(uploads_in_group[0], "project_code", None) if uploads_in_group else None
        header = f"**项目：{proj or '-'}  项目编号：{proj_code or '-'}  影响业务方：{bs or '-'}  产品：{pr or '-'}**"
        lines.append(header)
        for u in uploads_in_group:
            links = u.get_template_links_list() or []
            link = links[0] if links else None
            due = u.due_date.strftime("%Y-%m-%d") if u.due_date else "-"
            due_red = f'<font color="red">{due}</font>' if due != "-" else "-"
            file_label = u.file_name or "-"
            if u.task_type:
                file_label += f" ({u.task_type})"
            fv = getattr(u, "file_version", None) or "-"
            ddd = (u.document_display_date.strftime("%Y-%m-%d") if u.document_display_date else "-") if getattr(u, "document_display_date", None) else "-"
            rev = getattr(u, "reviewer", None) or "-"
            appr = getattr(u, "approver", None) or "-"
            line = f" - 文件名称：{file_label}  文件版本号：{fv}  截止日期：{due_red}  文档体现日期：{ddd}  审核：{rev}  批准：{appr}"
            if link:
                line += f"  文档地址：[点击打开]({link})"
            lines.append(line)
        return "\n".join(lines)
    
    task_list = "\n\n".join(
        _task_block_md(k, grp) for k, grp in groups.items()
    )
    
    base_url = _get_base_url()
    page2_path = url_for("pages.generate_page", _external=False)
    page2_url = f"{base_url}{page2_path}" if base_url else url_for("pages.generate_page", _external=True)
    
    template = _get_notify_template("author_reminder")
    if not template:
        template = "【个人任务催办】\n致：{author}\n您有 {pending_count} 个任务待完成：\n{task_list}\n\n请抓紧处理！"
    
    message = template.format(
        author=author,
        pending_count=len(pending_uploads),
        task_list=task_list,
        page2_url=page2_url,
    )
    message = message.rstrip()
    if not message.endswith("请抓紧处理！"):
        message += "\n\n请抓紧处理！"
    message += f"\n\n页面2（我的任务）：[点击打开]({page2_url})（账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456）\n\n### **编写完成后请在页面2中标记完成状态。**"
    
    at_mobiles = _resolve_mobiles_for_authors([author])
    result = dingtalk_service.send_markdown_message(
        "个人任务催办",
        message,
        at_all=False,
        at_mobiles=at_mobiles,
        at_names=[author],
        webhook=webhook,
        secret=secret,
    )
    ok = result is not None and result.get("success") is True
    if ok:
        return jsonify({"success": True, "message": "通知发送成功", "atNames": [str(author)]}), 200
    err = result.get("error", "未知错误") if result else "未知错误"
    if isinstance(err, dict):
        err = "未知错误"
    return jsonify({"success": False, "message": f"通知发送失败: {err}"}), 200


@bp.post("/api/notify/single-task")
@page13_access_required
def api_notify_single_task():
    """单条任务推送钉钉通知"""
    data = request.get_json(force=True) or {}
    upload_id = data.get("uploadId")
    
    if not upload_id:
        return jsonify({"message": "请提供任务ID"}), 400
    
    webhook = (current_app.config.get("DINGTALK_WEBHOOK") or os.environ.get("DINGTALK_WEBHOOK") or "").strip()
    secret = (current_app.config.get("DINGTALK_SECRET") or os.environ.get("DINGTALK_SECRET") or "").strip() or None
    
    if not webhook:
        return jsonify({"message": "未配置钉钉 Webhook，请在环境变量中设置 DINGTALK_WEBHOOK"}), 400
    
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到该任务"}), 404
    
    if upload.completion_status:
        return jsonify({"message": "该任务已完成，无需催办"})
    
    doc_link = ""
    if upload.template_links:
        links = upload.get_template_links_list()
        if links:
            doc_link = links[0]
    due_date_str = upload.due_date.strftime("%Y-%m-%d") if upload.due_date else "-"
    due_red = f'<font color="red">{due_date_str}</font>' if due_date_str != "-" else "-"
    business_side = upload.business_side or "-"
    product = upload.product or "-"
    country = upload.country or "-"
    project_code = getattr(upload, "project_code", None) or "-"
    file_version = getattr(upload, "file_version", None) or "-"
    doc_display_date = (upload.document_display_date.strftime("%Y-%m-%d") if upload.document_display_date else "-") if getattr(upload, "document_display_date", None) else "-"
    reviewer = getattr(upload, "reviewer", None) or "-"
    approver = getattr(upload, "approver", None) or "-"
    project_notes = getattr(upload, "project_notes", None) or "-"
    title = f"{upload.project_name}/{upload.file_name}" + (f" ({upload.task_type})" if upload.task_type else "")
    doc_link_md = f"[点击打开]({doc_link})" if doc_link else "（无链接）"

    template = _get_notify_template("single_task_reminder")
    if not template:
        template = (
            "【任务催办】\n致：{author}\n\n"
            "- **{title}**\n"
            " - 截止日期：{due_date}\n"
            " - 影响业务方：{business_side}\n"
            " - 产品：{product}\n"
            " - 国家：{country}\n"
            " - 文档地址：{doc_link_md}\n\n"
            "请抓紧处理！"
        )

    base_url = _get_base_url()
    page2_path = url_for("pages.generate_page", _external=False)
    page2_url = f"{base_url}{page2_path}" if base_url else url_for("pages.generate_page", _external=True)

    message_plain = template.format(
        author=upload.author,
        project_name=upload.project_name,
        file_name=upload.file_name,
        task_type=upload.task_type or "-",
        title=title,
        due_date=due_red,
        business_side=business_side,
        product=product,
        country=country,
        project_code=project_code,
        project_notes=project_notes,
        file_version=file_version,
        document_display_date=doc_display_date,
        reviewer=reviewer,
        approver=approver,
        doc_link_md=doc_link_md,
        doc_link=doc_link_md,
        page2_url=page2_url,
    )
    message_plain = message_plain.rstrip()
    if not message_plain.endswith("请抓紧处理！"):
        message_plain += "\n\n请抓紧处理！"
    message_plain += f"\n\n页面2（我的任务）：[点击打开]({page2_url})（账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456）\n\n### **编写完成后请在页面2中标记完成状态。**"
    
    at_mobiles = _resolve_mobiles_for_authors([upload.author])
    result = dingtalk_service.send_markdown_message(
        "任务催办",
        message_plain,
        at_all=False,
        at_mobiles=at_mobiles,
        at_names=[upload.author],
        webhook=webhook,
        secret=secret,
    )
    ok = result is not None and result.get("success") is True
    if ok:
        return jsonify({"success": True, "message": "通知发送成功", "atNames": [str(upload.author)]}), 200
    err = result.get("error", "未知错误") if result else "未知错误"
    if isinstance(err, dict):
        err = "未知错误"
    return jsonify({"success": False, "message": f"通知发送失败: {err}"}), 200


@bp.get("/api/notify/next-schedule")
@page13_access_required
def api_notify_next_schedule():
    """获取下一次自动通知时间（使用统计页配置的定时）"""
    from . import scheduler_service
    from .scheduler import _get_schedule_config_from_db
    cfg = _get_schedule_config_from_db()
    next_times = scheduler_service.get_next_run_times(cfg)
    
    webhook = current_app.config.get("DINGTALK_WEBHOOK", "")
    next_times["dingtalkConfigured"] = bool(webhook)
    
    return jsonify(next_times)


@bp.get("/api/notify/schedule-config")
@page13_access_required
def api_get_schedule_config():
    """获取自动通知时间配置（统计页用）"""
    from .scheduler import _get_schedule_config_from_db
    cfg = _get_schedule_config_from_db()
    row = AppConfig.query.filter_by(config_key="MODULE_CASCADE_DELAY_MINUTES").first()
    delay_minutes = 5
    if row and row.config_value:
        try:
            delay_minutes = max(1, min(1440, int(str(row.config_value).strip())))
        except ValueError:
            pass
    return jsonify({
        "weekly": cfg["weekly"],
        "overdue": cfg["overdue"],
        "project": cfg["project"],
        "moduleCascadeDelayMinutes": delay_minutes,
    })


@bp.put("/api/notify/schedule-config")
@page13_access_required
def api_put_schedule_config():
    """保存自动通知时间配置并立即生效"""
    data = request.get_json() or {}
    weekly = (data.get("weekly") or "").strip() or "thu 16:00"
    overdue = (data.get("overdue") or "").strip() or "15:00"
    project = (data.get("project") or "").strip() or "mon,wed,fri 9:30"
    delay_minutes = 5
    if "moduleCascadeDelayMinutes" in data:
        try:
            delay_minutes = max(1, min(1440, int(data.get("moduleCascadeDelayMinutes", 5))))
        except (TypeError, ValueError):
            pass
    for key, value in [
        ("SCHEDULE_WEEKLY_REMINDER", weekly),
        ("SCHEDULE_OVERDUE_REMINDER", overdue),
        ("SCHEDULE_PROJECT_STATS", project),
        ("MODULE_CASCADE_DELAY_MINUTES", str(delay_minutes)),
    ]:
        row = AppConfig.query.filter_by(config_key=key).first()
        if row:
            row.config_value = value
        else:
            db.session.add(AppConfig(config_key=key, config_value=value))
    db.session.commit()
    try:
        from .scheduler import reschedule_jobs
        reschedule_jobs(current_app._get_current_object())
    except Exception:
        pass
    return jsonify({"success": True, "message": "已保存并已更新定时任务"})


@bp.get("/api/notify/module-cascade-status")
@page13_access_required
def api_module_cascade_status():
    """模块级联催办状态：可配置延迟分钟数、待执行列表、最近已执行列表。"""
    row = AppConfig.query.filter_by(config_key="MODULE_CASCADE_DELAY_MINUTES").first()
    delay_minutes = 5
    if row and row.config_value:
        try:
            delay_minutes = max(1, min(1440, int(str(row.config_value).strip())))
        except ValueError:
            pass
    pending = ModuleCascadeReminder.query.filter_by(status="pending").order_by(ModuleCascadeReminder.run_at).all()
    recent_sent = (
        ModuleCascadeReminder.query.filter_by(status="sent")
        .order_by(ModuleCascadeReminder.sent_at.desc())
        .limit(20)
        .all()
    )
    return jsonify({
        "delayMinutes": delay_minutes,
        "pending": [
            {
                "projectName": r.project_name,
                "triggerModule": r.trigger_module,
                "targetModule": r.target_module,
                "runAt": r.run_at.strftime("%Y-%m-%d %H:%M") if r.run_at else None,
            }
            for r in pending
        ],
        "recentSent": [
            {
                "projectName": r.project_name,
                "triggerModule": r.trigger_module,
                "targetModule": r.target_module,
                "sentAt": r.sent_at.strftime("%Y-%m-%d %H:%M") if r.sent_at else None,
            }
            for r in recent_sent
        ],
    })


@bp.post("/api/notify/module-cascade-manual")
@page13_access_required
def api_notify_module_cascade_manual():
    """手动模块级联催办：按项目检查，产品全部完成→催办开发；开发全部完成→催办测试。body 可传 projectName 仅处理该项目。"""
    webhook = (current_app.config.get("DINGTALK_WEBHOOK") or os.environ.get("DINGTALK_WEBHOOK") or "").strip()
    if not webhook:
        return jsonify({"success": False, "message": "未配置 DINGTALK_WEBHOOK"}), 400
    data = request.get_json(silent=True) or {}
    project_name = (data.get("projectName") or "").strip() or None
    try:
        from .scheduler import _run_module_cascade_manual
        _run_module_cascade_manual(project_name=project_name)
        if project_name:
            return jsonify({"success": True, "message": f"已执行「{project_name}」的模块级联催办"})
        return jsonify({"success": True, "message": "已执行模块级联催办（按项目：产品→开发、开发→测试）"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@bp.post("/api/notify/test-auto")
@page13_access_required
def api_notify_test_auto():
    """测试自动催办：按类型执行与定时任务完全相同的逻辑，仅时间提前到点击时。"""
    webhook = (current_app.config.get("DINGTALK_WEBHOOK") or os.environ.get("DINGTALK_WEBHOOK") or "").strip()
    if not webhook:
        return jsonify({
            "success": False,
            "webhook_configured": False,
            "message": "未配置 DINGTALK_WEBHOOK，请在 .env 或环境变量中设置",
        }), 400

    payload = request.get_json(silent=True) or {}
    test_type = (payload.get("type") or "").strip().lower()

    if test_type == "thursday":
        from .scheduler import _run_thursday_reminder
        _run_thursday_reminder()
        return jsonify({
            "success": True,
            "webhook_configured": True,
            "message": "已按定时任务逻辑发送（每周任务完成提醒）",
            "type": test_type,
        })
    if test_type == "overdue":
        from .scheduler import _run_overdue_reminder
        res = _run_overdue_reminder()
        if res is None:
            return jsonify({
                "success": False,
                "webhook_configured": True,
                "message": "执行异常",
                "type": test_type,
            })
        if res.get("no_tasks"):
            return jsonify({
                "success": True,
                "webhook_configured": True,
                "message": "无明日截止任务，未发送",
                "type": test_type,
            })
        sent, failed = res.get("sent") or 0, res.get("failed") or 0
        if failed > 0 or sent == 0:
            err = res.get("last_error") or "钉钉未返回成功"
            return jsonify({
                "success": False,
                "webhook_configured": True,
                "message": f"发送失败：{err}" + (f"（成功 {sent} 条，失败 {failed} 条）" if sent else ""),
                "type": test_type,
            })
        return jsonify({
            "success": True,
            "webhook_configured": True,
            "message": f"已发送 {sent} 条逾期提醒",
            "type": test_type,
        })
    if test_type == "project_stats":
        from .scheduler import _run_project_stats
        _run_project_stats()
        return jsonify({
            "success": True,
            "webhook_configured": True,
            "message": "已按定时任务逻辑发送（每两天项目完成情况统计）",
            "type": test_type,
        })
    if test_type == "module_cascade":
        from .scheduler import _run_process_module_cascade_pending
        _run_process_module_cascade_pending()
        return jsonify({
            "success": True,
            "webhook_configured": True,
            "message": "已处理到期的模块级联催办（按项目：产品完成→催办开发；开发完成→催办测试）",
            "type": test_type,
        })

    from . import dingtalk_service
    secret = (current_app.config.get("DINGTALK_SECRET") or os.environ.get("DINGTALK_SECRET") or "").strip() or None
    content = "【自动催办测试】通道正常。定时任务将按配置时间发送每周任务完成提醒、逾期前一日催告、每两天项目完成情况统计。"
    result = dingtalk_service.send_text_message(content, webhook=webhook, secret=secret)
    ok = result.get("success") is True
    errmsg = result.get("error") or ""
    return jsonify({
        "success": ok,
        "webhook_configured": True,
        "message": "测试消息已发送" if ok else (errmsg or "钉钉返回失败，请检查 Webhook/Secret 及网络"),
        "type": test_type or "default",
    })


def register_blueprint(app):
    app.register_blueprint(bp)
