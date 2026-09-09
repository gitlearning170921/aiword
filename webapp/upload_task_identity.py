"""任务身份：同项目、同目标版本下不可重复；不同目标版本允许相同文件任务。"""
from __future__ import annotations

import re
from typing import Any, Optional

from sqlalchemy import or_

_SOFTWARE_TARGET_VERSION_RE = re.compile(r"^v?\s*\d+\.\d+\.\d+\.\d+$", re.I)


def normalize_target_version(value: Any) -> str:
    return str(value or "").strip()


def looks_like_software_target_version(value: Any) -> bool:
    return bool(_SOFTWARE_TARGET_VERSION_RE.match(normalize_target_version(value)))


def upload_task_identity_fields(
    *,
    project_name: str,
    file_name: str,
    task_type: Any,
    author: str,
    target_version: Any,
) -> dict[str, Any]:
    return {
        "project_name": project_name,
        "file_name": file_name,
        "task_type": (str(task_type).strip() if task_type is not None else "") or None,
        "author": author,
        "target_version": normalize_target_version(target_version),
    }


def find_upload_task_duplicate(
    *,
    project_name: str,
    file_name: str,
    task_type: Any,
    author: str,
    target_version: Any,
    exclude_id: Optional[str] = None,
):
    from .models import UploadRecord

    fields = upload_task_identity_fields(
        project_name=project_name,
        file_name=file_name,
        task_type=task_type,
        author=author,
        target_version=target_version,
    )
    q = UploadRecord.query.filter(
        UploadRecord.project_name == fields["project_name"],
        UploadRecord.file_name == fields["file_name"],
        UploadRecord.author == fields["author"],
    )
    tt = fields["task_type"]
    if tt:
        q = q.filter(UploadRecord.task_type == tt)
    else:
        q = q.filter(or_(UploadRecord.task_type.is_(None), UploadRecord.task_type == ""))
    tv = fields["target_version"]
    if tv:
        q = q.filter(UploadRecord.target_version == tv)
    else:
        q = q.filter(or_(UploadRecord.target_version.is_(None), UploadRecord.target_version == ""))
    if exclude_id:
        q = q.filter(UploadRecord.id != exclude_id)
    return q.first()


def duplicate_task_message(target_version: Any, task_type: Any, author: str) -> str:
    ver = normalize_target_version(target_version) or "未指定"
    return (
        f"存在同项目+同目标版本+同文件+同类型+同编写人"
        f"（目标版本 {ver} / {task_type or '无'} / {author}），是否需要替换原有内容？"
    )
