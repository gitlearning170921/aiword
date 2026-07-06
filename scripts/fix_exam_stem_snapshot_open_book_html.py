#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清洗 aiword 考试相关镜像表中的题干 HTML 脏数据：
- exam_attempt_items.stem_snapshot
- exam_center_activity_details.upstream_payload（JSON 内 items/questions 的 stem）

用法：
  python scripts/fix_exam_stem_snapshot_open_book_html.py --dry-run
  python scripts/fix_exam_stem_snapshot_open_book_html.py
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from webapp import create_app  # noqa: E402
from webapp.exam_stem_sanitize import (  # noqa: E402
    strip_broken_open_book_html,
    strip_open_book_html_in_tree,
)
from webapp.models import ExamAttemptItem, ExamCenterActivityDetail, db  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="每类最多处理 N 条有变化记录（0=不限）")
    args = ap.parse_args()

    app = create_app()
    changed_items = 0
    changed_details = 0
    scanned_items = 0
    scanned_details = 0
    samples: list[dict] = []

    with app.app_context():
        for it in ExamAttemptItem.query.order_by(ExamAttemptItem.created_at.asc()).all():
            scanned_items += 1
            before = str(it.stem_snapshot or "")
            after = strip_broken_open_book_html(before)
            if after == before:
                continue
            if args.limit and args.limit > 0 and changed_items >= int(args.limit):
                break
            changed_items += 1
            if len(samples) < 8:
                samples.append(
                    {
                        "table": "exam_attempt_items",
                        "id": it.id,
                        "before": before[:240],
                        "after": after[:240],
                    }
                )
            if not args.dry_run:
                it.stem_snapshot = after

        for det in ExamCenterActivityDetail.query.order_by(ExamCenterActivityDetail.created_at.asc()).all():
            scanned_details += 1
            pl = det.upstream_payload
            if not isinstance(pl, dict) or not pl:
                continue
            cloned = copy.deepcopy(pl)
            n = strip_open_book_html_in_tree(cloned)
            if n <= 0:
                continue
            if args.limit and args.limit > 0 and changed_details >= int(args.limit):
                break
            changed_details += 1
            if len(samples) < 12:
                samples.append(
                    {
                        "table": "exam_center_activity_details",
                        "id": det.id,
                        "fields_changed_in_payload": n,
                    }
                )
            if not args.dry_run:
                det.upstream_payload = cloned

        if not args.dry_run and (changed_items or changed_details):
            db.session.commit()

    print(
        json.dumps(
            {
                "dry_run": bool(args.dry_run),
                "exam_attempt_items_scanned": scanned_items,
                "exam_attempt_items_changed": changed_items,
                "activity_details_scanned": scanned_details,
                "activity_details_changed": changed_details,
                "samples": samples,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
