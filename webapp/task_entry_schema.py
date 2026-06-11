"""
任务录入字段 schema：页面「任务录入」、下载模板、导入待办共用。

调整任务录入字段时须同步修改：
  1. 本文件 TASK_ENTRY_IMPORT_COLUMNS（列顺序与表头文案）
  2. web/static/js/app.js 中 createProjectBlock / createTaskRowUnderProject（DOM 顺序）
  3. api_upload / 编辑弹窗等写入 UploadRecord 的后端字段

下载模板与 CSV/Excel 导入仅依赖本模块，勿在 routes.py / app.js 重复维护表头。
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence

from .models import (
    TASK_TYPE_CATEGORY_FILE,
    TASK_TYPE_CATEGORY_MATTER,
    UploadRecord,
)

# 列顺序与任务录入 UI 一致：先第一层项目，再第二层任务行（含签批通用字段）
TASK_ENTRY_IMPORT_COLUMNS: Sequence[Dict[str, str]] = (
    {"key": "project_name", "label": "项目名称", "layer": "project"},
    {"key": "business_side", "label": "影响业务方", "layer": "project"},
    {"key": "product", "label": "影响产品", "layer": "project"},
    {"key": "country", "label": "国家", "layer": "project"},
    {"key": "project_code", "label": "项目编号", "layer": "project"},
    {"key": "project_notes", "label": "项目备注", "layer": "project"},
    {"key": "registered_product_name", "label": "注册产品名称", "layer": "project"},
    {"key": "model", "label": "型号", "layer": "project"},
    {"key": "registration_version", "label": "注册版本号", "layer": "project"},
    {"key": "fileName", "label": "文件名称", "layer": "task"},
    {"key": "task_category", "label": "任务类别", "layer": "task"},
    {"key": "task_type", "label": "任务类型", "layer": "task"},
    {"key": "belonging_module", "label": "所属模块", "layer": "task"},
    {"key": "template_links", "label": "文档链接", "layer": "task"},
    {"key": "author", "label": "编写人员", "layer": "task"},
    {"key": "assignee_name", "label": "负责人", "layer": "task"},
    {"key": "due_date", "label": "截止日期", "layer": "task"},
    {"key": "notes", "label": "下发任务备注", "layer": "task"},
    {"key": "file_version", "label": "文件版本号", "layer": "task"},
    {"key": "document_display_date", "label": "文档体现日期", "layer": "task"},
    {"key": "reviewer", "label": "审核人员", "layer": "task"},
    {"key": "approver", "label": "批准人员", "layer": "task"},
    {"key": "displayed_author", "label": "体现编写人员", "layer": "task"},
)

# 兼容旧模板 / 外部工具导出的表头别名（映射到 TASK_ENTRY_IMPORT_COLUMNS 的 key）
_IMPORT_HEADER_ALIASES: Dict[str, str] = {
    "产品": "product",
    "类型": "task_type",
    "task_type": "task_type",
    "projectName": "project_name",
    "projectCode": "project_code",
    "businessSide": "business_side",
    "product": "product",
    "country": "country",
    "projectNotes": "project_notes",
    "fileName": "fileName",
    "taskType": "task_type",
    "taskCategory": "task_category",
    "templateLinks": "template_links",
    "fileVersion": "file_version",
    "author": "author",
    "assigneeName": "assignee_name",
    "dueDate": "due_date",
    "notes": "notes",
    "documentDisplayDate": "document_display_date",
    "reviewer": "reviewer",
    "approver": "approver",
    "belongingModule": "belonging_module",
    "displayedAuthor": "displayed_author",
    "registeredProductName": "registered_product_name",
    "model": "model",
    "registrationVersion": "registration_version",
}


def import_template_headers() -> List[str]:
    return [c["label"] for c in TASK_ENTRY_IMPORT_COLUMNS]


def import_header_map() -> Dict[str, str]:
    out = {c["label"]: c["key"] for c in TASK_ENTRY_IMPORT_COLUMNS}
    out.update(_IMPORT_HEADER_ALIASES)
    return out


def import_schema_for_client() -> Dict[str, Any]:
    """供前端或文档使用的 JSON schema（表头顺序与字段 key）。"""
    return {
        "headers": import_template_headers(),
        "columns": [
            {"key": c["key"], "label": c["label"], "layer": c["layer"]}
            for c in TASK_ENTRY_IMPORT_COLUMNS
        ],
    }


def task_category_label(category: str) -> str:
    if (category or "").strip().lower() == TASK_TYPE_CATEGORY_MATTER:
        return "事项型"
    return "文件型"


def parse_task_category_label(raw: str) -> Optional[str]:
    v = (raw or "").strip().lower()
    if not v:
        return None
    if v in (TASK_TYPE_CATEGORY_MATTER, "matter", "事项", "事项型"):
        return TASK_TYPE_CATEGORY_MATTER
    if v in (TASK_TYPE_CATEGORY_FILE, "file", "文件", "文件型"):
        return TASK_TYPE_CATEGORY_FILE
    return None


def format_date_for_import(obj: Any) -> str:
    if obj is None:
        return ""
    if hasattr(obj, "strftime"):
        try:
            return obj.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return ""
    return str(obj)[:10] if obj else ""


def _values_from_upload_record(record: UploadRecord) -> Dict[str, str]:
    from .notify_content import task_type_category_of_upload

    cat = task_type_category_of_upload(record)
    return {
        "project_name": record.project_name or "",
        "project_code": record.project_code or "",
        "business_side": record.business_side or "",
        "product": record.product or "",
        "country": record.country or "",
        "project_notes": record.project_notes or "",
        "registered_product_name": str(getattr(record, "registered_product_name", None) or ""),
        "model": str(getattr(record, "model", None) or ""),
        "registration_version": str(getattr(record, "registration_version", None) or ""),
        "fileName": record.file_name or "",
        "task_category": task_category_label(cat),
        "task_type": record.task_type or "",
        "belonging_module": str(getattr(record, "belonging_module", None) or ""),
        "template_links": (record.template_links or "").replace("\n", " ").strip(),
        "author": record.author or "",
        "assignee_name": record.assignee_name or record.author or "",
        "due_date": format_date_for_import(record.due_date),
        "notes": record.notes or "",
        "file_version": str(getattr(record, "file_version", None) or ""),
        "document_display_date": format_date_for_import(getattr(record, "document_display_date", None)),
        "reviewer": str(getattr(record, "reviewer", None) or ""),
        "approver": str(getattr(record, "approver", None) or ""),
        "displayed_author": str(getattr(record, "displayed_author", None) or ""),
    }


def record_to_import_row(record: UploadRecord) -> List[str]:
    values = _values_from_upload_record(record)
    return [values[c["key"]] for c in TASK_ENTRY_IMPORT_COLUMNS]


def default_sample_import_row() -> List[str]:
    today = datetime.now().strftime("%Y-%m-%d")
    values = {
        "project_name": "示例项目",
        "project_code": "PRJ001",
        "business_side": "示例业务方",
        "product": "示例产品",
        "country": "中国",
        "project_notes": "项目备注示例",
        "registered_product_name": "注册产品示例",
        "model": "型号示例",
        "registration_version": "V1.0",
        "fileName": "示例文件.docx",
        "task_category": "文件型",
        "task_type": "初稿待编写",
        "belonging_module": "开发",
        "template_links": "https://example.com/doc.docx",
        "author": "张三",
        "assignee_name": "张三",
        "due_date": today,
        "notes": "下发任务备注示例",
        "file_version": "V1.0",
        "document_display_date": today,
        "reviewer": "审核人",
        "approver": "批准人",
        "displayed_author": "体现编写人",
    }
    return [values[c["key"]] for c in TASK_ENTRY_IMPORT_COLUMNS]


def build_import_template_csv(
    include_sample: bool,
    project_name: Optional[str] = None,
    *,
    records_for_project: Optional[List[UploadRecord]] = None,
    fallback_sample_record: Optional[UploadRecord] = None,
) -> str:
    """生成导入用 CSV 文本（UTF-8，无 BOM；routes 层加 utf-8-sig）。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(import_template_headers())
    if not include_sample:
        return buf.getvalue()

    if project_name and (project_name or "").strip() and records_for_project:
        for r in records_for_project:
            writer.writerow(record_to_import_row(r))
    elif fallback_sample_record:
        writer.writerow(record_to_import_row(fallback_sample_record))
    else:
        writer.writerow(default_sample_import_row())
    return buf.getvalue()


def validate_import_row_task_category(row: dict) -> Optional[str]:
    """
    若同时填写任务类别与任务类型，校验类型是否属于该类别。
    返回错误文案；无冲突时返回 None。
    """
    cat_raw = (row.get("task_category") or "").strip()
    task_type = (row.get("task_type") or "").strip()
    if not cat_raw or not task_type:
        return None
    expected = parse_task_category_label(cat_raw)
    if not expected:
        return f"任务类别「{cat_raw}」无效，请填写「文件型」或「事项型」"
    from .notify_content import _task_type_category_by_name

    actual = _task_type_category_by_name().get(task_type, TASK_TYPE_CATEGORY_FILE)
    if actual != expected:
        return (
            f"任务类型「{task_type}」属于「{task_category_label(actual)}」，"
            f"与任务类别「{task_category_label(expected)}」不一致"
        )
    return None


def parse_import_date(s: str) -> Optional[date]:
    if not s or not (s or "").strip():
        return None
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
