"""
删除考试训练中心「烟测 / April 占位」等在本地表中残留的任务镜像，避免因上游不可用而单靠本地兜底
误展示无法再开考的 assignment。

默认匹配（可叠加 --dry-run）：
  - exam_center_assignments.title 包含「四月」
  - 标题或 set_id 与联调脚本 exam_center_smoke 一致（set-100、【测试】Smoke 等）

运行（项目根 aiword）:
  python scripts/purge_exam_assignments_smoke.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, or_

from webapp import create_app, db
from webapp.models import ExamCenterActivity, ExamCenterActivityDetail, ExamCenterAssignment


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只打印将要删除的行，不写库")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        q = ExamCenterAssignment.query.filter(
            or_(
                ExamCenterAssignment.title.contains("四月"),
                ExamCenterAssignment.title.contains("Smoke"),
                ExamCenterAssignment.title.contains("【测试】"),
                ExamCenterAssignment.set_id == "set-100",
            )
        )
        rows = q.all()
        aids = [str(r.assignment_id or "").strip() for r in rows if r and str(r.assignment_id or "").strip()]
        print(f"matched exam_center_assignments: {len(rows)}")
        for r in rows:
            print(f"  assignment_id={r.assignment_id!r} title={r.title!r} set_id={r.set_id!r}")

        act_ids: list[str] = []
        if aids:
            acts = ExamCenterActivity.query.filter(ExamCenterActivity.assignment_id.in_(aids)).all()
            act_ids = [str(a.id) for a in acts if getattr(a, "id", None)]
            print(f"related exam_center_activities: {len(act_ids)}")

        if args.dry_run:
            print("[dry-run] no changes committed")
            return

        if act_ids:
            db.session.execute(delete(ExamCenterActivityDetail).where(ExamCenterActivityDetail.activity_id.in_(act_ids)))
            db.session.execute(delete(ExamCenterActivity).where(ExamCenterActivity.id.in_(act_ids)))
        for r in rows:
            db.session.delete(r)
        db.session.commit()
        print("done: removed local assignment mirror(s) and related activities.")


if __name__ == "__main__":
    main()
