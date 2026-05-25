"""钉钉等推送通知中的任务行文案（含事项型任务的文档地址提示）。"""

from __future__ import annotations

import re
from typing import Dict

MATTER_COMPLETE_NOTES_MSG = "请在备注中填写事项完成情况"
MATTER_COMPLETE_NOTES_INVALID_MSG = "请在备注中填写有效的事项完成情况，不可仅填空格或符号"

# 事项型任务在通知中替代「点击打开」链接的固定说明
MATTER_TASK_DOC_LINK_HINT = "本条为实操项，请确保与相应文件内容一致"


def normalize_task_type_category(raw) -> str:
    from .models import TASK_TYPE_CATEGORIES, TASK_TYPE_CATEGORY_FILE

    v = (str(raw or "").strip().lower())
    if v in TASK_TYPE_CATEGORIES:
        return v
    return TASK_TYPE_CATEGORY_FILE


def _task_type_category_by_name() -> Dict[str, str]:
    from .models import TaskTypeConfig

    out: Dict[str, str] = {}
    for t in TaskTypeConfig.query.filter_by(is_active=True).all():
        name = (t.name or "").strip()
        if name:
            out[name] = normalize_task_type_category(getattr(t, "category", None))
    return out


def task_type_category_of_upload(upload) -> str:
    from .models import TASK_TYPE_CATEGORY_FILE

    tt = (getattr(upload, "task_type", None) or "").strip()
    if not tt:
        return TASK_TYPE_CATEGORY_FILE
    return _task_type_category_by_name().get(tt, TASK_TYPE_CATEGORY_FILE)


def is_matter_task_upload(upload) -> bool:
    from .models import TASK_TYPE_CATEGORY_MATTER

    return task_type_category_of_upload(upload) == TASK_TYPE_CATEGORY_MATTER


def is_meaningful_matter_execution_notes(raw) -> bool:
    """事项型完成备注：去空白后须含至少一个中文/字母/数字，拒绝纯空格或纯符号。"""
    s = str(raw or "").strip()
    if not s:
        return False
    core = re.sub(r"\s+", "", s)
    if not core:
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", core))


def notify_doc_link_suffix_md(upload) -> str:
    """任务行末尾的「文档地址：…」片段（含前导空格）。"""
    if is_matter_task_upload(upload):
        return f"  文档地址：{MATTER_TASK_DOC_LINK_HINT}"
    links = upload.get_template_links_list() or []
    link = links[0] if links else None
    if link:
        return f"  文档地址：[点击打开]({link})"
    return ""


def notify_doc_link_md_for_template(upload) -> str:
    """单条催办模板占位符 {doc_link_md}。"""
    if is_matter_task_upload(upload):
        return MATTER_TASK_DOC_LINK_HINT
    links = upload.get_template_links_list() or []
    if links:
        return f"[点击打开]({links[0]})"
    return "（无链接）"
