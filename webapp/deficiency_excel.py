# -*- coding: utf-8 -*-
"""发补记录 Excel 导入/模板（页面0）。"""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from typing import Any, Optional

from openpyxl import Workbook, load_workbook

# 表头（中文）→ 内部字段
_HEADER_MAP: dict[str, str] = {
    "所属项目": "project_name",
    "项目名称": "project_name",
    "项目": "project_name",
    "project": "project_name",
    "project name": "project_name",
    "发补意见": "opinion_text",
    "意见": "opinion_text",
    "opinion": "opinion_text",
    "优先级": "priority",
    "priority": "priority",
    "整改方案": "remediation_plan",
    "方案": "remediation_plan",
    "plan": "remediation_plan",
    "发补时间": "issued_on",
    "发补日期": "issued_on",
    "issued_on": "issued_on",
    "issued on": "issued_on",
    "整改状态": "remediation_status",
    "状态": "remediation_status",
    "status": "remediation_status",
    "整改完成时间": "completed_on",
    "整改完成日期": "completed_on",
    "完成时间": "completed_on",
    "完成日期": "completed_on",
    "completed_on": "completed_on",
    "发补类型": "deficiency_type",
    "类型": "deficiency_type",
    "type": "deficiency_type",
    "发补来源": "deficiency_source",
    "来源": "deficiency_source",
    "source": "deficiency_source",
}

_TEMPLATE_HEADERS = [
    "所属项目",
    "发补意见",
    "优先级",
    "整改方案",
    "发补日期",
    "整改状态",
    "整改完成日期",
    "发补类型",
    "发补来源",
]

_TEMPLATE_EXAMPLE = [
    "示例血糖仪二类项目",
    "请补充软件需求与风险分析的追溯关系说明。",
    "高",
    "在 SRS 与风险管理报告中补齐追溯矩阵并交叉核对编号。",
    "2024-06-12",
    "未完成",
    "",
    "注册审评发补",
    "器审中心",
]


def _norm_header(h: Any) -> str:
    s = str(h or "").strip().lower().replace(" ", "")
    s = s.replace("（", "(").replace("）", ")")
    return s


def _lookup_field(header: Any) -> Optional[str]:
    raw = str(header or "").strip()
    if not raw:
        return None
    if raw in _HEADER_MAP:
        return _HEADER_MAP[raw]
    compact = _norm_header(raw)
    for k, v in _HEADER_MAP.items():
        if _norm_header(k) == compact:
            return v
    return None


def build_deficiency_import_template_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "发补记录"
    ws.append(_TEMPLATE_HEADERS)
    ws.append(_TEMPLATE_EXAMPLE)
    ws2 = wb.create_sheet("填写说明")
    notes = [
        "1. 请从「发补记录」Sheet 第 2 行起填写；第 1 行为表头，勿改列名。",
        "2. 「所属项目」须与页面0 公司总览中的项目名称一致（同一公司下）。",
        "3. 注册国家/类别由所属项目自动带出，Excel 中不必填写。",
        "4. 优先级：高 / 中 / 低（或 high / medium / low）。",
        "5. 整改状态：未完成 / 已完成（或 open / done）。已完成时建议填写整改完成日期，缺省为导入当天。",
        "6. 发补类型：注册审评发补 / 体考发补（或 registration_review / type_testing）。",
        "7. 日期格式：YYYY-MM-DD，或 Excel 日期单元格。",
        "8. 示例行可删除后导入。",
    ]
    for line in notes:
        ws2.append([line])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _parse_date_cell(val: Any) -> Optional[str]:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()
    s = str(val).strip()
    if not s:
        return None
    # 2024/6/12 or 2024-06-12
    m = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    if len(s) >= 10:
        try:
            return date.fromisoformat(s[:10]).isoformat()
        except ValueError:
            return None
    return None


def _parse_priority(val: Any) -> str:
    s = str(val or "").strip().lower()
    if s in ("高", "high", "h", "3"):
        return "high"
    if s in ("低", "low", "l", "1"):
        return "low"
    return "medium"


def _parse_status(val: Any) -> str:
    s = str(val or "").strip().lower()
    if s in ("已完成", "完成", "done", "completed", "closed", "close"):
        return "done"
    return "open"


def _parse_type(val: Any) -> str:
    s = str(val or "").strip().lower().replace(" ", "")
    if not s:
        return "registration_review"
    if "体考" in s or "型检" in s or s in ("type_testing", "typetesting", "tt"):
        return "type_testing"
    if "审评" in s or "注册" in s or s in ("registration_review", "registrationreview", "rr"):
        return "registration_review"
    if s == "type_testing":
        return "type_testing"
    return "registration_review"


def parse_deficiency_excel(file_bytes: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """解析 Excel → 行字典列表；返回 (rows, warnings)。跳过空行。"""
    warnings: list[str] = []
    try:
        wb = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    except Exception as exc:
        raise ValueError(f"无法读取 Excel：{exc}") from exc
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        raise ValueError("Excel 为空") from None
    col_index: dict[int, str] = {}
    for i, h in enumerate(header_row or []):
        field = _lookup_field(h)
        if field:
            col_index[i] = field
    if "project_name" not in col_index.values():
        raise ValueError("缺少「所属项目」列")
    if "opinion_text" not in col_index.values():
        raise ValueError("缺少「发补意见」列")
    if "issued_on" not in col_index.values():
        raise ValueError("缺少「发补日期/发补时间」列")

    out: list[dict[str, Any]] = []
    for excel_row_no, row in enumerate(rows_iter, start=2):
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue
        item: dict[str, Any] = {"_excel_row": excel_row_no}
        for i, field in col_index.items():
            if i >= len(row):
                continue
            item[field] = row[i]
        # 跳过仍为示例标题行的明显模板样例（可选：不强制）
        project_name = str(item.get("project_name") or "").strip()
        opinion = str(item.get("opinion_text") or "").strip()
        if not project_name and not opinion:
            continue
        issued = _parse_date_cell(item.get("issued_on"))
        completed = _parse_date_cell(item.get("completed_on"))
        status = _parse_status(item.get("remediation_status"))
        if status == "done" and not completed:
            completed = date.today().isoformat()
        if status == "open":
            completed = None
        parsed = {
            "_excel_row": excel_row_no,
            "project_name": project_name,
            "opinion_text": opinion,
            "priority": _parse_priority(item.get("priority")),
            "remediation_plan": str(item.get("remediation_plan") or "").strip(),
            "issued_on": issued,
            "remediation_status": status,
            "completed_on": completed,
            "deficiency_type": _parse_type(item.get("deficiency_type")),
            "deficiency_source": str(item.get("deficiency_source") or "").strip(),
        }
        if not parsed["project_name"]:
            warnings.append(f"第 {excel_row_no} 行：缺少所属项目，已跳过")
            continue
        if not parsed["opinion_text"]:
            warnings.append(f"第 {excel_row_no} 行：缺少发补意见，已跳过")
            continue
        if not parsed["issued_on"]:
            warnings.append(f"第 {excel_row_no} 行：发补日期无效，已跳过")
            continue
        out.append(parsed)
    try:
        wb.close()
    except Exception:
        pass
    if not out:
        raise ValueError("未解析到有效发补行（请确认表头与数据行）")
    return out, warnings
