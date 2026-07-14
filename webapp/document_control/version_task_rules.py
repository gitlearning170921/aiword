"""版本任务清单规则（调试阶段内嵌自 docs/rules；后续改为从知识库拉取）。

匹配顺序（YY-IW-020）：
1) 按版本主导变更位匹配章节大标题
2) 在该章节归档表内，再按归档频率匹配版本位
3) 流程文件：X/Y→QP7.3.9；Z→SMP7.3-05；B→仅生产发布（不走缺陷）
"""

from __future__ import annotations

from typing import Any, Optional

# 来源文件（训练进知识库后，用同名文档刷新规则）
RULE_DOC_FILES = {
    "yy_iw_020": "YY -IW-020 医疗软件质量合规管理制度（V2.1）.docx",
    "qp_739": "QP 7.3.9 变更控制程序（A2）.docx",
    "smp_7305": "SMP 7.3-05 缺陷管理制度（A1）.docx",
}

CHAPTER_CHANGE = "软件变更管理"
CHAPTER_DEFECT = "缺陷管理"
CHAPTER_RELEASE = "软件生产/发布管理"

PROCESS_BRANCH_CHANGE = "change"
PROCESS_BRANCH_DEFECT = "defect"
PROCESS_BRANCH_RELEASE = "release"

RULES_MODE = "embedded"  # 后续改为 "knowledge_base"


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


