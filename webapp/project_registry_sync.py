# -*- coding: utf-8 -*-
"""页面0 公司总览 ↔ 页面1 项目：登记字段双向同步。"""
from __future__ import annotations

from typing import Any, Optional

from flask import session

from .authz import parse_optional_date
from .models import CompanyProject, Project, now_local


def payload_from_api_data(data: dict) -> dict[str, Any]:
    """从 API JSON 提取可同步字段（仅包含请求中出现的键）。"""
    out: dict[str, Any] = {}
    if "productType" in data:
        out["product_type"] = (data.get("productType") or "").strip() or None
    if "expectedCertificationDate" in data:
        out["expected_certification_date"] = parse_optional_date(
            data.get("expectedCertificationDate")
        )
    if "expectedSubmissionDate" in data:
        out["expected_submission_date"] = parse_optional_date(
            data.get("expectedSubmissionDate")
        )
    if "progressDescription" in data:
        out["progress_description"] = (data.get("progressDescription") or "").strip() or None
        out["_touch_progress_meta"] = True
    if "assignedTeamId" in data:
        out["assigned_team_id"] = (data.get("assignedTeamId") or "").strip() or None
    return out


def payload_from_company_project(cp: CompanyProject) -> dict[str, Any]:
    return {
        "product_type": getattr(cp, "product_type", None),
        "assigned_team_id": getattr(cp, "assigned_team_id", None),
        "expected_certification_date": getattr(cp, "expected_certification_date", None),
        "expected_submission_date": getattr(cp, "expected_submission_date", None),
        "progress_description": getattr(cp, "progress_description", None),
        "progress_updated_at": getattr(cp, "progress_updated_at", None),
        "updated_by": getattr(cp, "updated_by", None),
    }


def payload_from_page1_project(p: Project) -> dict[str, Any]:
    return {
        "product_type": getattr(p, "product_type", None),
        "assigned_team_id": getattr(p, "assigned_team_id", None),
        "expected_certification_date": getattr(p, "expected_certification_date", None),
        "expected_submission_date": getattr(p, "expected_submission_date", None),
        "progress_description": getattr(p, "progress_description", None),
        "progress_updated_at": getattr(p, "progress_updated_at", None),
        "updated_by": getattr(p, "updated_by", None),
    }


def apply_payload_to_company(cp: CompanyProject, payload: dict[str, Any]) -> None:
    if "product_type" in payload:
        cp.product_type = payload["product_type"]
    if "assigned_team_id" in payload:
        cp.assigned_team_id = payload["assigned_team_id"]
    if "expected_certification_date" in payload:
        cp.expected_certification_date = payload["expected_certification_date"]
    if "expected_submission_date" in payload:
        cp.expected_submission_date = payload["expected_submission_date"]
    if "progress_description" in payload:
        cp.progress_description = payload["progress_description"]
        if payload.get("_touch_progress_meta"):
            cp.progress_updated_at = now_local()
            cp.updated_by = (
                session.get("display_name") or session.get("username") or None
            )
        elif "progress_updated_at" in payload:
            cp.progress_updated_at = payload.get("progress_updated_at")
            cp.updated_by = payload.get("updated_by")


def apply_payload_to_page1(p: Project, payload: dict[str, Any]) -> None:
    if "product_type" in payload:
        p.product_type = payload["product_type"]
    if "assigned_team_id" in payload:
        p.assigned_team_id = payload["assigned_team_id"]
    if "expected_certification_date" in payload:
        p.expected_certification_date = payload["expected_certification_date"]
    if "expected_submission_date" in payload:
        p.expected_submission_date = payload["expected_submission_date"]
    if "progress_description" in payload:
        p.progress_description = payload["progress_description"]
        if payload.get("_touch_progress_meta"):
            p.progress_updated_at = now_local()
            p.updated_by = (
                session.get("display_name") or session.get("username") or None
            )
        elif "progress_updated_at" in payload:
            p.progress_updated_at = payload.get("progress_updated_at")
            p.updated_by = payload.get("updated_by")


def sync_page1_to_company(p: Project, payload: Optional[dict[str, Any]] = None) -> bool:
    """页面1 更新后同步到关联的公司总览项目。"""
    cp_id = (getattr(p, "company_project_id", None) or "").strip()
    if not cp_id:
        return False
    cp = CompanyProject.query.get(cp_id)
    if not cp:
        return False
    pl = payload if payload is not None else payload_from_page1_project(p)
    if "progress_description" in pl and "_touch_progress_meta" not in pl:
        pl = dict(pl)
        if getattr(p, "progress_updated_at", None):
            pl["progress_updated_at"] = p.progress_updated_at
            pl["updated_by"] = getattr(p, "updated_by", None)
    apply_payload_to_company(cp, pl)
    return True


def sync_company_to_page1(
    company_project_id: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    push_nulls: bool = False,
) -> int:
    """公司总览更新后同步到所有关联的页面1 项目。

    push_nulls=False（列表加载等）：仅推送公司有值的字段，避免空公司总览覆盖页面1 已有登记信息。
    push_nulls=True（页面0 保存后）：含空值，支持在页面0 清空后同步到页面1。
    """
    cp = CompanyProject.query.get(company_project_id)
    if not cp:
        return 0
    pl = payload if payload is not None else payload_from_company_project(cp)
    if not push_nulls:
        pl = {k: v for k, v in pl.items() if v is not None}
    if not pl:
        return 0
    rows = Project.query.filter(Project.company_project_id == company_project_id).all()
    for p in rows:
        apply_payload_to_page1(p, pl)
    return len(rows)


def sync_all_linked_page1_from_company() -> int:
    """将各公司总览项目上已填登记字段，推送到其关联的全部页面1 项目。"""
    total = 0
    for cp in CompanyProject.query.all():
        n = sync_company_to_page1(cp.id)
        total += n
    return total
