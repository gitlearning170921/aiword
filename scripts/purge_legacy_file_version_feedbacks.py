# -*- coding: utf-8 -*-
"""删除「文件版本号：目标版本 → 空」这类历史误采集。

不导入 webapp（避免 create_app 同步公司映射）。连接串只读 instance/database_url.txt。

用法（在 aiword 项目根目录）:
  python scripts/purge_legacy_file_version_feedbacks.py
  python scripts/purge_legacy_file_version_feedbacks.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VERSION_RE = re.compile(r"^[Vv]?\s*(\d+)\.(\d+)\.(\d+)\.(\d+)\s*$")
COMPARE_KEYS = (
    "fileName",
    "documentNumber",
    "fileVersion",
    "taskType",
    "targetVersion",
    "author",
    "dueDate",
    "documentDisplayDate",
    "belongingModule",
    "notes",
    "recordStatus",
    "chapter",
    "isSystemRecord",
)


def _looks_like_software_version(value: str) -> bool:
    return bool(VERSION_RE.match(str(value or "").strip()))


def _as_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def _as_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []
    return []


def _split_legacy(item: dict[str, Any]) -> dict[str, Any]:
    rec = dict(item)
    tv = str(rec.get("targetVersion") or rec.get("registrationVersion") or "").strip()
    fv = str(rec.get("fileVersion") or "").strip()
    if not tv and _looks_like_software_version(fv):
        rec["targetVersion"] = fv
        rec["fileVersion"] = ""
        if not str(rec.get("registrationVersion") or "").strip():
            rec["registrationVersion"] = fv
    elif fv and tv and fv == tv and _looks_like_software_version(fv):
        rec["fileVersion"] = ""
    rec["documentNumber"] = str(rec.get("documentNumber") or "").strip()
    rec["fileVersion"] = str(rec.get("fileVersion") or "").strip()
    return rec


def _field(item: dict[str, Any], key: str) -> str:
    if key == "targetVersion":
        return str(item.get("targetVersion") or item.get("registrationVersion") or "").strip()
    if key == "chapter":
        return str(item.get("chapter") or item.get("processBranchLabel") or "").strip()
    if key == "isSystemRecord":
        return "1" if item.get("isSystemRecord") in {True, 1, "1", "true", "是"} else "0"
    return str(item.get(key) or "").strip()


def _has_real_diff(original: dict[str, Any], adjusted: dict[str, Any]) -> bool:
    before = _split_legacy(original)
    after = _split_legacy(adjusted)
    return any(_field(before, key) != _field(after, key) for key in COMPARE_KEYS)


def _summary_is_legacy_file_version_only(summary: Any) -> bool:
    rows = _as_list(summary)
    if not rows:
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        if str(row.get("field") or "").strip() != "fileVersion":
            return False
        frm = str(row.get("from") or "").strip()
        to = str(row.get("to") or "").strip()
        if to or not _looks_like_software_version(frm):
            return False
    return True


def is_legacy_alias_row(row: dict[str, Any]) -> bool:
    kind = str(row.get("adjust_type") or "").strip().lower()
    if kind not in {"update", "replace"}:
        return False
    original = _as_dict(row.get("original_item_json"))
    adjusted = _as_dict(row.get("adjusted_item_json"))
    if _has_real_diff(original, adjusted):
        return False
    if _summary_is_legacy_file_version_only(row.get("change_summary_json")):
        return True
    orig_fv = str(original.get("fileVersion") or "").strip()
    adj_fv = str(adjusted.get("fileVersion") or "").strip()
    tv = str(
        original.get("targetVersion")
        or original.get("registrationVersion")
        or adjusted.get("targetVersion")
        or adjusted.get("registrationVersion")
        or ""
    ).strip()
    return bool(orig_fv and not adj_fv and _looks_like_software_version(orig_fv) and orig_fv == tv)


def _read_database_uri() -> str:
    path = ROOT / "instance" / "database_url.txt"
    if not path.exists():
        raise SystemExit("未找到 instance/database_url.txt，无法连接数据库")
    uri = path.read_text(encoding="utf-8").strip().split("\n")[0].strip()
    if not uri:
        raise SystemExit("instance/database_url.txt 为空")
    return uri


def main() -> int:
    parser = argparse.ArgumentParser(description="清理文件版本号误采集")
    parser.add_argument("--apply", action="store_true", help="执行删除（默认只预览）")
    args = parser.parse_args()

    from sqlalchemy import bindparam, create_engine, text

    engine = create_engine(_read_database_uri())
    sql = text(
        "SELECT id, adjust_type, original_item_json, adjusted_item_json, "
        "change_summary_json, reason FROM version_task_generation_feedbacks"
    )
    with engine.connect() as conn:
        rows = [dict(x) for x in conn.execute(sql).mappings().all()]
    hits = [row for row in rows if is_legacy_alias_row(row)]
    print(f"反馈总数 {len(rows)}，误采集 {len(hits)}")
    for row in hits[:30]:
        original = _as_dict(row.get("original_item_json"))
        adjusted = _as_dict(row.get("adjusted_item_json"))
        name = str(adjusted.get("fileName") or original.get("fileName") or "").strip() or "?"
        print(f"  · {row.get('id')} {row.get('adjust_type')} {name}")
    if len(hits) > 30:
        print(f"  … 另有 {len(hits) - 30} 条")
    if not hits:
        return 0
    if not args.apply:
        print("预览模式，未删除。加上 --apply 才会写库。")
        return 0
    ids = [str(row.get("id") or "") for row in hits if row.get("id")]
    stmt = text(
        "DELETE FROM version_task_generation_feedbacks WHERE id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    with engine.begin() as conn:
        conn.execute(stmt, {"ids": ids})
    print(f"已删除 {len(ids)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
