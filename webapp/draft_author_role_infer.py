# -*- coding: utf-8 -*-
"""编写人员身份推断：与 aicheckword ``src/app.py`` 中 ``_infer_draft_author_role_idx`` 逻辑对齐。"""

from __future__ import annotations

# 与 aicheckword 初稿页下拉顺序一致
DRAFT_AUTHOR_ROLE_KEYS: tuple[str, ...] = ("", "pm", "pjm", "rm", "rdm", "ui", "qa", "cm", "ra", "prod")

DRAFT_AUTHOR_ROLE_LABELS: tuple[str, ...] = (
    "（未指定）通用技术编写",
    "产品经理",
    "项目经理",
    "风险经理",
    "研发经理",
    "UI设计师",
    "测试工程师",
    "配置管理员",
    "注册工程师",
    "生产专员",
)


def infer_draft_author_role_key(
    file_names: list,
    *,
    registration_type: str = "",
    project_form: str = "",
) -> str:
    """根据待生成文件名与模板案例上的注册类别/项目形态，推断 author_role 取值（_DRAFT_AUTHOR_ROLE_KEYS 之一）。"""
    scores = {k: 0 for k in DRAFT_AUTHOR_ROLE_KEYS}

    def _idx(k: str) -> int:
        try:
            return DRAFT_AUTHOR_ROLE_KEYS.index(k)
        except ValueError:
            return 0

    rt = (registration_type or "").strip()
    pf = (project_form or "").strip()
    high_risk_reg = any(x in rt for x in ("三类", "Ⅲ", "Ⅱb", "Ⅱa"))

    for fn in file_names or []:
        s = (fn or "").strip()
        if not s:
            continue
        low = s.lower()

        def _hit(*parts: str) -> bool:
            for p in parts:
                if not p:
                    continue
                if all(ord(c) < 128 for c in p):
                    if p.lower() in low:
                        return True
                else:
                    if p in s:
                        return True
            return False

        if _hit(
            "测试用例",
            "test case",
            "test execution",
            "system test",
            "system testing",
            "确认测试",
            "集成测试",
            "单元测试",
            "unit test",
            "integration test",
            "verification plan",
            "verification report",
            "validation plan",
            "validation report",
            "测试报告",
            "测试计划",
            "测试方案",
            "测试",
            "验证",
            "确认",
            "V&V",
            "IQ",
            "OQ",
            "PQ",
        ):
            scores["qa"] += 3
        if _hit("traceability", "追溯", "rtm", "可追溯性", "traceability analysis", "追溯矩阵", "追溯分析"):
            scores["qa"] += 2
        if _hit(
            "risk",
            "ras",
            "rmp",
            "rmr",
            "风险分析",
            "风险管理",
            "risk analysis",
            "risk management",
            "风险评估",
            "风险控制",
            "风险报告",
            "风险",
            "hazard",
            "fmea",
            "fta",
        ):
            scores["rm"] += 3
            if high_risk_reg:
                scores["rm"] += 1
        if _hit(
            "urs",
            "用户需求",
            "product requirement",
            "产品需求",
            "市场需求",
            "prd",
            "mrd",
            "需求",
            "user needs",
            "user requirement",
        ):
            scores["pm"] += 3
        if _hit(
            "srs",
            "软件需求规范",
            "requirement specification",
            "软件需求说明书",
            "软件需求",
            "software requirement",
            "software requirements",
        ):
            scores["rdm"] += 3
        if _hit(
            "architecture",
            "ads",
            "架构",
            "详细设计",
            "概要设计",
            "design specification",
            "sdd",
            "网络安全",
            "cybersecurity",
            "cyber security",
            "设计说明",
            "设计规范",
            "软件设计",
            "设计",
        ):
            scores["rdm"] += 2
        if _hit("software description", "软件描述", "软件研究"):
            scores["rdm"] += 2
        if _hit("audit", "审计", "日志", "权限", "access control", "编码规范"):
            scores["rdm"] += 1
        if _hit(
            "instruction",
            "ifu",
            "说明书",
            "使用说明",
            "udn",
            "user manual",
            "用户手册",
            "instructions for use",
            "产品技术要求",
            "注册申报",
            "注册申请",
            "注册自检",
            "技术审评",
            "临床评价",
        ):
            scores["ra"] += 2
        if _hit("label", "标签", "包装标识"):
            scores["ra"] += 1
        if _hit(
            "milestone",
            "计划",
            "project plan",
            "schedule",
            "开发计划",
            "项目计划",
            "进度计划",
            "立项",
            "里程碑",
        ):
            scores["pjm"] += 2
        if _hit(
            "config",
            "配置管理",
            "release",
            "baseline",
            "configuration",
            "version control",
            "版本控制",
            "变更管理",
            "变更控制",
            "配置项",
            "配置",
            "scm",
            "cm plan",
        ):
            scores["cm"] += 3
        if _hit(
            "interface",
            "界面",
            " ui",
            "usability",
            "可用性",
            "交互",
            "user experience",
            "用户体验",
            "ux",
        ):
            scores["ui"] += 2
        if _hit(
            "生产",
            "production",
            "manufacturing",
            "制造",
            "生产工艺",
            "生产放行",
            "工艺规程",
            "bom",
        ):
            scores["prod"] += 2
        if _hit("预期用途", "适应症", "intended use", "产品特性", "产品定义"):
            scores["pm"] += 1

    if max(scores.values()) == 0:
        if pf and any(x in pf for x in ("软件", "APP", "Web", "PC", "独立")):
            return DRAFT_AUTHOR_ROLE_KEYS[_idx("rdm")]
        return DRAFT_AUTHOR_ROLE_KEYS[0]

    tie_break = ["qa", "rm", "rdm", "ra", "pm", "pjm", "ui", "cm", "prod", ""]
    best = max(scores.values())
    for k in tie_break:
        if scores.get(k, 0) == best:
            return DRAFT_AUTHOR_ROLE_KEYS[_idx(k)]
    return DRAFT_AUTHOR_ROLE_KEYS[0]