# ---------------------------------------------------------------------------
# YY-IW-020 · 软件变更管理（章节归档表，产品/开发发起变更共用核心清单）
# ---------------------------------------------------------------------------
YY_CHAPTER_CHANGE_ARCHIVE: list[dict[str, Any]] = [
    _task(
        task_key="change_request",
        file_name="变更申请单",
        task_type="归档文件",
        author="项目经理",
        belonging_module="全员",
        phase_offset_days=-10,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件变更管理》：每个版本重新修改，识别需归档文件清单。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="dev_plan",
        file_name="软件开发计划",
        task_type="归档文件",
        author="项目经理",
        belonging_module="全员",
        phase_offset_days=-9,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件变更管理》：每个版本更新文件清单与时间。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="design_review_plan",
        file_name="设计和开发评审报告（策划）",
        task_type="归档文件",
        author="项目经理",
        belonging_module="全员",
        phase_offset_days=-9,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件变更管理》：每个版本重新修改。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="srs",
        file_name="软件需求规范",
        task_type="归档文件",
        author="产品经理",
        belonging_module="产品",
        phase_offset_days=-8,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件变更管理》：每个版本重新修改。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="arch",
        file_name="架构设计规范",
        task_type="归档文件",
        author="研发人员",
        belonging_module="开发",
        phase_offset_days=-7,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件变更管理》：每个版本重新修改。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="detail_design",
        file_name="详细设计规范",
        task_type="归档文件",
        author="研发人员",
        belonging_module="开发",
        phase_offset_days=-6,
        archive_frequency="版本号X/Y位变更时",
        reason="YY-IW-020《软件变更管理》：版本号 X/Y 位变更时。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="unit_test",
        file_name="单元测试方案/报告/记录",
        task_type="归档文件",
        author="研发人员",
        belonging_module="开发",
        phase_offset_days=-5,
        archive_frequency="版本号X/Y位变更时",
        reason="YY-IW-020《软件变更管理》：版本号 X/Y 位变更时。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="fg_insp_proc",
        file_name="成品检验规程",
        task_type="归档文件",
        author="测试人员",
        belonging_module="测试",
        phase_offset_days=-4,
        archive_frequency="版本号X/Y位变更时",
        reason="YY-IW-020《软件变更管理》：版本号 X/Y 位变更时很有可能需要更新。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="smoke_report",
        file_name="软件冒烟测试报告",
        task_type="归档文件",
        author="开发负责人",
        belonging_module="开发",
        phase_offset_days=-3,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件变更管理》：每个版本；转测前输出冒烟报告。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="sys_test_plan",
        file_name="系统测试方案",
        task_type="归档文件",
        author="测试人员",
        belonging_module="测试",
        phase_offset_days=-6,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件变更管理》：每个版本重新修改。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="sys_test_report",
        file_name="系统测试报告/记录",
        task_type="归档文件",
        author="测试人员",
        belonging_module="测试",
        phase_offset_days=-2,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件变更管理》：每个版本重新修改。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="defect_log_change",
        file_name="缺陷记录表",
        task_type="归档文件",
        author="测试人员",
        belonging_module="测试",
        phase_offset_days=-1,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件变更管理》：每个版本归档缺陷记录。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="release_note_change",
        file_name="软件发布说明",
        task_type="归档文件",
        author="研发人员",
        belonging_module="开发",
        phase_offset_days=0,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件变更管理》：每个版本。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="cfg_status_change",
        file_name="配置状态报告",
        task_type="归档文件",
        author="配置管理员",
        belonging_module="全员",
        phase_offset_days=2,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件变更管理》：每个版本；与变更申请单识别清单一致。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
    _task(
        task_key="change_history",
        file_name="变更历史记录",
        task_type="归档文件",
        author="项目经理",
        belonging_module="全员",
        phase_offset_days=2,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件变更管理》：每个版本追加记录。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_CHANGE,
    ),
]

# ---------------------------------------------------------------------------
# YY-IW-020 · 缺陷管理（开发发起变更走缺陷流程，归档参照该章节）
# ---------------------------------------------------------------------------
YY_CHAPTER_DEFECT_ARCHIVE: list[dict[str, Any]] = [
    _task(
        task_key="change_request_defect",
        file_name="变更申请单",
        task_type="归档文件",
        author="项目经理",
        belonging_module="全员",
        phase_offset_days=-10,
        archive_frequency="每个版本",
        reason="YY-IW-020《缺陷管理》：每个版本识别归档清单。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_DEFECT,
    ),
    _task(
        task_key="defect_log",
        file_name="缺陷记录表",
        task_type="归档文件",
        author="测试人员",
        belonging_module="测试",
        phase_offset_days=-1,
        archive_frequency="每个版本",
        reason="YY-IW-020《缺陷管理》：每个版本禅道导出归档。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_DEFECT,
    ),
    _task(
        task_key="defect_assessment",
        file_name="缺陷评估报告",
        task_type="归档文件",
        author="测试人员",
        belonging_module="测试",
        phase_offset_days=-1,
        archive_frequency="每个版本",
        reason="YY-IW-020《缺陷管理》：缺陷类版本归档评估报告。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_DEFECT,
    ),
    _task(
        task_key="source_code_defect",
        file_name="源代码",
        task_type="归档文件",
        author="研发经理",
        belonging_module="开发",
        phase_offset_days=-2,
        archive_frequency="每个版本",
        reason="YY-IW-020《缺陷管理》：每个版本。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_DEFECT,
    ),
    _task(
        task_key="image_pkg_defect",
        file_name="镜像包",
        task_type="归档文件",
        author="研发经理",
        belonging_module="开发",
        phase_offset_days=-1,
        archive_frequency="每个版本",
        reason="YY-IW-020《缺陷管理》：每个版本。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_DEFECT,
    ),
    _task(
        task_key="cfg_status_defect",
        file_name="配置状态报告",
        task_type="归档文件",
        author="配置管理员",
        belonging_module="全员",
        phase_offset_days=2,
        archive_frequency="每个版本",
        reason="YY-IW-020《缺陷管理》：每个版本。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_DEFECT,
    ),
    _task(
        task_key="cfg_audit_defect",
        file_name="配置审计报告",
        task_type="归档文件",
        author="质量人员",
        belonging_module="全员",
        phase_offset_days=2,
        archive_frequency="每个版本",
        reason="YY-IW-020《缺陷管理》：每个版本。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_DEFECT,
    ),
    _task(
        task_key="change_history_defect",
        file_name="变更历史记录",
        task_type="归档文件",
        author="项目经理",
        belonging_module="全员",
        phase_offset_days=2,
        archive_frequency="每个版本",
        reason="YY-IW-020《缺陷管理》：每个版本追加记录。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_DEFECT,
    ),
]

# ---------------------------------------------------------------------------
# YY-IW-020 · 软件生产/发布管理（B 位仅走本章节，不走缺陷）
# ---------------------------------------------------------------------------
YY_CHAPTER_RELEASE_ARCHIVE: list[dict[str, Any]] = [
    _task(
        task_key="change_exec_release",
        file_name="变更执行单",
        task_type="归档文件",
        author="项目经理",
        belonging_module="全员",
        phase_offset_days=-3,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件生产/发布管理》：每个版本。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_RELEASE,
    ),
    _task(
        task_key="release_plan",
        file_name="发布计划",
        task_type="归档文件",
        author="发布专员",
        belonging_module="开发",
        phase_offset_days=-2,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件生产/发布管理》：每个版本。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_RELEASE,
    ),
    _task(
        task_key="release_note",
        file_name="软件发布说明",
        task_type="归档文件",
        author="研发人员",
        belonging_module="开发",
        phase_offset_days=-1,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件生产/发布管理》：上线前签字确认。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_RELEASE,
    ),
    _task(
        task_key="release_record",
        file_name="发布记录",
        task_type="归档文件",
        author="发布专员",
        belonging_module="开发",
        phase_offset_days=0,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件生产/发布管理》：每个版本。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_RELEASE,
    ),
    _task(
        task_key="fg_insp_record",
        file_name="成品检验记录",
        task_type="归档文件",
        author="QC",
        belonging_module="测试",
        phase_offset_days=1,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件生产/发布管理》：QC 检验放行。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_RELEASE,
    ),
    _task(
        task_key="certificate",
        file_name="合格证",
        task_type="归档文件",
        author="QC",
        belonging_module="测试",
        phase_offset_days=1,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件生产/发布管理》：内容与其他文件保持一致。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_RELEASE,
    ),
    _task(
        task_key="release_appl",
        file_name="产品放行申请单",
        task_type="归档文件",
        author="QC",
        belonging_module="全员",
        phase_offset_days=1,
        archive_frequency="每个版本",
        reason="YY-IW-020《软件生产/发布管理》：每个版本。",
        rule_ref="YY-IW-020",
        chapter=CHAPTER_RELEASE,
    ),
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

# 生产发布流程任务（B 位；对齐 YY-IW-020 发布描述）
RELEASE_PROCESS_CATALOG: list[dict[str, Any]] = [
    _task(
        task_key="rel_sign_release_note",
        file_name="软件发布说明会签",
        task_type="生产发布流程",
        author="产品/开发/测试/项目经理",
        belonging_module="全员",
        phase_offset_days=-2,
        archive_frequency="",
        reason="YY-IW-020《软件生产/发布管理》：上线前填写发布说明并签字确认。",
        rule_ref="YY-IW-020",
        process_branch=PROCESS_BRANCH_RELEASE,
    ),
    _task(
        task_key="rel_publish_record",
        file_name="正式发布与发布记录",
        task_type="生产发布流程",
        author="发布专员",
        belonging_module="开发",
        phase_offset_days=-1,
        archive_frequency="",
        reason="YY-IW-020：正式发布时填写《发布记录》。",
        rule_ref="YY-IW-020",
        process_branch=PROCESS_BRANCH_RELEASE,
    ),
    _task(
        task_key="rel_qc_inspect",
        file_name="QC检验与检验记录",
        task_type="生产发布流程",
        author="QC",
        belonging_module="测试",
        phase_offset_days=0,
        archive_frequency="",
        reason="YY-IW-020：QC 检验通过后签署检验记录，检查发布结果。",
        rule_ref="YY-IW-020",
        process_branch=PROCESS_BRANCH_RELEASE,
    ),
    _task(
        task_key="rel_product_release",
        file_name="产品放行申请",
        task_type="生产发布流程",
        author="QC",
        belonging_module="全员",
        phase_offset_days=1,
        archive_frequency="",
        reason="YY-IW-020《软件生产/发布管理》：产品放行。",
        rule_ref="YY-IW-020",
        process_branch=PROCESS_BRANCH_RELEASE,
    ),
    _task(
        task_key="rel_post_verify",
        file_name="发布后测试验证",
        task_type="生产发布流程",
        author="测试人员",
        belonging_module="测试",
        phase_offset_days=1,
        archive_frequency="",
        reason="YY-IW-020：发布成功后测试人员进行测试验证。",
        rule_ref="YY-IW-020",
        process_branch=PROCESS_BRANCH_RELEASE,
    ),
]


def resolve_chapter_route(dominant_change: str) -> dict[str, str]:
    """版本主导位 → 章节大标题 + 流程分支。"""
    bit = (dominant_change or "").strip().upper()
    if bit in {"X", "Y"}:
        return {
            "chapter": CHAPTER_CHANGE,
            "processBranch": PROCESS_BRANCH_CHANGE,
            "label": f"{CHAPTER_CHANGE} + 变更控制（QP7.3.9）",
        }
    if bit == "Z":
        return {
            "chapter": CHAPTER_DEFECT,
            "processBranch": PROCESS_BRANCH_DEFECT,
            "label": f"{CHAPTER_DEFECT} + 缺陷管理（SMP7.3-05）",
        }
    if bit == "B":
        return {
            "chapter": CHAPTER_RELEASE,
            "processBranch": PROCESS_BRANCH_RELEASE,
            "label": f"{CHAPTER_RELEASE}（仅生产发布，不走缺陷）",
        }
    return {
        "chapter": CHAPTER_CHANGE,
        "processBranch": PROCESS_BRANCH_CHANGE,
        "label": CHAPTER_CHANGE,
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
        src = RELEASE_PROCESS_CATALOG
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


def catalogs_for_dominant(dominant: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """先章节，再频率，再叠加流程任务。"""
    route = resolve_chapter_route(dominant)
    chapter = route["chapter"]
    branch = route["processBranch"]
    if chapter == CHAPTER_DEFECT:
        archive = YY_CHAPTER_DEFECT_ARCHIVE
    elif chapter == CHAPTER_RELEASE:
        archive = YY_CHAPTER_RELEASE_ARCHIVE
    else:
        archive = YY_CHAPTER_CHANGE_ARCHIVE
    tasks = _filter_archive_by_frequency(archive, dominant)
    tasks.extend(_process_catalog_for_branch(branch, dominant))
    return route, tasks


def load_version_task_rules(*, mode: Optional[str] = None) -> dict[str, Any]:
    """规则加载入口。调试用 embedded；后续 mode=knowledge_base 从知识库刷新。"""
    active = (mode or RULES_MODE or "embedded").strip().lower()
    if active == "knowledge_base":
        # 预留：从 aicheckword 知识库按 RULE_DOC_FILES 拉取并重建章节/频率表
        # 当前回退内嵌，避免联调阻断
        active = "embedded"
    return {
        "mode": active,
        "ruleDocFiles": RULE_DOC_FILES,
        "ruleBasis": (
            "①YY-IW-020 先匹配章节大标题（软件变更管理 / 缺陷管理 / 软件生产/发布管理）；"
            "②章节内再按归档频率匹配版本位；"
            "③X/Y→QP7.3.9；Z→SMP7.3-05；B→仅生产发布流程（不走缺陷）。"
        ),
        "ruleSource": (
            "YY-IW-020章节匹配 → "
            "X/Y:变更控制(QP7.3.9) / Z:缺陷管理(SMP7.3-05) / B:生产发布"
        ),
    }


# 兼容旧名
def resolve_process_branch(dominant_change: str) -> str:
    return resolve_chapter_route(dominant_change)["processBranch"]
