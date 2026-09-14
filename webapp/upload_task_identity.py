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


def project_upload_name_aliases(project: Any) -> list[str]:
    """页面1 任务用展示名（名称＋国家/类别），版本清单下发须同时认本名。"""
    from webapp.authz import project_display_label

    label = project_display_label(
        getattr(project, "name", None),
        getattr(project, "registered_country", None),
        getattr(project, "registered_category", None),
    ).strip()
    base = str(getattr(project, "name", None) or "").strip()
    out: list[str] = []
    for name in (label, base):
        if name and name not in out:
            out.append(name)
    return out


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


def _filter_file_and_target_version(q, file_name: str, target_version: Any, exclude_id: Optional[str] = None):
    from .models import UploadRecord

    tv = normalize_target_version(target_version)
    q = q.filter(UploadRecord.file_name == file_name)
    if tv:
        q = q.filter(UploadRecord.target_version == tv)
    else:
        q = q.filter(or_(UploadRecord.target_version.is_(None), UploadRecord.target_version == ""))
    if exclude_id:
        q = q.filter(UploadRecord.id != exclude_id)
    return q


def find_upload_task_duplicate_for_project(
    *,
    project: Any,
    file_name: str,
    task_type: Any,
    author: str,
    target_version: Any,
    exclude_id: Optional[str] = None,
):
    """按项目展示名、本名、project_id 查找已有任务，避免下发拆成另一个项目。"""
    for pname in project_upload_name_aliases(project):
        hit = find_upload_task_duplicate(
            project_name=pname,
            file_name=file_name,
            task_type=task_type,
            author=author,
            target_version=target_version,
            exclude_id=exclude_id,
        )
        if hit:
            return hit
    pid = str(getattr(project, "id", None) or "").strip()
    if not pid:
        return None
    from .models import UploadRecord

    fields = upload_task_identity_fields(
        project_name="",
        file_name=file_name,
        task_type=task_type,
        author=author,
        target_version=target_version,
    )
    q = UploadRecord.query.filter(
        UploadRecord.project_id == pid,
        UploadRecord.author == fields["author"],
    )
    tt = fields["task_type"]
    if tt:
        q = q.filter(UploadRecord.task_type == tt)
    else:
        q = q.filter(or_(UploadRecord.task_type.is_(None), UploadRecord.task_type == ""))
    q = _filter_file_and_target_version(q, fields["file_name"], fields["target_version"], exclude_id)
    return q.first()


def list_upload_tasks_same_file_type_version(
    *,
    project: Any,
    file_name: str,
    task_type: Any,
    target_version: Any,
    exclude_id: Optional[str] = None,
) -> list[Any]:
    """同项目 + 同文件名 + 同类型 + 同目标版本（不限责任人）。"""
    from .models import UploadRecord

    tt = (str(task_type).strip() if task_type is not None else "") or None
    seen: set[str] = set()
    candidates: list[Any] = []

    def _collect(rows: list[Any]) -> None:
        for row in rows:
            rid = str(getattr(row, "id", "") or "")
            if not rid or rid in seen:
                continue
            seen.add(rid)
            candidates.append(row)

    def _typed(q):
        if tt:
            q = q.filter(UploadRecord.task_type == tt)
        else:
            q = q.filter(or_(UploadRecord.task_type.is_(None), UploadRecord.task_type == ""))
        return _filter_file_and_target_version(q, file_name, target_version, exclude_id)

    names = project_upload_name_aliases(project)
    if names:
        _collect(_typed(UploadRecord.query.filter(UploadRecord.project_name.in_(names))).all())
    pid = str(getattr(project, "id", None) or "").strip()
    if pid:
        _collect(_typed(UploadRecord.query.filter(UploadRecord.project_id == pid)).all())
    return candidates


def split_task_authors(raw: Any) -> list[str]:
    """责任人可用英文逗号分隔多人；空则视为待分配。"""
    text = str(raw or "").strip()
    if not text:
        return ["待分配"]
    names: list[str] = []
    seen: set[str] = set()
    for part in text.split(","):
        name = str(part or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names or ["待分配"]


def expand_preview_items_by_author(items: list[Any]) -> list[dict[str, Any]]:
    """下发前按责任人拆成多条，预览行仍可写「张三,李四」。"""
    out: list[dict[str, Any]] = []
    for row in items or []:
        if not isinstance(row, dict):
            continue
        authors = split_task_authors(row.get("author"))
        for name in authors:
            rec = dict(row)
            rec["author"] = name
            rec["_authorGroupSize"] = len(authors)
            out.append(rec)
    return out


def pick_latest_upload_task(rows: list[Any]) -> Any:
    def _ts(row: Any) -> float:
        updated = getattr(row, "updated_at", None)
        if updated is None:
            return 0.0
        try:
            return float(updated.timestamp())
        except Exception:
            return 0.0

    return max(rows, key=_ts) if rows else None


def duplicate_task_message(target_version: Any, task_type: Any, author: str) -> str:
    ver = normalize_target_version(target_version) or "未指定"
    return (
        f"存在同项目+同目标版本+同文件+同类型+同编写人"
        f"（目标版本 {ver} / {task_type or '无'} / {author}），是否需要替换原有内容？"
    )
