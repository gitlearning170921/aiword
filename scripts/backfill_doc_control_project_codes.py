from __future__ import annotations

"""文控台账：按所属项目名称一次性回填 project_code（不随服务启动执行）。

规则：
- 呼吸数据管理软件 → BRCMS
- Breathcare Management System → PAPUWIS
- 心电分析提示软件 → ECGAP
- BreathCare Station → BRCST
- BreathCare+ → BRCARE
- 仅处理文件编号**不是** QR 开头的记录（QR 开头跳过）

用法：
    python scripts/backfill_doc_control_project_codes.py
    python scripts/backfill_doc_control_project_codes.py --apply
    python scripts/backfill_doc_control_project_codes.py --org-id <uuid> --apply
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_ORG_ID = "9145f16e-90ab-4f90-b2b2-0b95bcc9da45"

PROJECT_NAME_TO_CODE: dict[str, str] = {
    "呼吸数据管理软件": "BRCMS",
    "Breathcare Management System": "PAPUWIS",
    "心电分析提示软件": "ECGAP",
    "BreathCare Station": "BRCST",
    "BreathCare+": "BRCARE",
}


def _norm_name(value: str) -> str:
    return " ".join((value or "").split())


def _is_qr_number(document_number: str) -> bool:
    return (document_number or "").strip().upper().startswith("QR")


def main() -> int:
    parser = argparse.ArgumentParser(description="文控台账 project_code 一次性回填")
    parser.add_argument(
        "--org-id",
        default=DEFAULT_ORG_ID,
        help=f"组织 ID（默认南京鱼跃 {DEFAULT_ORG_ID}）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="写入数据库（默认仅预览）",
    )
    args = parser.parse_args()
    org_id = (args.org_id or "").strip()
    if not org_id:
        print("[错误] 请指定 --org-id")
        return 1

    from webapp import create_app, db
    from webapp.models import ControlledDocument

    app = create_app()
    with app.app_context():
        rows = (
            ControlledDocument.query.filter_by(organization_id=org_id)
            .order_by(ControlledDocument.created_at.asc())
            .all()
        )
        targets: list[tuple[ControlledDocument, str]] = []
        skipped_same = 0
        skipped_qr = 0
        for doc in rows:
            name = _norm_name(doc.project_name or "")
            code = PROJECT_NAME_TO_CODE.get(name)
            if not code:
                continue
            if _is_qr_number(doc.document_number or ""):
                skipped_qr += 1
                continue
            current = (doc.project_code or "").strip().upper()
            if current == code.upper():
                skipped_same += 1
                continue
            targets.append((doc, code))

        print(f"组织 {org_id}：台账共 {len(rows)} 条")
        print(
            f"将更新 project_code：{len(targets)} 条"
            f"（已为目标编号跳过 {skipped_same} 条，QR 编号跳过 {skipped_qr} 条）"
        )
        if not targets:
            print("无可更新记录。")
            return 0

        by_name: dict[str, int] = {}
        for doc, code in targets:
            name = _norm_name(doc.project_name or "")
            by_name[name] = by_name.get(name, 0) + 1
        for name, count in sorted(by_name.items(), key=lambda x: x[0]):
            print(f"  {name} → {PROJECT_NAME_TO_CODE[name]}：{count} 条")

        print("\n明细（前 30 条）：")
        for doc, code in targets[:30]:
            old = (doc.project_code or "").strip() or "-"
            print(
                f"  {doc.document_number}\t{old} → {code}\t"
                f"{_norm_name(doc.project_name or '')}"
            )
        if len(targets) > 30:
            print(f"  … 另有 {len(targets) - 30} 条")

        if not args.apply:
            print("\n[dry-run] 未写入。确认后执行：")
            print("  python scripts/backfill_doc_control_project_codes.py --apply")
            return 0

        for doc, code in targets:
            doc.project_code = code
            db.session.add(doc)
        db.session.commit()
        print(f"\n[OK] 已更新 {len(targets)} 条 project_code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
