"""
清空考试训练中心在 aiword 库中的「个人作答/活动」镜像，不删题目（题目在 aicheckword）。

默认删除：
  exam_center_activity_details → exam_center_activities
  exam_grading_jobs → exam_attempt_items → exam_attempts

可选（会破坏老师已下发的任务镜像，慎用）:
  --purge-assignments  同时删除 exam_center_assignment_audience /
                        exam_center_assignment_extras / exam_center_assignments

可选（本地录题/复审任务快照）:
  --purge-local-jobs   删除 exam_bank_ingest_jobs、exam_set_review_jobs

题库本体在 aicheckword；个人错题本数据主要在 aicheckword 的 quiz_wrongbook 等表，
请另运行 aicheckword/scripts/purge_quiz_personal_records.py。

用法（在 aiword 项目根目录）:
  python scripts/purge_exam_center_personal_records.py --dry-run
  python scripts/purge_exam_center_personal_records.py --yes
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="清空考试中心个人活动/作答镜像（aiword 库）")
    parser.add_argument("--dry-run", action="store_true", help="只打印行数，不写库")
    parser.add_argument("--yes", action="store_true", help="跳过交互确认")
    parser.add_argument(
        "--purge-assignments",
        action="store_true",
        help="同时删除本地 assignment 镜像及受众/扩展表（慎用）",
    )
    parser.add_argument(
        "--purge-local-jobs",
        action="store_true",
        help="同时删除 exam_bank_ingest_jobs、exam_set_review_jobs 本地任务记录",
    )
    args = parser.parse_args()

    logging.getLogger("webapp.app_settings").setLevel(logging.ERROR)

    from sqlalchemy import delete

    from webapp import create_app, db
    from webapp.models import (
        ExamBankIngestJob,
        ExamCenterActivity,
        ExamCenterActivityDetail,
        ExamCenterAssignment,
        ExamCenterAssignmentAudience,
        ExamCenterAssignmentExtra,
        ExamAttempt,
        ExamAttemptItem,
        ExamGradingJob,
        ExamSetReviewJob,
    )

    app = create_app()

    def _count(model) -> int:
        return int(model.query.count())

    targets: list[tuple[str, type]] = [
        ("exam_center_activity_details", ExamCenterActivityDetail),
        ("exam_center_activities", ExamCenterActivity),
        ("exam_grading_jobs", ExamGradingJob),
        ("exam_attempt_items", ExamAttemptItem),
        ("exam_attempts", ExamAttempt),
    ]
    if args.purge_assignments:
        targets.extend(
            [
                ("exam_center_assignment_audience", ExamCenterAssignmentAudience),
                ("exam_center_assignment_extras", ExamCenterAssignmentExtra),
                ("exam_center_assignments", ExamCenterAssignment),
            ]
        )
    if args.purge_local_jobs:
        targets.extend(
            [
                ("exam_bank_ingest_jobs", ExamBankIngestJob),
                ("exam_set_review_jobs", ExamSetReviewJob),
            ]
        )

    with app.app_context():
        report: list[tuple[str, int]] = []
        for label, model in targets:
            report.append((label, _count(model)))

        for label, n in report:
            print(f"  {label}: rows={n}")

        if args.dry_run:
            print("[dry-run] 未修改数据库")
            return

        total = sum(n for _, n in report)
        if total == 0:
            print("[ok] 无数据需清空")
            return

        if not args.yes:
            extra = []
            if args.purge_assignments:
                extra.append("含 assignment 镜像")
            if args.purge_local_jobs:
                extra.append("含本地 ingest/review 任务")
            hint = "、".join(extra) if extra else "仅活动与 attempt"
            s = input(f"将按顺序删除上述表（{hint}），输入 YES 继续: ")
            if (s or "").strip() != "YES":
                print("已取消")
                return

        # 顺序与 targets 一致：先子后父；单次提交避免中途失败留下半套数据
        try:
            for label, model in targets:
                r = db.session.execute(delete(model))
                rc = getattr(r, "rowcount", None)
                print(f"[ok] DELETE {label} rowcount={rc}")
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        print("[done] aiword 侧考试中心个人镜像已清空")


if __name__ == "__main__":
    main()
