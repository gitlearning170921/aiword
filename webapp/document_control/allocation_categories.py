"""申请编号：台账分类与《文件控制程序》规则映射。"""

from __future__ import annotations

from typing import Any, Optional

from webapp.models import NumberingScheme

REGISTRATION_SHEET_NAME = "注册文件"

# 程序文件类型码 → 台账 Sheet 分类
DOC_TYPE_SHEET_CATEGORY: dict[str, str] = {
    "QM": "程序文件",
    "QP": "程序文件",
    "SMP": "程序文件",
    "SOP": "SOP",
    "SRS": "DHF",
    "WL": "四级表单",
    "QR": "四级表单",
}

# 用户按「分类」申请编号（常用 DHF / 注册文件）
ISSUE_SHEET_CATEGORIES: list[dict[str, Any]] = [
    {
        "sheetCategory": "DHF",
        "label": "DHF（技术文件）",
        "schemeDocTypeCode": "SRS",
        "autoAllocatable": True,
        "needsProjectCode": True,
        "needsSubtype": True,
        "subtypeFromTitle": True,
        "sort": 1,
    },
    {
        "sheetCategory": REGISTRATION_SHEET_NAME,
        "label": "注册文件",
        "schemeDocTypeCode": "SRS",
        "autoAllocatable": True,
        "needsProjectCode": True,
        "needsSubtype": True,
        "subtypeFromTitle": True,
        "sort": 2,
    },
    {
        "sheetCategory": "SOP",
        "label": "SOP（操作性文件）",
        "schemeDocTypeCode": "SOP",
        "autoAllocatable": True,
        "needsProjectCode": True,
        "needsSubtype": False,
        "sort": 3,
    },
    {
        "sheetCategory": "程序文件",
        "label": "程序文件（质量手册/程序/管理性文件）",
        "schemeDocTypeCode": None,
        "autoAllocatable": False,
        "manualHint": "按《文件控制程序》条款编号（如 QP4.2.3、SMP5.1-01），请手工填写后「新增」",
        "sort": 4,
    },
    {
        "sheetCategory": "四级表单",
        "label": "四级表单（外来文件/质量记录）",
        "schemeDocTypeCode": None,
        "autoAllocatable": False,
        "manualHint": "外来文件沿用标准号；质量记录如 QR-QP4.2.4-01，请手工填写",
        "sort": 5,
    },
]


def sheet_category_for_doc_type(doc_type_code: str) -> str:
    return DOC_TYPE_SHEET_CATEGORY.get((doc_type_code or "").strip().upper(), "")


def resolve_issue_category(sheet_category: str) -> Optional[dict[str, Any]]:
    cat = (sheet_category or "").strip()
    for item in ISSUE_SHEET_CATEGORIES:
        if item.get("sheetCategory") == cat:
            return item
    return None


def resolve_scheme_for_issue(
    org_id: str,
    *,
    sheet_category: str,
    scheme_id: Optional[str] = None,
) -> tuple[Optional[NumberingScheme], Optional[dict[str, Any]], Optional[str]]:
    """返回 (scheme, category_config, error_message)。"""
    if scheme_id:
        row = NumberingScheme.query.filter_by(id=scheme_id, organization_id=org_id).first()
        if not row:
            return None, None, "规则不存在"
        return row, None, None

    cfg = resolve_issue_category(sheet_category)
    if not cfg:
        return None, None, "未知分类"
    if not cfg.get("autoAllocatable"):
        hint = (cfg.get("manualHint") or "").strip() or "该分类须手工编号"
        return None, cfg, hint
    code = (cfg.get("schemeDocTypeCode") or "").strip().upper()
    if not code:
        return None, cfg, "该分类未配置自动取号规则，请先从知识库更新规则"
    row = NumberingScheme.query.filter_by(
        organization_id=org_id,
        doc_type_code=code,
    ).first()
    if not row:
        return None, cfg, f"未找到 {code} 编号规则，请先在「编号规则」从知识库更新"
    return row, cfg, None


def enrich_issue_categories(org_id: str) -> list[dict[str, Any]]:
    schemes = {
        (r.doc_type_code or "").upper(): r
        for r in NumberingScheme.query.filter_by(organization_id=org_id).all()
    }
    out: list[dict[str, Any]] = []
    for item in sorted(ISSUE_SHEET_CATEGORIES, key=lambda x: int(x.get("sort") or 0)):
        code = (item.get("schemeDocTypeCode") or "").strip().upper()
        scheme = schemes.get(code) if code else None
        row = {
            **item,
            "schemeId": scheme.id if scheme else None,
            "kbRuleExcerpt": (scheme.kb_rule_excerpt if scheme else None) or item.get("manualHint"),
        }
        if item.get("autoAllocatable") and code and not scheme:
            row["autoAllocatable"] = False
            row["disabledReason"] = f"请先从知识库更新规则（缺少 {code}）"
        out.append(row)
    return out
