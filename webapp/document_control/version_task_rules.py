"""版本任务清单规则（内嵌回退自 YY-IW-020 V2.2 归档表；运行时优先知识库最新版）。

匹配顺序（与制度章节标题一致）：
1) 按主导变更位套用适用章节：变更管理=X/Y；缺陷管理=X/Y/Z；生产/发布=X/Y/Z/B
2) 主章节优先，其它适用章节补齐（同名归档物不重复）
3) 章节内再按「归档频率」过滤版本位；事件驱动频率本阶段不自动生成
4) 流程：X/Y→QP7.3.9；Z→SMP7.3-05；B→制度「要求」中的发布动作（不走缺陷）
5) 软件变更管理分 CE 获证 / 国内获证 两张表，按项目注册国家选择
"""

from __future__ import annotations

from typing import Any, Optional

# 来源文件（训练进知识库后，用同名文档刷新规则）
RULE_DOC_FILES = {
    "yy_iw_020": "YY -IW-020 医疗软件质量合规管理制度（V2.2）.docx",
    "qp_739": "QP 7.3.9 变更控制程序（A2）.docx",
    "smp_7305": "SMP 7.3-05 缺陷管理制度（A1）.docx",
}

CHAPTER_CHANGE = "软件变更管理"
CHAPTER_DEFECT = "缺陷管理"
CHAPTER_RELEASE = "软件生产/发布管理"

PROCESS_BRANCH_CHANGE = "change"
PROCESS_BRANCH_DEFECT = "defect"
PROCESS_BRANCH_RELEASE = "release"

RULES_MODE = "knowledge_base"  # 优先知识库最新 YY-IW-020，失败回退内嵌 V2.2

_RULE_OVERLAY: dict[str, Any] = {}

RULE_BASIS = (
    "①按 YY-IW-020 章节标题适用位："
    "软件变更管理=X/Y（CE/国内分表）；系统追溯=X/Y；"
    "缺陷管理=X/Y/Z；软件生产/发布管理=X/Y/Z/B。"
    "②主章节优先，其它适用章节补齐同名不重复。"
    "③章节内按归档频率过滤；事件驱动频率不自动生成。"
    "④流程：X/Y→QP7.3.9；Z→SMP7.3-05；B→制度「要求」中的发布动作（无则仅归档表）。"
)

MATCH_STEPS = [
    "按主导变更位匹配章节大标题适用位（变更管理 X/Y、缺陷 X/Y/Z、生产发布 X/Y/Z/B）",
    "主章节清单优先，其它适用章节补齐，归档物名称不重复",
    "章节内按归档频率过滤（每个版本 / X/Y 位 / 发现缺陷）；事件驱动不自动生成",
    "叠加流程：X/Y=QP7.3.9，Z=SMP7.3-05，B=制度「要求」中仍存在的发布动作",
]


def get_rule_overlay() -> dict[str, Any]:
    return _RULE_OVERLAY


def apply_rule_overlay(payload: Optional[dict[str, Any]]) -> None:
    """用知识库/本地解析结果覆盖归档清单；payload.ok 为假时清空。"""
    global _RULE_OVERLAY
    if not payload or not payload.get("ok"):
        _RULE_OVERLAY = {}
        return
    rows = payload.get("rows") or {}
    catalogs: dict[str, list[dict[str, Any]]] = {}
    mapping = (
        ("changeCe", "chg_ce", CHAPTER_CHANGE),
        ("changeNmpa", "chg_nmpa", CHAPTER_CHANGE),
        ("defect", "def", CHAPTER_DEFECT),
        ("release", "rel", CHAPTER_RELEASE),
        ("traceability", "tr", "系统追溯"),
    )
    for key, prefix, chapter in mapping:
        raw = rows.get(key) or []
        tuples = [tuple(x) for x in raw if x]
        if tuples:
            catalogs[key] = _tasks_from_rows(prefix, chapter, tuples)
    heading_raw = payload.get("headingBits") or {}
    heading = {
        str(k): frozenset(str(x).upper() for x in (v or []) if str(x).strip())
        for k, v in heading_raw.items()
        if v
    }
    _RULE_OVERLAY = {
        "catalogs": catalogs,
        "headingBits": heading,
        "processHints": payload.get("processHints") or {},
        "ruleSource": payload.get("ruleSource") or "",
        "matchedBy": payload.get("matchedBy") or "",
        "sourceFile": payload.get("sourceFile") or "",
        "sourceVersion": payload.get("sourceVersion") or "",
        "message": payload.get("message") or "",
    }


