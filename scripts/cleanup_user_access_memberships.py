# -*- coding: utf-8 -*-
"""一次性批量清理账号 membership：公司管理员只保留公司绑定，其它角色只保留项目组绑定。

规则（与页面4 账号管理一致）：
- company：删除 UserTeamMembership；确保 can_access_company_registry=True
- none / project：删除 UserOrganizationMembership 与 UserCountryScope；关闭 can_access_company_registry

用法：
    python scripts/cleanup_user_access_memberships.py           # 预览，不写库
    python scripts/cleanup_user_access_memberships.py --apply   # 执行并提交
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _print_summary(result: dict) -> None:
    mode = "预览（未写库）" if result.get("dryRun") else "已执行"
    print(f"\n=== 账号 membership 清理 · {mode} ===")
    print(f"总账号数：{result.get('totalUsers', 0)}")
    print(f"需清理：{result.get('changedUsers', 0)}")
    users = result.get("users") or []
    if not users:
        print("无需要清理的账号。")
        return
    for row in users:
        parts = [f"  · {row.get('username')} ({row.get('adminRole')})"]
        if row.get("removedTeamIds"):
            parts.append(f"删项目组={','.join(row['removedTeamIds'])}")
        if row.get("removedOrganizationIds"):
            parts.append(f"删公司={','.join(row['removedOrganizationIds'])}")
        if row.get("removedCountries"):
            parts.append(f"删国家={','.join(row['removedCountries'])}")
        if row.get("fixedCanAccessCompanyRegistry"):
            parts.append("修正页面0权限")
        print(" — ".join(parts))


def main() -> int:
    parser = argparse.ArgumentParser(description="批量清理账号公司/项目组互斥 membership")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="执行清理并提交（默认仅预览）",
    )
    args = parser.parse_args()

    from webapp import create_app
    from webapp.user_access import batch_normalize_user_access_memberships

    app = create_app()
    with app.app_context():
        result = batch_normalize_user_access_memberships(dry_run=not args.apply)
        _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
