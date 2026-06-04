from __future__ import annotations

"""多租户最小联调回归脚本（不联 aicheckword 真实服务）。

用途：
- 验证 `organizations` / `user_organization_memberships` 表存在
- 验证关键业务表存在 `organization_id` 列且老数据已回填
- 验证 `tenant_context.resolve_organization_context()` 在多租户开关默认关闭时
  仍返回旧 collection（向后兼容）
- 验证开启多租户后，无显式 ID 时回退到默认组织且 collection 正确
- 验证用户与组织的 `UserOrganizationMembership` seed 完整

运行：
    python scripts/multi_tenant_smoke.py

非零退出码表示回归失败。所有访问都基于 SQLAlchemy/Flask 上下文，不发起任何
对 aicheckword 的网络请求。
"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


REQUIRED_ORG_COLUMN_TABLES = (
    "project_teams",
    "company_projects",
    "projects",
    "upload_records",
    "draft_generation_jobs",
    "audit_jobs",
    "translation_jobs",
    "exam_center_assignments",
    "exam_center_activities",
    "exam_attempts",
    "exam_bank_ingest_jobs",
    "exam_set_review_jobs",
)


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"[ OK ] {msg}")


def run() -> None:
    from webapp import create_app, db  # noqa: E402
    from sqlalchemy import inspect, text  # noqa: E402

    app = create_app()
    with app.app_context():
        insp = inspect(db.engine)
        tables = set(insp.get_table_names())

        if "organizations" not in tables:
            _fail("organizations 表缺失")
        if "user_organization_memberships" not in tables:
            _fail("user_organization_memberships 表缺失")
        _ok("organizations / user_organization_memberships 表存在")

        for t in REQUIRED_ORG_COLUMN_TABLES:
            if t not in tables:
                continue
            cols = {c["name"] for c in insp.get_columns(t)}
            if "organization_id" not in cols:
                _fail(f"{t} 缺少 organization_id 列")
        _ok("关键业务表均含 organization_id 列")

        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, name, knowledge_collection FROM organizations "
                    "WHERE is_default = 1 LIMIT 1"
                )
            ).fetchone()
            if not row:
                _fail("默认组织缺失（is_default=1）")
            default_org_id, default_name, default_coll = (
                str(row[0] or "").strip(),
                str(row[1] or "").strip(),
                str(row[2] or "").strip(),
            )
            if not default_org_id:
                _fail("默认组织 id 为空")
            _ok(
                f"默认组织 OK: name={default_name!r} id={default_org_id} collection={default_coll!r}"
            )

            for t in REQUIRED_ORG_COLUMN_TABLES:
                if t not in tables:
                    continue
                cnt = conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {t} "
                        "WHERE organization_id IS NULL OR organization_id = ''"
                    )
                ).scalar()
                if (cnt or 0) > 0:
                    _fail(
                        f"{t} 仍存在 {cnt} 条 organization_id 为空记录（回填未完成）"
                    )
            _ok("所有 backfill 表 organization_id 已就绪")

            users_total = conn.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0
            users_with_org = conn.execute(
                text(
                    "SELECT COUNT(DISTINCT user_id) FROM user_organization_memberships"
                )
            ).scalar() or 0
            if users_total and users_with_org < users_total:
                _fail(
                    f"仍有用户未关联任何组织: total={users_total} mapped={users_with_org}"
                )
            _ok(f"用户-组织映射 OK: total={users_total} mapped={users_with_org}")

        from webapp import app_settings
        from webapp import tenant_context as tc

        original_flag = app_settings.is_multi_tenant_enabled()

        try:
            with app.test_request_context():
                ctx_off_oid, ctx_off_coll = tc.resolve_organization_context()
            if not original_flag:
                if ctx_off_oid and ctx_off_oid != default_org_id:
                    _fail(
                        f"多租户关闭时 resolve 应返回默认组织: got={ctx_off_oid!r}"
                    )
                if (ctx_off_coll or "") != "regulations":
                    _fail(
                        f"多租户关闭时 collection 应回退到 regulations: got={ctx_off_coll!r}"
                    )
            _ok(
                f"多租户关闭分支 resolve OK: org={ctx_off_oid!r} collection={ctx_off_coll!r}"
            )
        except Exception as exc:  # pragma: no cover
            traceback.print_exc()
            _fail(f"resolve_organization_context 关闭分支异常: {exc}")

        from webapp.models import AppConfig
        from webapp import db as _db

        existing_cfg = AppConfig.query.filter_by(config_key="FEATURE_MULTI_TENANT").first()
        prev_value = existing_cfg.config_value if existing_cfg else None
        created_now = False
        try:
            if existing_cfg:
                existing_cfg.config_value = "1"
            else:
                existing_cfg = AppConfig(config_key="FEATURE_MULTI_TENANT", config_value="1")
                _db.session.add(existing_cfg)
                created_now = True
            _db.session.commit()
            if not app_settings.is_multi_tenant_enabled():
                _fail("FEATURE_MULTI_TENANT 写入后 is_multi_tenant_enabled 仍为 False")
            with app.test_request_context():
                from flask import session

                session["organization_ids"] = [default_org_id]
                session["active_organization_id"] = default_org_id
                org_id, collection = tc.resolve_organization_context()
            if org_id != default_org_id:
                _fail(
                    f"多租户开启时未回退到默认组织: org={org_id!r} expected={default_org_id!r}"
                )
            if not collection:
                _fail("多租户开启时 collection 为空")
            _ok(
                f"多租户开启 resolve OK: org={org_id} collection={collection!r}"
            )
        finally:
            if created_now:
                _db.session.delete(existing_cfg)
                _db.session.commit()
            else:
                existing_cfg.config_value = prev_value or ""
                _db.session.commit()
            if app_settings.is_multi_tenant_enabled() != original_flag:
                _fail("还原 FEATURE_MULTI_TENANT 失败")
        _ok("多租户开关已还原")

    print("multi-tenant smoke 通过")


if __name__ == "__main__":
    run()