def _task(
    *,
    task_key: str,
    file_name: str,
    task_type: str,
    author: str,
    belonging_module: str,
    phase_offset_days: int,
    archive_frequency: str,
    reason: str,
    rule_ref: str,
    chapter: str = "",
    process_branch: str = "",
) -> dict[str, Any]:
    return {
        "taskKey": task_key,
        "fileName": file_name,
        "taskType": task_type,
        "author": author,
        "belongingModule": belonging_module,
        "phaseOffsetDays": phase_offset_days,
        "archiveFrequency": archive_frequency,
        # 兼容旧字段：由频率推导时写入
        "triggers": set(),
        "reason": reason,
        "ruleRef": rule_ref,
        "chapter": chapter,
        "processBranch": process_branch,
    }


_AUTHOR_MODULE = {
    "项目经理": "全员",
    "产品经理": "产品",
    "研发人员": "开发",
    "研发经理": "开发",
    "测试人员": "测试",
    "QC": "测试",
    "发布专员": "开发",
    "配置管理员": "全员",
    "风险经理": "全员",
    "UI负责人": "产品",
}

# 立即输出（制度「要求」）偏发布日前；其余上线后 1 周内
_IMMEDIATE_FILES = {
    "变更申请单",
    "软件需求规范",
    "架构设计规范",
    "系统测试方案",
    "软件发布说明",
    "发布记录",
    "成品检验记录",
    "检验记录",
}


def _offset_for(file_name: str, frequency: str) -> int:
    if file_name in _IMMEDIATE_FILES:
        return 0
    if frequency == "每个版本":
        return 7
    if "X/Y" in frequency:
        return 3
    return 7


def _archive_task(
    *,
    prefix: str,
    seq: str,
    file_name: str,
    frequency: str,
    author: str,
    chapter: str,
    caution: str = "",
    content_change: str = "",
) -> dict[str, Any]:
    bits = [f"YY-IW-020《{chapter}》", f"归档频率：{frequency}"]
    if content_change and content_change not in {"/", "／"}:
        bits.append(f"内容：{content_change}")
    if caution and caution not in {"/", "／"}:
        bits.append(caution)
    key = f"yy_{prefix}_{seq}_{file_name}"
    return _task(
        task_key=key,
        file_name=file_name,
        task_type="归档文件",
        author=author,
        belonging_module=_AUTHOR_MODULE.get(author, "全员"),
        phase_offset_days=_offset_for(file_name, frequency),
        archive_frequency=frequency,
        reason="；".join(bits) + "。",
        rule_ref="YY-IW-020",
        chapter=chapter,
    )


