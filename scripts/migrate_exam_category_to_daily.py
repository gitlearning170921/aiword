"""
一次性数据迁移：将考试训练中心相关表中 exam_category 为空的历史记录标为 daily（日常考试）。

与体考类型 exam_track 正交；新增「新标发布」前历史数据均视为日常考试。

用法（在 aiword 项目根目录）:
  python scripts/migrate_exam_category_to_daily.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    import logging

    # create_app 会同步库内 UPLOAD_FOLDER/OUTPUT_FOLDER；迁机后旧盘符无效会打 WARNING，
    # 且若根日志器重复挂载 handler 可能同一条出现两次。本脚本仅 UPDATE 表字段，不依赖目录。
    logging.getLogger("webapp.app_settings").setLevel(logging.ERROR)

    from webapp import create_app, db
    from sqlalchemy import text

    app = create_app()
    tables = (
        "exam_center_assignments",
        "exam_center_activities",
        "exam_attempts",
        "exam_bank_ingest_jobs",
    )
    with app.app_context():
        dialect = db.engine.dialect.name
        for t in tables:
            if dialect == "sqlite":
                sql = text(f"UPDATE {t} SET exam_category = 'daily' WHERE exam_category IS NULL OR TRIM(exam_category) = ''")
            else:
                sql = text(
                    f"UPDATE {t} SET exam_category = 'daily' WHERE exam_category IS NULL OR exam_category = ''"
                )
            try:
                r = db.session.execute(sql)
                db.session.commit()
                print(f"[ok] {t}: rowcount={getattr(r, 'rowcount', None)}")
            except Exception as e:
                db.session.rollback()
                print(f"[skip/fail] {t}: {e}")


if __name__ == "__main__":
    main()