def _tasks_from_rows(prefix: str, chapter: str, rows: list[tuple]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        seq, name, freq, author = row[:4]
        caution = row[4] if len(row) > 4 else ""
        content_change = row[5] if len(row) > 5 else ""
        out.append(
            _archive_task(
                prefix=prefix,
                seq=str(seq),
                file_name=name,
                frequency=freq,
                author=author,
                chapter=chapter,
                caution=caution,
                content_change=content_change,
            )
        )
    return out


# 软件变更管理 · CE获证产品（制度表，文件名/频率逐字）
_CHANGE_CE_ROWS: list[tuple] = [
    ("2", "变更申请单", "每个版本", "项目经理", "识别所有影响到需要归档的文件清单", "重新修改"),
    ("3", "软件开发计划", "每个版本", "项目经理", "", "更新文件清单和时间"),
    ("8", "设计和开发评审报告（策划）", "每个版本", "项目经理", "", "重新修改"),
    ("9", "风险分析", "根据变更申请中风险评估结果决定", "风险经理", "", "重新评估，若无影响可不修改"),
    ("10", "网络安全风险分析", "变更涉及到网络安全时", "风险经理", "", "重新评估，若无影响可不修改"),
    ("11", "用户需求设计规范", "变更涉及到影响用户使用时", "UI负责人", "", "重新修改"),
    ("12", "软件需求规范", "每个版本", "产品经理", "", "重新修改"),
    ("13", "用户接口需求规范", "变更涉及到影响用户使用时", "产品经理", "", "重新修改"),
    ("14", "设计和开发评审报告（需求输入）", "每个版本", "项目经理", "", "重新修改"),
    ("15a", "代码评审报告", "每个版本", "研发人员", "", "重新修改"),
    ("15b", "源代码", "每个版本", "研发经理", "", "重新修改"),
    ("16", "架构设计规范", "每个版本", "研发人员", "", "重新修改"),
    ("17", "详细设计规范", "版本号X/Y位变更时", "研发人员", "", "重新修改"),
    ("18", "用户接口设计规范", "变更涉及到影响用户使用时", "研发人员", "", "重新修改"),
    ("71", "过程检验规程", "变更涉及到发布工艺流程时", "研发人员", "", "重新修改"),
    ("21", "成品检验规程", "版本号X/Y位变更时", "测试人员", "", "重新修改"),
    ("27", "用户手册", "变更涉及到影响用户使用时", "产品经理", "产品和注册一起编写，模板使用注册版本", "重新修改"),
    ("28", "设计和开发评审报告（开发输出）", "每个版本", "项目经理", "", "重新修改"),
    ("29", "单元测试方案", "版本号X/Y位变更时", "研发人员", "", "重新修改"),
    ("30a", "单元测试报告", "版本号X/Y位变更时", "研发人员", "", "重新修改"),
    ("30b", "单元测试记录", "版本号X/Y位变更时", "研发人员", "Gitlab导出测试记录归档，模版参照体系文件模板", "重新修改"),
    ("32", "系统测试方案", "每个版本", "测试人员", "", "重新修改"),
    ("33a", "系统测试报告", "每个版本", "测试人员", "", "重新修改"),
    ("33b", "系统测试记录", "每个版本", "测试人员", "禅道导出excel归档，模版参照体系文件模板", "重新修改"),
    ("34", "缺陷记录表", "每个版本", "测试人员", "禅道导出excel归档，模版参照体系文件模板", "重新修改"),
    ("38", "总结可用性测试方案", "变更涉及到影响用户使用时", "测试人员", "", "重新修改"),
    ("39a", "总结可用性测试报告", "变更涉及到影响用户使用时", "测试人员", "", "重新修改"),
    ("39b", "总结性可用性测试记录", "变更涉及到影响用户使用时", "测试人员", "", "重新修改"),
    ("42", "镜像包", "每个版本", "研发经理", "", "重新修改"),
    ("43", "软件发布说明", "每个版本", "研发人员", "", "重新修改"),
    ("44", "设计和开发评审报告（验证）", "每个版本", "项目经理", "", "重新修改"),
    ("45", "用户测试方案", "变更涉及到影响用户使用时", "测试人员", "", "重新修改"),
    ("46a", "用户测试报告", "变更涉及到影响用户使用时", "测试人员", "", "重新修改"),
    ("46b", "用户测试记录", "变更涉及到影响用户使用时", "测试人员", "", "重新修改"),
    ("47", "用户培训方案", "变更涉及到影响用户使用时", "产品经理", "", "重新修改"),
    ("48", "缺陷评估报告", "版本有发现缺陷时", "测试人员", "", "重新修改"),
    ("51", "配置状态报告", "每个版本", "配置管理员", "和变更申请单识别到的文件清单一致", "重新修改"),
    ("52", "配置审计报告", "每个版本", "测试人员", "", "重新修改"),
    ("53", "设计和开发评审报告（确认）", "每个版本", "项目经理", "", "重新修改"),
    ("62", "变更执行单", "每个版本", "项目经理", "", "重新修改"),
    ("70", "变更历史记录", "每个版本", "项目经理", "", "追加记录"),
]

# 国内获证：无用户接口需求/设计规范，其余与 CE 表对应
_CHANGE_NMPA_ROWS: list[tuple] = [
    row
    for row in _CHANGE_CE_ROWS
    if row[1] not in {"用户接口需求规范", "用户接口设计规范"}
]

YY_CHAPTER_CHANGE_ARCHIVE_CE = _tasks_from_rows("chg_ce", CHAPTER_CHANGE, _CHANGE_CE_ROWS)
YY_CHAPTER_CHANGE_ARCHIVE_NMPA = _tasks_from_rows(
    "chg_nmpa", CHAPTER_CHANGE, _CHANGE_NMPA_ROWS
)
# 兼容旧名：未指定注册路径时用 CE 表
YY_CHAPTER_CHANGE_ARCHIVE = YY_CHAPTER_CHANGE_ARCHIVE_CE

_DEFECT_ROWS: list[tuple] = [
    ("34", "缺陷记录表", "每个版本", "测试人员", "禅道导出excel归档，模版参照体系文件模板", "重新修改"),
    ("48", "缺陷评估报告", "每个版本", "测试人员", "", "重新修改"),
    ("15b", "源代码", "每个版本", "研发经理", "", "重新修改"),
    ("42", "镜像包", "每个版本", "研发经理", "", "重新修改"),
    ("51", "配置状态报告", "每个版本", "配置管理员", "", "重新修改"),
    ("52", "配置审计报告", "每个版本", "测试人员", "", "重新修改"),
    ("70", "变更历史记录", "每个版本", "项目经理", "", "追加记录"),
]
YY_CHAPTER_DEFECT_ARCHIVE = _tasks_from_rows("def", CHAPTER_DEFECT, _DEFECT_ROWS)

_RELEASE_ROWS: list[tuple] = [
    ("57", "软件发布验证方案", "变更涉及到发布工艺流程时", "发布专员", "", "重新修改"),
    ("58", "软件发布验证报告", "变更涉及到发布工艺流程时", "发布专员", "更新验证记录", "重新修改"),
    ("59", "设计开发转换计划", "变更涉及到发布工艺流程时", "发布专员", "", "重新修改"),
    ("60", "设计开发转换方案", "变更涉及到发布工艺流程时", "发布专员", "涉及部门、文件清单、日期更新", "重新修改"),
    ("61", "设计和开发转换报告", "变更涉及到发布工艺流程时", "发布专员", "更新版本号、时间", "重新修改"),
    ("63", "发布计划", "每个版本", "发布专员", "", "重新修改"),
    ("66", "发布记录", "每个版本", "发布专员", "", "重新修改"),
    ("72", "过程检验记录", "每个版本", "发布专员", "", "重新修改"),
    ("67", "成品检验记录", "每个版本", "QC", "", "重新修改"),
    ("73", "成品检验报告", "每个版本", "发布专员", "", "重新修改"),
    ("68", "合格证", "每个版本", "QC", "内容和其他文件保持一致", "重新修改"),
    ("69", "产品放行申请单", "每个版本", "QC", "", "重新修改"),
]
YY_CHAPTER_RELEASE_ARCHIVE = _tasks_from_rows("rel", CHAPTER_RELEASE, _RELEASE_ROWS)

# 系统追溯（X/Y）：正文要求禅道或《软件可追溯性分析报告》
YY_TRACEABILITY_ARCHIVE = [
    _archive_task(
        prefix="tr",
        seq="trace",
        file_name="软件可追溯性分析报告",
        frequency="版本号X/Y位变更时",
        author="产品经理",
        chapter="系统追溯",
        caution="日常软件变更需说明需求、开发、测试对应关系，通过禅道管理或者填写本报告",
    )
]

# QP7.3.9 — 仅 X/Y
CHANGE_PROCESS_CATALOG: list[dict[str, Any]] = [
    _task(
        task_key="qp_change_request",
        file_name="变更申请单（QR-QP7.3.9-01）",
        task_type="变更控制流程",
        author="变更发起人",
        belonging_module="全员",
        phase_offset_days=-11,
        archive_frequency="",
        reason="QP7.3.9：提出设计变更申请并分配 CR 编号。",
        rule_ref="QP7.3.9",
        process_branch=PROCESS_BRANCH_CHANGE,
    ),
    _task(
        task_key="qp_ccb_precheck",
        file_name="变更预评审",
        task_type="变更控制流程",
        author="CCB协调人",
        belonging_module="全员",
        phase_offset_days=-10,
        archive_frequency="",
        reason="QP7.3.9：CCB 协调人对变更申请做预评审。",
        rule_ref="QP7.3.9",
        process_branch=PROCESS_BRANCH_CHANGE,
    ),
    _task(
        task_key="qp_ccb_decision",
        file_name="CCB变更评审决策",
        task_type="变更控制流程",
        author="CCB",
        belonging_module="全员",
        phase_offset_days=-9,
        archive_frequency="",
        reason="QP7.3.9：CCB 评审并指定变更负责人。",
        rule_ref="QP7.3.9",
        process_branch=PROCESS_BRANCH_CHANGE,
    ),
    _task(
        task_key="qp_change_plan",
        file_name="变更计划（设计变更策划）",
        task_type="变更控制流程",
        author="变更负责人",
        belonging_module="开发",
        phase_offset_days=-8,
        archive_frequency="",
        reason="QP7.3.9：变更计划明确措施、验证确认与风险评价。",
        rule_ref="QP7.3.9",
        process_branch=PROCESS_BRANCH_CHANGE,
    ),
    _task(
        task_key="qp_license_change",
        file_name="重大变更许可事项评估与申报",
        task_type="变更控制流程",
        author="注册工程师",
        belonging_module="全员",
        phase_offset_days=-12,
        archive_frequency="",
        reason="QP7.3.9：X 位重大变更需评估并申报/备案。",
        rule_ref="QP7.3.9",
        process_branch=PROCESS_BRANCH_CHANGE,
    ),
    _task(
        task_key="qp_change_exec",
        file_name="变更执行单（QR-QP7.3.9-02）",
        task_type="变更控制流程",
        author="变更负责人",
        belonging_module="全员",
        phase_offset_days=-3,
        archive_frequency="",
        reason="QP7.3.9：批准后下达并跟踪实施。",
        rule_ref="QP7.3.9",
        process_branch=PROCESS_BRANCH_CHANGE,
    ),
    _task(
        task_key="qp_change_close",
        file_name="变更关闭确认",
        task_type="变更控制流程",
        author="CCB协调人",
        belonging_module="全员",
        phase_offset_days=1,
        archive_frequency="",
        reason="QP7.3.9：CCB 批准变更生效并关闭。",
        rule_ref="QP7.3.9",
        process_branch=PROCESS_BRANCH_CHANGE,
    ),
]

# SMP7.3-05 — 仅 Z（B 不走缺陷）
DEFECT_PROCESS_CATALOG: list[dict[str, Any]] = [
    _task(
        task_key="smp_defect_submit",
        file_name="缺陷提交（缺陷管理申请）",
        task_type="缺陷管理流程",
        author="测试人员",
        belonging_module="测试",
        phase_offset_days=-8,
        archive_frequency="",
        reason="SMP7.3-05 / YY-IW-020《开发发起变更》：测试在禅道提交 bug。",
        rule_ref="SMP7.3-05",
        process_branch=PROCESS_BRANCH_DEFECT,
    ),
    _task(
        task_key="smp_defect_assign",
        file_name="缺陷指派与确认",
        task_type="缺陷管理流程",
        author="CCB/项目经理",
        belonging_module="全员",
        phase_offset_days=-7,
        archive_frequency="",
        reason="SMP7.3-05：确认后指派研发处理。",
        rule_ref="SMP7.3-05",
        process_branch=PROCESS_BRANCH_DEFECT,
    ),
    _task(
        task_key="smp_defect_resolve",
        file_name="缺陷解决",
        task_type="缺陷管理流程",
        author="研发人员",
        belonging_module="开发",
        phase_offset_days=-4,
        archive_frequency="",
        reason="SMP7.3-05：开发修复 bug 并填写解决信息。",
        rule_ref="SMP7.3-05",
        process_branch=PROCESS_BRANCH_DEFECT,
    ),
    _task(
        task_key="smp_defect_verify",
        file_name="缺陷验证",
        task_type="缺陷管理流程",
        author="测试人员",
        belonging_module="测试",
        phase_offset_days=-2,
        archive_frequency="",
        reason="SMP7.3-05：测试验证关闭前的验证。",
        rule_ref="SMP7.3-05",
        process_branch=PROCESS_BRANCH_DEFECT,
    ),
    _task(
        task_key="smp_defect_close",
        file_name="缺陷关闭",
        task_type="缺陷管理流程",
        author="CCB",
        belonging_module="全员",
        phase_offset_days=-1,
        archive_frequency="",
        reason="SMP7.3-05：验证充分后关闭缺陷。",
        rule_ref="SMP7.3-05",
        process_branch=PROCESS_BRANCH_DEFECT,
    ),
]

# 生产发布流程：仅制度「要求」中、且不与发布归档表重复的动作
RELEASE_PROCESS_CATALOG: list[dict[str, Any]] = [
    _task(
        task_key="rel_sign_release_note",
        file_name="软件发布说明（会签）",
        task_type="生产发布流程",
        author="产品负责人/开发负责人/测试负责人/项目经理",
        belonging_module="全员",
        phase_offset_days=0,
        archive_frequency="每个版本",
        reason="YY-IW-020「要求」：上线前填写打印《软件发布说明》并签字确认。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_RELEASE,
        process_branch=PROCESS_BRANCH_RELEASE,
    ),
    _task(
        task_key="rel_post_verify",
        file_name="发布后测试验证",
        task_type="生产发布流程",
        author="测试人员",
        belonging_module="测试",
        phase_offset_days=1,
        archive_frequency="每个版本",
        reason="YY-IW-020「要求」：发布成功后，测试人员进行测试验证。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_RELEASE,
        process_branch=PROCESS_BRANCH_RELEASE,
    ),
]


CHAPTER_HEADING_BITS = {
    CHAPTER_CHANGE: frozenset({"X", "Y"}),
    "系统追溯": frozenset({"X", "Y"}),
    CHAPTER_DEFECT: frozenset({"X", "Y", "Z"}),
    CHAPTER_RELEASE: frozenset({"X", "Y", "Z", "B"}),
}


def _active_heading_bits() -> dict[str, frozenset]:
    merged = dict(CHAPTER_HEADING_BITS)
    extra = (_RULE_OVERLAY.get("headingBits") or {}) if _RULE_OVERLAY else {}
    merged.update(extra)
    return merged


def _active_catalog(key: str, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cats = (_RULE_OVERLAY.get("catalogs") or {}) if _RULE_OVERLAY else {}
    rows = cats.get(key) or fallback
    return [dict(x) for x in rows]


def archive_market_for_country(registration_country: str) -> str:
    """CE获证表 vs 国内获证表。"""
    key = (registration_country or "").strip().casefold()
    if any(x in key for x in ("中国", "china", "cn", "nmpa", "国内")):
        return "nmpa"
    return "ce"


def change_archive_for_market(market: str) -> list[dict[str, Any]]:
    if (market or "").strip().lower() == "nmpa":
        return _active_catalog("changeNmpa", YY_CHAPTER_CHANGE_ARCHIVE_NMPA)
    return _active_catalog("changeCe", YY_CHAPTER_CHANGE_ARCHIVE_CE)


def resolve_chapter_route(
    dominant_change: str, *, archive_market: str = "ce"
) -> dict[str, Any]:
    """版本主导位 → 主章节 + 流程分支 + 适用章节列表。"""
    bit = (dominant_change or "").strip().upper()
    market_label = "国内获证" if archive_market == "nmpa" else "CE获证"
    heading_bits = _active_heading_bits()
    applicable = [
        name for name, bits in heading_bits.items() if bit in bits
    ]
    if bit in {"X", "Y"}:
        primary = CHAPTER_CHANGE
        branch = PROCESS_BRANCH_CHANGE
        label = f"{CHAPTER_CHANGE}（{market_label}，X/Y）+ 变更控制（QP7.3.9）"
    elif bit == "Z":
        primary = CHAPTER_DEFECT
        branch = PROCESS_BRANCH_DEFECT
        label = f"{CHAPTER_DEFECT}（X/Y/Z）+ 缺陷管理（SMP7.3-05）"
    elif bit == "B":
        primary = CHAPTER_RELEASE
        branch = PROCESS_BRANCH_RELEASE
        label = f"{CHAPTER_RELEASE}（X/Y/Z/B，不走缺陷）"
    else:
        primary = CHAPTER_CHANGE
        branch = PROCESS_BRANCH_CHANGE
        label = CHAPTER_CHANGE
    return {
        "chapter": primary,
        "processBranch": branch,
        "label": label,
        "applicableChapters": applicable,
        "archiveMarket": archive_market,
        "archiveMarketLabel": market_label,
        "dominantChange": bit,
    }


def process_branch_label(branch: str) -> str:
    mapping = {
        PROCESS_BRANCH_CHANGE: "变更控制（QP7.3.9）",
        PROCESS_BRANCH_DEFECT: "缺陷管理（SMP7.3-05）",
        PROCESS_BRANCH_RELEASE: "生产发布（YY-IW-020）",
    }
    return mapping.get(branch, branch or "-")


def archive_frequency_matches(frequency: str, dominant: str) -> bool:
    """章节内：归档频率 ↔ 版本位。"""
    freq = (frequency or "").strip()
    bit = (dominant or "").strip().upper()
    if not freq:
        return True
    if freq == "每个版本":
        return bit in {"X", "Y", "Z", "B"}
    if "X/Y" in freq or "X／Y" in freq:
        return bit in {"X", "Y"}
    if "发现缺陷" in freq:
        return bit == "Z"
    # 事件驱动（涉及原材料/用户使用/发布工艺等）自动生成阶段不触发
    return False


def _filter_archive_by_frequency(
    rows: list[dict[str, Any]], dominant: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if archive_frequency_matches(str(row.get("archiveFrequency") or ""), dominant):
            item = dict(row)
            item["triggers"] = {dominant}
            out.append(item)
    return out


def _process_catalog_for_branch(branch: str, dominant: str) -> list[dict[str, Any]]:
    if branch == PROCESS_BRANCH_DEFECT:
        src = DEFECT_PROCESS_CATALOG
    elif branch == PROCESS_BRANCH_RELEASE:
        hints = (_RULE_OVERLAY.get("processHints") or {}) if _RULE_OVERLAY else {}
        src = []
        # 无 overlay 时按现行内嵌制度（V2.2「要求」已删除会签段）不生成额外发布动作
        if hints.get("releaseSignoff"):
            src.extend(
                x for x in RELEASE_PROCESS_CATALOG if x.get("taskKey") == "rel_sign_release_note"
            )
        if hints.get("postReleaseVerify"):
            src.extend(
                x for x in RELEASE_PROCESS_CATALOG if x.get("taskKey") == "rel_post_verify"
            )
    else:
        src = CHANGE_PROCESS_CATALOG
    out: list[dict[str, Any]] = []
    for row in src:
        # X 专属重大变更
        if row.get("taskKey") == "qp_license_change" and dominant != "X":
            continue
        item = dict(row)
        item["triggers"] = {dominant}
        out.append(item)
    return out


def catalogs_for_dominant(
    dominant: str, *, registration_country: str = ""
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """先按章节标题适用位，主章节优先，再频率，再叠加流程。"""
    market = archive_market_for_country(registration_country)
    route = resolve_chapter_route(dominant, archive_market=market)
    bit = (dominant or "").strip().upper()
    heading_bits = _active_heading_bits()
    sources: list[tuple[str, list[dict[str, Any]]]] = []
    if bit in heading_bits.get(CHAPTER_CHANGE, frozenset()):
        sources.append((CHAPTER_CHANGE, change_archive_for_market(market)))
    if bit in heading_bits.get("系统追溯", frozenset()):
        sources.append(("系统追溯", _active_catalog("traceability", YY_TRACEABILITY_ARCHIVE)))
    if bit in heading_bits.get(CHAPTER_DEFECT, frozenset()):
        sources.append((CHAPTER_DEFECT, _active_catalog("defect", YY_CHAPTER_DEFECT_ARCHIVE)))
    if bit in heading_bits.get(CHAPTER_RELEASE, frozenset()):
        sources.append((CHAPTER_RELEASE, _active_catalog("release", YY_CHAPTER_RELEASE_ARCHIVE)))

    primary = route["chapter"]
    sources.sort(key=lambda x: 0 if x[0] == primary else 1)

    tasks: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for _chapter_name, rows in sources:
        for item in _filter_archive_by_frequency(rows, bit):
            name_key = str(item.get("fileName") or "").strip().casefold()
            if not name_key or name_key in seen_names:
                continue
            seen_names.add(name_key)
            tasks.append(item)
    tasks.extend(_process_catalog_for_branch(route["processBranch"], bit))
    route["matchedFileCount"] = len(tasks)
    return route, tasks


def load_version_task_rules(*, mode: Optional[str] = None) -> dict[str, Any]:
    """规则加载入口。优先 overlay（知识库/本地制度），否则内嵌 V2.2。"""
    overlay = get_rule_overlay()
    if overlay:
        return {
            "mode": overlay.get("matchedBy") or "knowledge_base",
            "ruleDocFiles": RULE_DOC_FILES,
            "ruleBasis": RULE_BASIS,
            "ruleSource": overlay.get("ruleSource") or "YY-IW-020",
            "sourceFile": overlay.get("sourceFile") or "",
            "sourceVersion": overlay.get("sourceVersion") or "",
            "matchSteps": MATCH_STEPS,
        }
    active = (mode or RULES_MODE or "knowledge_base").strip().lower()
    if active == "knowledge_base":
        active = "embedded"
    return {
        "mode": active,
        "ruleDocFiles": RULE_DOC_FILES,
        "ruleBasis": RULE_BASIS,
        "ruleSource": "YY-IW-020 V2.2 归档表（内嵌回退，逐字文件名）",
        "sourceFile": RULE_DOC_FILES.get("yy_iw_020") or "",
        "sourceVersion": "V2.2",
        "matchSteps": MATCH_STEPS,
    }


# 兼容旧名
def resolve_process_branch(dominant_change: str) -> str:
    return resolve_chapter_route(dominant_change)["processBranch"]
