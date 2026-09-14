from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from html import unescape
from copy import deepcopy
from typing import Any, Optional
from urllib.parse import quote, urlparse

import requests
from sqlalchemy import update as sa_update

from webapp import db
from webapp.models import (
    ControlledDocument,
    Project,
    ProjectVersionRecord,
    VersionTaskGenerationFeedback,
    VersionTaskGenerationJob,
    now_local,
)

VERSION_RE = re.compile(r"^[Vv]?\s*(\d+)\.(\d+)\.(\d+)\.(\d+)\s*$")
DATE_PATTERNS = (
    re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b"),
    re.compile(r"\b(20\d{2})年(\d{1,2})月(\d{1,2})日\b"),
)
_DDG_URL_TEMPLATES = (
    "https://html.duckduckgo.com/html/?q={query}",
    "https://lite.duckduckgo.com/lite/?q={query}",
)


@dataclass(frozen=True)
class ParsedVersion:
    raw: str
    normalized: str
    x: int
    y: int
    z: int
    b: int


from .version_task_rules import (
    catalogs_for_dominant,
    load_version_task_rules,
    process_branch_label,
)

# 版本清单下发到任务列表时的默认任务类型（与系统默认 TaskTypeConfig 一致）
DEFAULT_VERSION_TASK_TYPE = "初稿待编写"
LEGACY_DEFAULT_VERSION_TASK_TYPE = "版本变更任务"
LEGACY_AUTO_VERSION_TASK_TYPES = {
    LEGACY_DEFAULT_VERSION_TASK_TYPE,
    "归档文件",
    "变更控制流程",
    "缺陷管理流程",
    "生产发布流程",
}


def parse_version(raw: str) -> ParsedVersion:
    text = (raw or "").strip()
    m = VERSION_RE.match(text)
    if not m:
        raise ValueError(f"版本号格式错误：{raw}（应为 X.Y.Z.B）")
    x, y, z, b = [int(m.group(i)) for i in range(1, 5)]
    return ParsedVersion(raw=text, normalized=f"{x}.{y}.{z}.{b}", x=x, y=y, z=z, b=b)


def parse_version_chain(
    from_version: str,
    to_version: str,
    intermediate_versions: Optional[list[str]] = None,
) -> list[ParsedVersion]:
    chain_raw = [from_version]
    for item in intermediate_versions or []:
        s = (item or "").strip()
        if s:
            chain_raw.append(s)
    chain_raw.append(to_version)
    parsed: list[ParsedVersion] = [parse_version(v) for v in chain_raw]
    return parsed


def dominant_change(prev_v: ParsedVersion, next_v: ParsedVersion) -> str:
    if next_v.x != prev_v.x:
        return "X"
    if next_v.y != prev_v.y:
        return "Y"
    if next_v.z != prev_v.z:
        return "Z"
    if next_v.b != prev_v.b:
        return "B"
    return "NONE"


def normalize_version_release_dates(
    chain: list[ParsedVersion],
    raw_dates: Optional[dict[str, Any]],
) -> dict[str, str]:
    if not isinstance(raw_dates, dict):
        raise ValueError("versionReleaseDates 必须为对象")
    out: dict[str, str] = {}
    missing: list[str] = []
    for version in chain:
        key = version.normalized
        value = str(raw_dates.get(key) or raw_dates.get(version.raw) or "").strip()
        if not value:
            missing.append(key)
            continue
        out[key] = _fmt_date(_parse_iso_date(value))
    if missing:
        raise ValueError(f"以下版本缺少发布时间：{', '.join(missing)}")
    return out


def build_transitions(chain: list[ParsedVersion]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx in range(len(chain) - 1):
        left = chain[idx]
        right = chain[idx + 1]
        change = dominant_change(left, right)
        out.append(
            {
                "fromVersion": left.normalized,
                "toVersion": right.normalized,
                "dominantChange": change,
                "changedSegments": {
                    "x": left.x != right.x,
                    "y": left.y != right.y,
                    "z": left.z != right.z,
                    "b": left.b != right.b,
                },
            }
        )
    return out


def _parse_iso_date(raw: str) -> date:
    value = (raw or "").strip()
    if not value:
        raise ValueError("发布时间不能为空")
    return datetime.strptime(value, "%Y-%m-%d").date()


def _fmt_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def normalize_preview_item_fields(rec: dict[str, Any]) -> bool:
    """统一任务类型默认值，并把历史「备注」(规则原因)迁到「说明」。

    就地改写传入字典。去重仍按改写前的 taskType 进行，本函数应在去重之后调用。
    """
    if not isinstance(rec, dict):
        return False
    rec.update(split_legacy_file_version_alias(rec))
    changed = False
    kind = str(rec.get("taskType") or "").strip()
    if not kind or kind in LEGACY_AUTO_VERSION_TASK_TYPES:
        if kind != DEFAULT_VERSION_TASK_TYPE:
            rec["taskType"] = DEFAULT_VERSION_TASK_TYPE
            changed = True
    if rec.get("explanation") is None:
        rec["explanation"] = str(rec.get("notes") or rec.get("reason") or "").strip()
        rec["notes"] = ""
        changed = True
    else:
        rec["explanation"] = str(rec.get("explanation") or "").strip()
        rec["notes"] = str(rec.get("notes") or "").strip()
    return changed


def _merge_generated_item(target: dict[str, Any], patch: dict[str, Any]) -> None:
    allow_keys = {
        "fileName",
        "taskType",
        "author",
        "belongingModule",
        "explanation",
        "notes",
        "dueDate",
        "documentDisplayDate",
        "targetVersion",
        "fileVersion",
        "registrationVersion",
        "documentNumber",
        "isSystemRecord",
    }
    for key in allow_keys:
        if key in patch:
            target[key] = patch[key]


def _task_identity(item: dict[str, Any]) -> tuple[str, str, str]:
    return _task_dedupe_key(item)


def _feedback_identity(item: dict[str, Any]) -> tuple[str, str, str]:
    rec = dict(item) if isinstance(item, dict) else {}
    normalize_preview_item_fields(rec)
    return _task_identity(rec)


def _mark_preview_row_deleted(rec: dict[str, Any]) -> dict[str, Any]:
    row = dict(rec)
    row["changeKind"] = "delete"
    row["hideInPreview"] = True
    return row


def _preview_row_is_deleted(
    rec: dict[str, Any],
    deleted_keys: Optional[set[tuple[str, str, str]]] = None,
) -> bool:
    if not isinstance(rec, dict):
        return False
    kind = str(rec.get("changeKind") or "").strip().lower()
    if kind == "delete" or rec.get("hideInPreview"):
        return True
    if deleted_keys is not None and _task_dedupe_key(rec) in deleted_keys:
        return True
    return False


def collect_deleted_dedupe_keys(
    previous_items: Optional[list[dict[str, Any]]] = None,
    deleted_keys: Optional[list[Any]] = None,
) -> set[tuple[str, str, str]]:
    """从上次快照与 manualDeletedKeys 收集应排除的任务键。"""
    deleted: set[tuple[str, str, str]] = set()
    for raw in deleted_keys or []:
        parsed = _parse_dedupe_key(raw)
        if parsed:
            deleted.add(parsed)
    for row in previous_items or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("changeKind") or "").strip().lower()
        if kind != "delete" and not row.get("hideInPreview"):
            continue
        cleaned = split_legacy_file_version_alias(row)
        deleted.add(_task_dedupe_key(cleaned))
    return deleted


def apply_feedback_rules(
    generated_items: list[dict[str, Any]],
    feedback_rows: list[VersionTaskGenerationFeedback],
) -> tuple[list[dict[str, Any]], int]:
    items = [dict(x) for x in generated_items]
    hit = 0
    for row in feedback_rows:
        if is_legacy_file_version_alias_feedback(row):
            continue
        kind = (row.adjust_type or "").strip().lower()
        original = row.original_item_json if isinstance(row.original_item_json, dict) else {}
        adjusted = row.adjusted_item_json if isinstance(row.adjusted_item_json, dict) else {}
        if kind == "delete":
            # 删除只写在已保存快照里。再次「生成预览」按规则重建，不把删除套回去。
            continue
        identity = _feedback_identity(original if kind != "add" else adjusted)
        if kind != "add" and identity == ("", "", ""):
            continue
        if kind == "add":
            candidate = dict(adjusted)
            if candidate.get("explanation") is None:
                candidate["explanation"] = str(candidate.get("notes") or "").strip()
                candidate["notes"] = ""
            if candidate and _feedback_identity(candidate) not in {_feedback_identity(x) for x in items}:
                items.append(candidate)
                hit += 1
            continue
        idx = next((i for i, x in enumerate(items) if _feedback_identity(x) == identity), None)
        if idx is None:
            continue
        if kind in {"update", "replace"}:
            _merge_generated_item(items[idx], adjusted)
            # 旧反馈只有 notes（当时存的是规则原因），不要写进新的下发备注列
            if "explanation" not in adjusted and "notes" in adjusted:
                if not str(items[idx].get("explanation") or "").strip():
                    items[idx]["explanation"] = str(adjusted.get("notes") or "").strip()
                items[idx]["notes"] = ""
            hit += 1
    return items, hit


def find_preview_filename_conflicts(items: Optional[list[Any]]) -> list[dict[str, Any]]:
    """同一版本下（忽略已删除、空文件名）文件名重复。"""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in items or []:
        if not isinstance(rec, dict):
            continue
        if _preview_row_is_deleted(rec):
            continue
        name = str(rec.get("fileName") or "").strip()
        if not name:
            continue
        ver = str(
            rec.get("targetVersion") or rec.get("registrationVersion") or ""
        ).strip() or "未指定版本"
        key = (ver.casefold(), name.casefold())
        bucket = groups.get(key)
        if bucket is None:
            bucket = {"version": ver, "fileName": name, "count": 0}
            groups[key] = bucket
        bucket["count"] += 1
    return [row for row in groups.values() if int(row.get("count") or 0) > 1]


def format_preview_filename_conflicts(conflicts: list[dict[str, Any]]) -> str:
    if not conflicts:
        return "同一项目、同一版本下文件名不能重复"
    bits = [
        f"版本 {row.get('version') or '未指定版本'} 的「{row.get('fileName') or ''}」有 {row.get('count')} 条"
        for row in conflicts
    ]
    return "同一项目、同一版本下文件名不能重复：" + "；".join(bits)


def _task_dedupe_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("taskKey") or item.get("fileName") or "").strip().casefold(),
        str(item.get("targetVersion") or item.get("registrationVersion") or "").strip().casefold(),
        str(item.get("taskType") or "").strip().casefold(),
    )


def _serialize_dedupe_key(key: tuple[str, str, str]) -> list[str]:
    return [key[0], key[1], key[2]]


def _parse_dedupe_key(raw: Any) -> Optional[tuple[str, str, str]]:
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        return (
            str(raw[0] or "").strip().casefold(),
            str(raw[1] or "").strip().casefold(),
            str(raw[2] or "").strip().casefold(),
        )
    return None


def normalize_record_status(raw: Any) -> str:
    """预览记录状态：选用 / 弃用 / 待定。空值与未知值按选用。"""
    key = str(raw or "").strip().lower()
    if key in {"discard", "弃用", "deprecated", "rejected"}:
        return "discard"
    if key in {"pending", "待定"}:
        return "pending"
    return "adopt"


def normalize_is_system_record(raw: Any, *, default: bool = False) -> bool:
    """是否体系记录。缺字段或未勾选时默认为否。"""
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    key = str(raw).strip().lower()
    if key in {"1", "true", "yes", "y", "是", "体系", "体系记录"}:
        return True
    if key in {"0", "false", "no", "n", "否", "非体系"}:
        return False
    return default


def _origin_key_of(item: dict[str, Any]) -> str:
    existing = str(item.get("originKey") or "").strip()
    if existing:
        return existing
    a, b, c = _task_dedupe_key(item)
    return f"{a}||{b}||{c}"


def _looks_like_software_version(value: str) -> bool:
    return bool(VERSION_RE.match(str(value or "").strip()))


def split_legacy_file_version_alias(item: dict[str, Any]) -> dict[str, Any]:
    """旧快照把目标版本写在 fileVersion；文件版本号列启用后需拆开。"""
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


_TITLE_PUNCT_RE = re.compile(r"[\s\-_.·•、，。:：/\\()（）\[\]【】《》\"'`]+")
_DOC_FUZZY_MIN_SCORE = 0.72


def _compact_title(value: str) -> str:
    return _TITLE_PUNCT_RE.sub("", str(value or "")).casefold()


def _filename_match_keys(name: str) -> list[str]:
    from .subtype_resolver import normalize_title_key

    raw = str(name or "").strip()
    if not raw:
        return []
    keys: list[str] = []
    for candidate in (raw, re.sub(r"\.(docx?|pdf|xlsx?|pptx?)$", "", raw, flags=re.I)):
        key = normalize_title_key(candidate)
        compact = _compact_title(candidate)
        for item in (key, compact):
            if item and item not in keys:
                keys.append(item)
    return keys


def _title_fuzzy_score(query: str, title: str) -> float:
    q = _compact_title(query)
    t = _compact_title(title)
    if not q or not t:
        return 0.0
    if q == t:
        return 1.0
    shorter, longer = (q, t) if len(q) <= len(t) else (t, q)
    if shorter in longer:
        if len(shorter) < 2:
            return 0.0
        cover = len(shorter) / max(len(longer), 1)
        if len(shorter) < 4 and cover < 0.5:
            return 0.0
        return round(0.82 + 0.18 * cover, 4)
    ratio = SequenceMatcher(None, q, t).ratio()
    if len(q) < 4 or len(t) < 4:
        return ratio if ratio >= 0.92 else 0.0
    return ratio if ratio >= _DOC_FUZZY_MIN_SCORE else 0.0


def _build_controlled_doc_candidates(
    org_id: str, project_id: Optional[str] = None
) -> list[dict[str, Any]]:
    from .numbering_engine import is_controlled_document_status

    project_code = ""
    if project_id:
        project = Project.query.filter_by(id=project_id).first()
        if project:
            project_code = str(project.project_code or "").strip()
    rows = ControlledDocument.query.filter_by(organization_id=org_id).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        if not is_controlled_document_status(row.status):
            continue
        keys: list[str] = []
        for title in (row.title, row.title_en):
            for key in _filename_match_keys(str(title or "")):
                if key not in keys:
                    keys.append(key)
        if not keys:
            continue
        project_score = 0
        if project_id and str(row.project_id or "") == str(project_id):
            project_score += 4
        if project_code and str(row.project_code or "").strip() == project_code:
            project_score += 2
        out.append(
            {
                "keys": keys,
                "documentNumber": str(row.document_number or "").strip(),
                "fileVersion": str(row.version or "").strip(),
                "projectScore": project_score,
                "updatedTs": row.updated_at.timestamp() if row.updated_at else 0.0,
            }
        )
    return out


def _match_controlled_doc_meta(
    file_name: str, candidates: list[dict[str, Any]]
) -> Optional[dict[str, str]]:
    query_keys = _filename_match_keys(file_name)
    if not query_keys or not candidates:
        return None
    best: Optional[dict[str, Any]] = None
    best_rank: Optional[tuple] = None
    for cand in candidates:
        score = 0.0
        for qk in query_keys:
            for tk in cand.get("keys") or []:
                score = max(score, _title_fuzzy_score(qk, tk))
        if score <= 0:
            continue
        rank = (score, int(cand.get("projectScore") or 0), float(cand.get("updatedTs") or 0))
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best = cand
    if not best:
        return None
    return {
        "documentNumber": str(best.get("documentNumber") or "").strip(),
        "fileVersion": str(best.get("fileVersion") or "").strip(),
    }


def enrich_preview_items_from_document_control(
    items: Optional[list[Any]],
    *,
    org_id: Optional[str] = None,
    project_id: Optional[str] = None,
    overwrite: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """按文件名模糊匹配文控台账，补齐文件编号 / 文件版本号。默认不覆盖已填值。"""
    rows = [dict(x) for x in (items or []) if isinstance(x, dict)]
    if not org_id or not rows:
        return rows, 0
    candidates = _build_controlled_doc_candidates(org_id, project_id)
    filled = 0
    out: list[dict[str, Any]] = []
    for rec in rows:
        rec = split_legacy_file_version_alias(rec)
        hit = _match_controlled_doc_meta(str(rec.get("fileName") or ""), candidates)
        changed = False
        if hit:
            if (overwrite or not str(rec.get("documentNumber") or "").strip()) and hit.get(
                "documentNumber"
            ):
                if str(rec.get("documentNumber") or "").strip() != hit["documentNumber"]:
                    rec["documentNumber"] = hit["documentNumber"]
                    changed = True
            if (overwrite or not str(rec.get("fileVersion") or "").strip()) and hit.get(
                "fileVersion"
            ):
                if str(rec.get("fileVersion") or "").strip() != hit["fileVersion"]:
                    rec["fileVersion"] = hit["fileVersion"]
                    changed = True
        if changed:
            filled += 1
        out.append(rec)
    return out, filled


def annotate_preview_item(item: dict[str, Any], *, fresh: bool = False) -> dict[str, Any]:
    rec = split_legacy_file_version_alias(item)
    normalize_preview_item_fields(rec)
    rec["originKey"] = _origin_key_of(rec)
    rec["recordStatus"] = normalize_record_status(rec.get("recordStatus"))
    rec["isSystemRecord"] = normalize_is_system_record(
        rec.get("isSystemRecord"), default=False
    )
    if fresh:
        rec["changeKind"] = ""
        rec["changeReason"] = ""
        rec["changeFields"] = []
        return rec
    kind = str(rec.get("changeKind") or "").strip().lower()
    rec["changeKind"] = kind if kind in {"add", "update", "delete"} else ""
    rec["changeReason"] = str(rec.get("changeReason") or "").strip()[:512]
    fields = rec.get("changeFields")
    rec["changeFields"] = fields if isinstance(fields, list) else []
    return rec


def preview_change_log_from_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in items:
        kind = str(rec.get("changeKind") or "").strip().lower()
        if kind not in {"add", "update", "delete"}:
            continue
        summary = rec.get("changeFields") if isinstance(rec.get("changeFields"), list) else []
        out.append(
            {
                "type": kind,
                "reason": str(rec.get("changeReason") or "").strip(),
                "changeSummary": summary,
                "fileName": str(rec.get("fileName") or "").strip(),
                "taskType": str(rec.get("taskType") or "").strip(),
                "targetVersion": str(
                    rec.get("targetVersion") or rec.get("registrationVersion") or ""
                ).strip(),
                "originKey": str(rec.get("originKey") or "").strip(),
            }
        )
    return out


def apply_previous_preview_edits(
    items: list[dict[str, Any]],
    previous_items: Optional[list[dict[str, Any]]] = None,
    deleted_keys: Optional[list[Any]] = None,
    *,
    manual_edited: bool = False,
) -> tuple[list[dict[str, Any]], list[list[str]]]:
    """把上次预览的手工增删改合并进本次规则结果。

    - 未手工编辑：只回填记录状态，规则清单保持完整。
    - 已手工编辑：保留上次快照中的增改，跳过已删除键；规则新增项仍会补入。
    """
    prev_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in previous_items or []:
        if not isinstance(row, dict):
            continue
        cleaned = split_legacy_file_version_alias(row)
        prev_map[_task_dedupe_key(cleaned)] = cleaned
    deleted: set[tuple[str, str, str]] = set()
    for raw in deleted_keys or []:
        parsed = _parse_dedupe_key(raw)
        if parsed:
            deleted.add(parsed)

    if manual_edited and not deleted:
        generated_keys = {_task_dedupe_key(item) for item in items}
        deleted = generated_keys - set(prev_map)

    if not manual_edited:
        out: list[dict[str, Any]] = []
        for item in items:
            rec = dict(item)
            prev = split_legacy_file_version_alias(prev_map.get(_task_dedupe_key(rec), {}))
            rec["recordStatus"] = prev.get("recordStatus", "adopt")
            rec["recordStatus"] = normalize_record_status(rec.get("recordStatus"))
            rec["isSystemRecord"] = normalize_is_system_record(
                prev.get("isSystemRecord") if "isSystemRecord" in prev else rec.get("isSystemRecord"),
                default=False,
            )
            if not str(rec.get("documentNumber") or "").strip() and prev.get("documentNumber"):
                rec["documentNumber"] = prev.get("documentNumber")
            if not str(rec.get("fileVersion") or "").strip() and prev.get("fileVersion"):
                rec["fileVersion"] = prev.get("fileVersion")
            out.append(rec)
        return out, [_serialize_dedupe_key(k) for k in sorted(deleted)]

    out = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = _task_dedupe_key(item)
        if key in deleted:
            continue
        if key in prev_map:
            rec = dict(prev_map[key])
        else:
            rec = dict(item)
            rec["recordStatus"] = "adopt"
        rec["recordStatus"] = normalize_record_status(rec.get("recordStatus"))
        rec["isSystemRecord"] = normalize_is_system_record(rec.get("isSystemRecord"), default=False)
        out.append(rec)
        seen.add(key)
    for key, rec in prev_map.items():
        if key in seen or key in deleted:
            continue
        added = dict(rec)
        added["recordStatus"] = normalize_record_status(added.get("recordStatus"))
        added["isSystemRecord"] = normalize_is_system_record(added.get("isSystemRecord"), default=False)
        out.append(added)
    return out, [_serialize_dedupe_key(k) for k in sorted(deleted)]


def apply_previous_record_status(
    items: list[dict[str, Any]],
    previous_items: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    merged, _ = apply_previous_preview_edits(
        items, previous_items, None, manual_edited=False
    )
    return merged


def generate_task_preview(
    *,
    from_version: str,
    to_version: str,
    intermediate_versions: Optional[list[str]],
    version_release_dates: dict[str, Any],
    feedback_rows: Optional[list[VersionTaskGenerationFeedback]] = None,
    registration_country: str = "",
    previous_items: Optional[list[dict[str, Any]]] = None,
    previous_deleted_keys: Optional[list[Any]] = None,
    previous_manual_edited: bool = False,
    org_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    # 再次「生成预览」按规则重建：不把上次删除套回去。刷新页面只读已保存快照。
    _ = previous_deleted_keys
    _ = previous_manual_edited
    chain = parse_version_chain(from_version, to_version, intermediate_versions or [])
    release_dates = normalize_version_release_dates(chain, version_release_dates)
    transitions = build_transitions(chain)
    touched_changes = {
        t["dominantChange"] for t in transitions if t["dominantChange"] in {"X", "Y", "Z", "B"}
    }

    items: list[dict[str, Any]] = []
    route_by_version: dict[str, dict[str, Any]] = {}
    match_lines: list[dict[str, Any]] = []
    for transition in transitions:
        dominant = transition["dominantChange"]
        if dominant not in {"X", "Y", "Z", "B"}:
            continue
        target_version = str(transition["toVersion"])
        route, catalog = catalogs_for_dominant(
            dominant, registration_country=registration_country
        )
        branch = route["processBranch"]
        route_by_version[target_version] = route
        transition["chapter"] = route["chapter"]
        transition["processBranch"] = branch
        transition["processBranchLabel"] = route.get("label") or process_branch_label(branch)
        transition["applicableChapters"] = list(route.get("applicableChapters") or [])
        match_lines.append(
            {
                "version": target_version,
                "fromVersion": transition["fromVersion"],
                "dominantChange": dominant,
                "primaryChapter": route.get("chapter") or "",
                "applicableChapters": list(route.get("applicableChapters") or []),
                "processLabel": route.get("label") or process_branch_label(branch),
                "archiveMarketLabel": route.get("archiveMarketLabel") or "",
                "itemCount": len(catalog),
            }
        )
        anchor_date = _parse_iso_date(release_dates[target_version])
        for task in catalog:
            if dominant not in set(task.get("triggers") or set()):
                continue
            due = anchor_date + timedelta(days=int(task.get("phaseOffsetDays") or 0))
            task_branch = str(task.get("processBranch") or "")
            task_chapter = str(task.get("chapter") or route["chapter"])
            items.append(
                {
                    "taskKey": task["taskKey"],
                    "fileName": task["fileName"],
                    "taskType": task["taskType"],
                    "author": task["author"],
                    "belongingModule": task["belongingModule"],
                    "dueDate": _fmt_date(due),
                    "explanation": task["reason"],
                    "notes": "",
                    "fileVersion": "",
                    "documentNumber": "",
                    "registrationVersion": target_version,
                    "documentDisplayDate": _fmt_date(anchor_date),
                    "targetVersion": target_version,
                    "triggeredBy": [dominant],
                    "transition": f"{transition['fromVersion']} -> {transition['toVersion']}",
                    "chapter": task_chapter,
                    "processBranch": task_branch or branch,
                    "processBranchLabel": process_branch_label(task_branch or branch),
                    "ruleRef": task.get("ruleRef") or "YY-IW-020",
                    "archiveFrequency": task.get("archiveFrequency") or "",
                    "isSystemRecord": False,
                }
            )

    items_by_id: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in items:
        key = _task_dedupe_key(item)
        if key not in items_by_id:
            items_by_id[key] = item
            continue
        existing = items_by_id[key]
        merged_triggers = sorted(
            set((existing.get("triggeredBy") or []) + (item.get("triggeredBy") or []))
        )
        existing["triggeredBy"] = merged_triggers
        # 保留更高优先级备注（流程任务优先于纯归档重复键）
        if str(item.get("taskType") or "").endswith("流程") and not str(
            existing.get("taskType") or ""
        ).endswith("流程"):
            existing.update({k: item[k] for k in item if k != "triggeredBy"})
            existing["triggeredBy"] = merged_triggers
    deduped = list(items_by_id.values())
    deduped.sort(key=lambda x: (x.get("dueDate") or "", x.get("fileName") or ""))

    feedback_hit_count = 0
    if feedback_rows:
        deduped, feedback_hit_count = apply_feedback_rules(deduped, feedback_rows)
    deduped = apply_previous_record_status(deduped, previous_items)
    if org_id:
        deduped, _ = enrich_preview_items_from_document_control(
            deduped, org_id=org_id, project_id=project_id, overwrite=False
        )
    deduped = [annotate_preview_item(x, fresh=True) for x in deduped]

    if intermediate_versions:
        chain_note = "已按提供的中间版本链路逐段推断触发规则。"
    else:
        chain_note = "未提供中间版本，已按起止版本单跳推断触发规则。"
    rule_meta = load_version_task_rules()
    match_steps = list(rule_meta.get("matchSteps") or [])
    rule_source = str(rule_meta.get("ruleSource") or "")
    rule_basis = str(rule_meta.get("ruleBasis") or "")
    explanation = {
        "title": "规则匹配说明",
        "source": rule_source,
        "steps": match_steps,
        "chainNote": chain_note,
        "versions": match_lines,
        "supplementHint": (
            "另请对照公司「发补记录」中同一注册国家与注册类别、且发补日期不晚于今日的历史意见"
            "（含未完成），补充相关文档/章节的复核与整改任务。"
        ),
    }
    note_parts = [
        f"依据：{rule_source}",
        chain_note,
        *[
            f"{row['fromVersion']}→{row['version']} 主导{row['dominantChange']}位："
            f"适用章节「{'、'.join(row.get('applicableChapters') or [])}」"
            f"（主章节 {row.get('primaryChapter') or '-'}，{row.get('itemCount') or 0} 条）"
            for row in match_lines
        ],
        explanation["supplementHint"],
    ]
    note = "\n".join(note_parts)

    return {
        "fromVersion": chain[0].normalized,
        "toVersion": chain[-1].normalized,
        "versionChain": [x.normalized for x in chain],
        "versionReleaseDates": release_dates,
        "transitions": transitions,
        "dominantChanges": sorted(list(touched_changes)),
        "processBranches": [
            {
                "version": ver,
                "chapter": r.get("chapter") or "",
                "branch": r.get("processBranch") or "",
                "label": r.get("label") or process_branch_label(r.get("processBranch") or ""),
                "applicableChapters": list(r.get("applicableChapters") or []),
                "archiveMarketLabel": r.get("archiveMarketLabel") or "",
            }
            for ver, r in sorted(route_by_version.items())
        ],
        "releaseDate": release_dates[chain[-1].normalized],
        "items": deduped,
        "ruleItems": deepcopy(deduped),
        "deletedItems": [],
        "manualDeletedKeys": [],
        "changeLog": [],
        "note": note,
        "explanation": explanation,
        "ruleBasis": rule_basis,
        "ruleSource": rule_source,
        "rulesMode": rule_meta.get("mode") or "",
        "sourceFile": rule_meta.get("sourceFile") or "",
        "sourceVersion": rule_meta.get("sourceVersion") or "",
        "registrationCountry": registration_country or "",
        "feedbackHitCount": feedback_hit_count,
    }


def _safe_date(y: int, m: int, d: int) -> Optional[str]:
    try:
        return _fmt_date(date(y, m, d))
    except Exception:
        return None


def _extract_dates(text: str) -> list[str]:
    out: list[str] = []
    for pattern in DATE_PATTERNS:
        for m in pattern.finditer(text or ""):
            y, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
            parsed = _safe_date(y, mm, dd)
            if parsed:
                out.append(parsed)
    seen = set()
    uniq = []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq


def _parse_duckduckgo_html(html: str) -> tuple[list[dict[str, str]], str]:
    patterns: list[tuple[str, re.Pattern[str]]] = [
        (
            "primary",
            re.compile(
                r'<a[^>]*class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
                r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
                re.S,
            ),
        ),
        (
            "fallback_class",
            re.compile(
                r'<a[^>]*class="[^"]*result[^"]*"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
                re.S,
            ),
        ),
    ]
    out: list[dict[str, str]] = []
    parser = "none"
    for parser_name, block_re in patterns:
        for m in block_re.finditer(html):
            href = unescape(re.sub(r"\s+", " ", m.group("href") or "").strip())
            title = unescape(re.sub(r"<.*?>", "", m.group("title") or "").strip())
            snippet = ""
            if "snippet" in m.groupdict():
                snippet = unescape(re.sub(r"<.*?>", "", m.group("snippet") or "").strip())
            if not href:
                continue
            out.append({"url": href, "title": title, "snippet": snippet})
            if len(out) >= 10:
                break
        if out:
            parser = parser_name
            break
    if not out:
        link_re = re.compile(r'href="(https?://[^"]+)"[^>]*>([^<]{4,120})<', re.I)
        for m in link_re.finditer(html):
            href = unescape(m.group(1).strip())
            title = unescape(re.sub(r"<.*?>", "", m.group(2) or "").strip())
            if "duckduckgo.com" in href:
                continue
            out.append({"url": href, "title": title, "snippet": ""})
            if len(out) >= 8:
                break
        if out:
            parser = "link_fallback"
    return out, parser


def _normalize_proxy_url(proxy: str) -> str:
    """本机代理写成 https://127.0.0.1:端口 时常触发 ProxyError/SSLEOF，归一为 http://。"""
    text = (proxy or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        return text
    host = (parsed.hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"} and (parsed.scheme or "").lower() == "https":
        netloc = parsed.netloc or f"{host}:{parsed.port or 7890}"
        return f"http://{netloc}"
    return text


def _resolve_local_search_proxy() -> Optional[str]:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        val = _normalize_proxy_url(os.environ.get(key) or "")
        if val:
            return val
    return None


def _is_proxy_or_ssl_error(exc: BaseException) -> bool:
    lowered = (str(exc) or "").lower()
    return any(
        key in lowered
        for key in (
            "proxyerror",
            "unable to connect to proxy",
            "ssleoferror",
            "eof occurred in violation of protocol",
            "ssl",
            "certificate",
            "proxy",
        )
    )


def _duckduckgo_search_with_diagnostics(query: str, timeout: float = 12.0) -> tuple[list[dict[str, str]], dict[str, Any]]:
    urls = [tpl.format(query=quote(query)) for tpl in _DDG_URL_TEMPLATES]
    proxy = _resolve_local_search_proxy()
    diagnostics: dict[str, Any] = {
        "url": urls[0] if urls else "",
        "httpStatus": None,
        "htmlBytes": 0,
        "parser": "none",
        "rawHits": 0,
        "networkError": None,
        "durationMs": 0,
        "proxyConfigured": bool(proxy),
        "proxyNormalized": proxy or "",
        "attempts": [],
    }
    started = time.time()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    attempts: list[dict[str, Any]] = []
    if proxy:
        attempts.append({"proxies": {"http": proxy, "https": proxy}, "verify": True, "label": "proxy"})
        attempts.append({"proxies": {"http": proxy, "https": proxy}, "verify": False, "label": "proxy_insecure"})
    # 关闭 trust_env，避免系统坏代理反复注入；失败后再直连
    attempts.append({"proxies": {}, "verify": True, "label": "direct"})
    attempts.append({"proxies": {}, "verify": False, "label": "direct_insecure"})

    html = ""
    last_err: Optional[str] = None
    for url in urls:
        for attempt in attempts:
            label = str(attempt["label"])
            try:
                with requests.Session() as sess:
                    sess.trust_env = False
                    resp = sess.get(
                        url,
                        headers=headers,
                        timeout=timeout,
                        proxies=attempt.get("proxies") or {},
                        verify=bool(attempt.get("verify")),
                    )
                diagnostics["httpStatus"] = resp.status_code
                resp.raise_for_status()
                html = resp.text
                diagnostics["url"] = url
                diagnostics["attemptUsed"] = label
                diagnostics["attempts"].append({"label": label, "ok": True, "status": resp.status_code})
                last_err = None
                break
            except Exception as exc:
                err = str(exc)
                last_err = err
                diagnostics["attempts"].append({"label": label, "ok": False, "error": err[:240]})
                if not _is_proxy_or_ssl_error(exc) and "timeout" not in err.lower():
                    break
        if html:
            break

    if not html:
        diagnostics["networkError"] = last_err or "DuckDuckGo 请求失败"
        diagnostics["durationMs"] = int((time.time() - started) * 1000)
        diagnostics["failureHint"] = (
            "本地回退检索失败。请优先保证文档服务（aicheckword）可调用；"
            "发布时间检索会复用那边 Cursor/LLM 已配置的代理，无需在本页再配一遍"
        )
        return [], diagnostics

    diagnostics["htmlBytes"] = len(html.encode("utf-8", errors="ignore"))
    out, parser = _parse_duckduckgo_html(html)
    diagnostics["parser"] = parser
    diagnostics["rawHits"] = len(out)
    diagnostics["durationMs"] = int((time.time() - started) * 1000)
    return out, diagnostics


def _build_candidates_from_results(
    *,
    version: str,
    results: list[dict[str, str]],
    include_skipped: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for row in results:
        text = f"{row.get('title', '')} {row.get('snippet', '')}"
        dates = _extract_dates(text)
        if not dates:
            skipped.append(
                {
                    "title": str(row.get("title") or "")[:120],
                    "reason": "snippet中未匹配到日期",
                }
            )
            continue
        candidates.append(
            {
                "version": version,
                "date": dates[0],
                "sourceUrl": row.get("url") or "",
                "sourceTitle": row.get("title") or "",
                "snippet": row.get("snippet") or "",
                "confidence": "low",
            }
        )
    dedup: dict[str, dict[str, Any]] = {}
    for c in candidates:
        if c["date"] not in dedup:
            dedup[c["date"]] = c
    ordered = sorted(dedup.values(), key=lambda x: x["date"], reverse=True)
    extraction: dict[str, Any] = {
        "rowsScanned": len(results),
        "rowsWithDate": len(candidates),
        "rowsSkippedNoDate": len(skipped),
        "candidateCount": len(ordered),
    }
    if include_skipped:
        extraction["skippedSamples"] = skipped[:5]
    if not results:
        extraction["failureHint"] = "DuckDuckGo 页面未解析到搜索结果，可能为网络拦截或 HTML 结构变更"
    elif results and not ordered:
        extraction["failureHint"] = "已解析到搜索结果，但标题/摘要中未提取到 20xx 日期"
    return ordered[:5], extraction


def _duckduckgo_search(query: str, timeout: float = 12.0) -> list[dict[str, str]]:
    results, _ = _duckduckgo_search_with_diagnostics(query, timeout=timeout)
    return results


def _suggest_release_date_for_version(
    *,
    product_name: str,
    version: str,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    terms = [x for x in [product_name.strip(), version.strip(), "发布", "版本"] if x]
    query = " ".join(terms) if terms else f"{version} 版本 发布时间"
    results, ddg_diag = _duckduckgo_search_with_diagnostics(query)
    if ddg_diag.get("networkError"):
        hint = str(ddg_diag.get("failureHint") or "").strip()
        err = str(ddg_diag.get("networkError") or "").strip()
        message = f"联网检索失败：{hint or err}"
        if hint and err and hint not in err:
            message = f"联网检索失败：{hint}（{err[:180]}）"
        payload: dict[str, Any] = {
            "version": version,
            "query": query,
            "candidates": [],
            "message": message,
        }
        if include_diagnostics:
            payload["diagnostics"] = {
                "duckduckgo": ddg_diag,
                "dateExtraction": {
                    "rowsScanned": 0,
                    "rowsWithDate": 0,
                    "rowsSkippedNoDate": 0,
                    "candidateCount": 0,
                    "failureHint": hint or "网络请求失败",
                },
            }
        return payload

    ordered, extraction = _build_candidates_from_results(
        version=version,
        results=results,
        include_skipped=include_diagnostics,
    )
    payload = {
        "version": version,
        "query": query,
        "candidates": ordered,
        "message": (
            "已检索到候选日期，请人工确认后采用。"
            if ordered
            else "未检索到该版本发布时间，请手动填写。"
        ),
    }
    if include_diagnostics:
        payload["diagnostics"] = {"duckduckgo": ddg_diag, "dateExtraction": extraction}
    return payload


def suggest_release_dates(
    *,
    product_name: str,
    from_version: str,
    to_version: str,
    intermediate_versions: Optional[list[str]] = None,
    target_version: Optional[str] = None,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    chain = parse_version_chain(from_version, to_version, intermediate_versions or [])
    versions = [x.normalized for x in chain]
    targets = versions
    if target_version:
        normalized = parse_version(target_version).normalized
        if normalized not in versions:
            raise ValueError(f"目标版本 {target_version} 不在版本链路中")
        targets = [normalized]

    per_version: list[dict[str, Any]] = []
    all_candidates: list[dict[str, Any]] = []
    for version in targets:
        result = _suggest_release_date_for_version(
            product_name=product_name,
            version=version,
            include_diagnostics=include_diagnostics,
        )
        per_version.append(result)
        for candidate in result.get("candidates") or []:
            all_candidates.append(candidate)

    summary: Optional[dict[str, Any]] = None
    if include_diagnostics:
        summary = {
            "versionCount": len(targets),
            "candidateCount": len(all_candidates),
            "versionsWithCandidates": sum(1 for x in per_version if (x.get("candidates") or [])),
            "totalRawHits": sum(
                int((x.get("diagnostics") or {}).get("duckduckgo", {}).get("rawHits") or 0)
                for x in per_version
            ),
        }
        if summary["candidateCount"] == 0 and summary["totalRawHits"] == 0:
            summary["failureHint"] = "未检索到发布时间，请检查外网或手动填写"
        elif summary["candidateCount"] == 0 and summary["totalRawHits"] > 0:
            summary["failureHint"] = "已命中搜索结果但未提取到日期，请手动填写"

    return {
        "fromVersion": chain[0].normalized,
        "toVersion": chain[-1].normalized,
        "versionChain": versions,
        "targetVersion": target_version or None,
        "perVersion": per_version,
        "candidates": all_candidates[:10],
        "message": (
            "已检索到候选发布时间，请人工确认后采用。"
            if all_candidates
            else "未检索到发布时间，请手动填写。"
        ),
        "source": "local",
        "diagnostics": summary,
    }


def diagnose_release_dates(
    *,
    product_name: str,
    from_version: str,
    to_version: str,
    intermediate_versions: Optional[list[str]] = None,
    target_version: Optional[str] = None,
) -> dict[str, Any]:
    result = suggest_release_dates(
        product_name=product_name,
        from_version=from_version,
        to_version=to_version,
        intermediate_versions=intermediate_versions,
        target_version=target_version,
        include_diagnostics=True,
    )
    result["mode"] = "diagnose"
    return result


CHANGE_FIELD_LABELS = {
    "fileName": "文件名",
    "documentNumber": "文件编号",
    "fileVersion": "文件版本号",
    "taskType": "任务类型",
    "targetVersion": "目标版本",
    "author": "责任人",
    "dueDate": "完成日期",
    "documentDisplayDate": "文档日期",
    "belongingModule": "模块",
    "explanation": "说明",
    "notes": "备注",
    "recordStatus": "状态",
    "chapter": "章节分类",
    "isSystemRecord": "体系记录",
}

RECORD_STATUS_LABELS = {
    "adopt": "选用",
    "discard": "弃用",
    "pending": "待定",
}


def summarize_item_diff(
    original: Optional[dict[str, Any]],
    adjusted: Optional[dict[str, Any]],
) -> list[dict[str, str]]:
    before = split_legacy_file_version_alias(original) if isinstance(original, dict) else {}
    after = split_legacy_file_version_alias(adjusted) if isinstance(adjusted, dict) else {}
    out: list[dict[str, str]] = []
    for key, label in CHANGE_FIELD_LABELS.items():
        left = str(before.get(key) or "").strip()
        right = str(after.get(key) or "").strip()
        if key == "targetVersion":
            left = left or str(before.get("registrationVersion") or "").strip()
            right = right or str(after.get("registrationVersion") or "").strip()
        if key == "recordStatus":
            left = RECORD_STATUS_LABELS.get(normalize_record_status(left), left)
            right = RECORD_STATUS_LABELS.get(normalize_record_status(right), right)
        if key == "chapter":
            left = left or str(before.get("processBranchLabel") or "").strip()
            right = right or str(after.get("processBranchLabel") or "").strip()
        if key == "isSystemRecord":
            left = "是" if normalize_is_system_record(before.get("isSystemRecord"), default=False) else "否"
            right = "是" if normalize_is_system_record(after.get("isSystemRecord"), default=False) else "否"
        if left == right:
            continue
        out.append({"field": key, "label": label, "from": left, "to": right})
    return out


def _summary_is_legacy_file_version_only(summary: Any) -> bool:
    if not isinstance(summary, list) or not summary:
        return False
    for row in summary:
        if not isinstance(row, dict):
            return False
        field = str(row.get("field") or "").strip()
        if field != "fileVersion":
            return False
        frm = str(row.get("from") or "").strip()
        to = str(row.get("to") or "").strip()
        if to or not _looks_like_software_version(frm):
            return False
    return True


def is_legacy_file_version_alias_feedback(row: VersionTaskGenerationFeedback) -> bool:
    """旧逻辑把目标版本写进 fileVersion，再对比成「2.1.0.0→空」的误采集。"""
    kind = str(getattr(row, "adjust_type", "") or "").strip().lower()
    if kind not in {"update", "replace"}:
        return False
    original = row.original_item_json if isinstance(row.original_item_json, dict) else {}
    adjusted = row.adjusted_item_json if isinstance(row.adjusted_item_json, dict) else {}
    if summarize_item_diff(original, adjusted):
        return False
    summary = row.change_summary_json
    if _summary_is_legacy_file_version_only(summary):
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
    return bool(
        orig_fv
        and not adj_fv
        and _looks_like_software_version(orig_fv)
        and orig_fv == tv
    )


def purge_legacy_file_version_alias_feedbacks(
    *,
    org_id: Optional[str] = None,
    project_id: Optional[str] = None,
    commit: bool = True,
) -> dict[str, Any]:
    query = VersionTaskGenerationFeedback.query
    if org_id:
        query = query.filter_by(organization_id=org_id)
    pid = str(project_id or "").strip()
    if pid:
        query = query.filter_by(project_id=pid)
    removed_ids: list[str] = []
    for row in query.all():
        if not is_legacy_file_version_alias_feedback(row):
            continue
        removed_ids.append(str(row.id))
        db.session.delete(row)
    if removed_ids and commit:
        db.session.commit()
    elif removed_ids:
        db.session.flush()
    return {"removed": len(removed_ids), "ids": removed_ids}


def serialize_version_task_feedback(row: VersionTaskGenerationFeedback) -> dict[str, Any]:
    original = row.original_item_json if isinstance(row.original_item_json, dict) else {}
    adjusted = row.adjusted_item_json if isinstance(row.adjusted_item_json, dict) else {}
    src = adjusted or original
    summary = row.change_summary_json if isinstance(row.change_summary_json, list) else []
    if not summary and row.adjust_type in {"update", "replace"}:
        summary = summarize_item_diff(original, adjusted)
    reason = str(row.reason or "").strip()
    if not reason:
        reason = str(src.get("changeReason") or original.get("changeReason") or "").strip()
    return {
        "id": row.id,
        "type": row.adjust_type or "",
        "typeLabel": {"add": "新增", "update": "已修改", "replace": "已修改", "delete": "已删除"}.get(
            str(row.adjust_type or "").strip().lower(), row.adjust_type or ""
        ),
        "reason": reason,
        "changeSummary": summary,
        "fileName": str(src.get("fileName") or original.get("fileName") or "").strip(),
        "taskType": str(src.get("taskType") or original.get("taskType") or "").strip(),
        "targetVersion": str(
            src.get("targetVersion")
            or original.get("targetVersion")
            or src.get("registrationVersion")
            or original.get("registrationVersion")
            or ""
        ).strip(),
        "createdAt": row.created_at.isoformat() if row.created_at else "",
        "sourceJobId": row.source_job_id or "",
        "projectId": row.project_id or "",
    }


def list_version_task_feedbacks(
    *,
    org_id: str,
    project_id: Optional[str] = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    query = VersionTaskGenerationFeedback.query.filter_by(organization_id=org_id)
    pid = str(project_id or "").strip()
    if pid:
        query = query.filter_by(project_id=pid)
    purge_legacy_file_version_alias_feedbacks(
        org_id=org_id, project_id=pid or None, commit=True
    )
    rows = (
        query.order_by(VersionTaskGenerationFeedback.created_at.desc())
        .limit(max(1, min(int(limit or 80), 200)))
        .all()
    )
    return [
        serialize_version_task_feedback(row)
        for row in rows
        if not is_legacy_file_version_alias_feedback(row)
    ]


def feedback_rows_for_org(org_id: str) -> list[VersionTaskGenerationFeedback]:
    rows = (
        VersionTaskGenerationFeedback.query.filter_by(organization_id=org_id)
        .order_by(VersionTaskGenerationFeedback.created_at.desc())
        .limit(200)
        .all()
    )
    return [row for row in rows if not is_legacy_file_version_alias_feedback(row)]


def build_adjustment_rows(
    *,
    org_id: str,
    source_job_id: Optional[str],
    project_id: Optional[str],
    adjustments: list[dict[str, Any]],
) -> list[VersionTaskGenerationFeedback]:
    rows: list[VersionTaskGenerationFeedback] = []
    for item in adjustments:
        kind = (str(item.get("type") or "update").strip().lower()) or "update"
        if kind not in {"add", "delete", "update", "replace"}:
            continue
        original = item.get("originalItem")
        adjusted = item.get("adjustedItem")
        reason = str(item.get("reason") or "").strip()[:512]
        summary = item.get("changeSummary")
        if not isinstance(summary, list):
            summary = summarize_item_diff(
                original if isinstance(original, dict) else None,
                adjusted if isinstance(adjusted, dict) else None,
            )
        original_copy = dict(original) if isinstance(original, dict) else None
        adjusted_copy = dict(adjusted) if isinstance(adjusted, dict) else None
        if reason:
            if adjusted_copy is None and kind == "delete":
                original_copy = original_copy or {}
                original_copy["changeReason"] = reason
            elif adjusted_copy is not None:
                adjusted_copy["changeReason"] = reason
        rows.append(
            VersionTaskGenerationFeedback(
                organization_id=org_id,
                source_job_id=source_job_id or None,
                project_id=project_id or None,
                adjust_type=kind,
                original_item_json=original_copy,
                adjusted_item_json=adjusted_copy,
                reason=reason or None,
                change_summary_json=summary or None,
                applied_count=0,
                last_applied_at=None,
            )
        )
    return rows


def touch_feedback_hits(rows: list[VersionTaskGenerationFeedback]) -> None:
    now = now_local()
    for row in rows:
        row.applied_count = int(row.applied_count or 0) + 1
        row.last_applied_at = now


def _generation_status_rank(status: str) -> int:
    mapping = {"none": 0, "previewed": 1, "generated": 2}
    return mapping.get((status or "").strip().lower(), 0)


def serialize_project_version_record(row: ProjectVersionRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "projectId": row.project_id,
        "version": row.version,
        "releasedAt": _fmt_date(row.released_at) if row.released_at else "",
        "productName": row.product_name or "",
        "chainFromVersion": row.chain_from_version or "",
        "chainToVersion": row.chain_to_version or "",
        "generationStatus": row.generation_status or "none",
        "lastJobId": row.last_job_id or "",
        "updatedAt": row.updated_at.isoformat() if row.updated_at else "",
    }


def _version_sort_key(raw: str) -> tuple[int, int, int, int]:
    p = parse_version(raw)
    return (p.x, p.y, p.z, p.b)


def list_project_version_records(
    *,
    org_id: str,
    project_id: str,
) -> list[dict[str, Any]]:
    rows = (
        ProjectVersionRecord.query.filter_by(organization_id=org_id, project_id=project_id)
        .all()
    )
    rows.sort(key=lambda r: _version_sort_key(r.version))
    return [serialize_project_version_record(x) for x in rows]


def latest_version_record_project_id(*, org_id: str) -> str:
    """最近更新过版本记录的项目，供刷新后无预览时回填项目选择。"""
    row = (
        ProjectVersionRecord.query.filter_by(organization_id=org_id)
        .order_by(ProjectVersionRecord.updated_at.desc())
        .first()
    )
    return str(row.project_id or "").strip() if row else ""


def get_project_version_record(
    *,
    org_id: str,
    record_id: str,
) -> Optional[ProjectVersionRecord]:
    row = ProjectVersionRecord.query.filter_by(id=record_id, organization_id=org_id).first()
    return row


def delete_project_version_record(*, org_id: str, record_id: str) -> bool:
    row = get_project_version_record(org_id=org_id, record_id=record_id)
    if not row:
        return False
    db.session.delete(row)
    return True


def _related_project_version_records(
    *,
    org_id: str,
    source: ProjectVersionRecord,
) -> list[ProjectVersionRecord]:
    """同一源项目下的相关版本记录：优先同链路，否则整项目版本组。"""
    rows = (
        ProjectVersionRecord.query.filter_by(
            organization_id=org_id, project_id=source.project_id
        ).all()
    )
    chain_from = (source.chain_from_version or "").strip()
    chain_to = (source.chain_to_version or "").strip()
    if chain_from and chain_to:
        same_chain = [
            r
            for r in rows
            if (r.chain_from_version or "").strip() == chain_from
            and (r.chain_to_version or "").strip() == chain_to
        ]
        if same_chain:
            return same_chain
    return rows


def rebind_project_version_records(
    *,
    org_id: str,
    record_id: str,
    target_project_id: str,
    version: str = "",
    released_at: Optional[str] = None,
    product_name: str = "",
    chain_from_version: str = "",
    chain_to_version: str = "",
    generation_status: str = "",
    allow_downgrade_status: bool = True,
) -> dict[str, Any]:
    """
    保存单条版本记录；若关联项目变更，则同步把相关版本记录与预览批次改绑到新项目。
    """
    source = get_project_version_record(org_id=org_id, record_id=record_id)
    if not source:
        raise ValueError("未找到版本记录")
    old_project_id = source.project_id
    target_project_id = (target_project_id or "").strip()
    if not target_project_id:
        raise ValueError("projectId 不能为空")

    related = _related_project_version_records(org_id=org_id, source=source)
    related_ids = {r.id for r in related}
    moved_jobs = 0

    if old_project_id != target_project_id:
        # 目标项目已有同版本号则拒绝整组改绑
        for r in related:
            conflict = ProjectVersionRecord.query.filter_by(
                project_id=target_project_id, version=r.version
            ).first()
            if conflict and conflict.id not in related_ids:
                raise ValueError(
                    f"目标项目已存在版本 {r.version}，无法同步改绑相关记录"
                )
        for r in related:
            r.project_id = target_project_id
            r.organization_id = org_id

        job_ids = {str(r.last_job_id).strip() for r in related if (r.last_job_id or "").strip()}
        chain_from = (source.chain_from_version or "").strip()
        chain_to = (source.chain_to_version or "").strip()
        jobs = VersionTaskGenerationJob.query.filter_by(
            organization_id=org_id, project_id=old_project_id
        ).all()
        for job in jobs:
            should_move = False
            if job.id and job.id in job_ids:
                should_move = True
            elif chain_from and chain_to:
                if (job.from_version or "") == chain_from and (job.to_version or "") == chain_to:
                    should_move = True
            if should_move:
                job.project_id = target_project_id
                moved_jobs += 1

    item = save_project_version_record_item(
        org_id=org_id,
        project_id=target_project_id,
        record_id=record_id,
        version=version or source.version,
        released_at=released_at,
        product_name=product_name,
        chain_from_version=chain_from_version,
        chain_to_version=chain_to_version,
        generation_status=generation_status,
        allow_downgrade_status=allow_downgrade_status,
    )
    moved_items = [serialize_project_version_record(r) for r in related]
    # related 已在 session 中更新；主记录以 save 结果为准刷新
    for idx, r in enumerate(moved_items):
        if r.get("id") == item.get("id"):
            moved_items[idx] = item
            break
    else:
        moved_items.append(item)

    return {
        "item": item,
        "moved": old_project_id != target_project_id,
        "fromProjectId": old_project_id,
        "toProjectId": target_project_id,
        "movedRecordCount": len({x.get("id") for x in moved_items if x.get("id")}),
        "movedJobCount": moved_jobs,
        "movedItems": moved_items,
    }


def batch_save_project_version_records(
    *,
    org_id: str,
    items: list[dict[str, Any]],
    chain_from_version: str = "",
    chain_to_version: str = "",
) -> dict[str, Any]:
    """批量保存版本记录；若有关联项目变更，先按组改绑再逐条落字段。"""
    if not isinstance(items, list) or not items:
        raise ValueError("items 不能为空")

    prepared: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {idx + 1} 条格式无效")
        project_id = str(raw.get("projectId") or "").strip()
        version_raw = str(raw.get("version") or "").strip()
        if not project_id:
            raise ValueError(f"第 {idx + 1} 条缺少关联项目")
        if not version_raw:
            raise ValueError(f"第 {idx + 1} 条版本号不能为空")
        version = parse_version(version_raw).normalized
        key = (project_id, version)
        if key in seen_keys:
            raise ValueError(f"批量数据中目标项目下版本 {version} 重复")
        seen_keys.add(key)
        prepared.append(
            {
                "id": str(raw.get("id") or "").strip(),
                "projectId": project_id,
                "version": version,
                "releasedAt": str(raw.get("releasedAt") or "").strip(),
                "productName": str(raw.get("productName") or "").strip(),
                "generationStatus": str(raw.get("generationStatus") or "none").strip().lower(),
                "chainFromVersion": str(
                    raw.get("chainFromVersion") or chain_from_version or ""
                ).strip(),
                "chainToVersion": str(
                    raw.get("chainToVersion") or chain_to_version or ""
                ).strip(),
            }
        )

    moved = False
    moved_job_count = 0
    moved_record_count = 0
    already_rebound: set[str] = set()
    for item in prepared:
        record_id = item["id"]
        if not record_id or record_id in already_rebound:
            continue
        row = get_project_version_record(org_id=org_id, record_id=record_id)
        if not row:
            raise ValueError(f"未找到版本记录：{record_id}")
        if row.project_id == item["projectId"]:
            continue
        result = rebind_project_version_records(
            org_id=org_id,
            record_id=record_id,
            target_project_id=item["projectId"],
            version=item["version"],
            released_at=item["releasedAt"],
            product_name=item["productName"],
            chain_from_version=item["chainFromVersion"],
            chain_to_version=item["chainToVersion"],
            generation_status=item["generationStatus"],
            allow_downgrade_status=True,
        )
        moved = moved or bool(result.get("moved"))
        moved_job_count += int(result.get("movedJobCount") or 0)
        moved_record_count = max(
            moved_record_count, int(result.get("movedRecordCount") or 0)
        )
        for moved_item in result.get("movedItems") or []:
            mid = str(moved_item.get("id") or "").strip()
            if mid:
                already_rebound.add(mid)

    saved_items: list[dict[str, Any]] = []
    for item in prepared:
        saved_items.append(
            save_project_version_record_item(
                org_id=org_id,
                project_id=item["projectId"],
                record_id=item["id"] or None,
                version=item["version"],
                released_at=item["releasedAt"],
                product_name=item["productName"],
                chain_from_version=item["chainFromVersion"],
                chain_to_version=item["chainToVersion"],
                generation_status=item["generationStatus"],
                allow_downgrade_status=True,
            )
        )

    return {
        "saved": len(saved_items),
        "items": saved_items,
        "moved": moved,
        "movedRecordCount": moved_record_count,
        "movedJobCount": moved_job_count,
    }


def save_project_version_record_item(
    *,
    org_id: str,
    project_id: str,
    version: str,
    released_at: Optional[str] = None,
    product_name: str = "",
    chain_from_version: str = "",
    chain_to_version: str = "",
    generation_status: str = "",
    job_id: Optional[str] = None,
    record_id: Optional[str] = None,
    allow_downgrade_status: bool = True,
) -> dict[str, Any]:
    normalized = parse_version(version).normalized
    row: Optional[ProjectVersionRecord] = None
    if record_id:
        row = get_project_version_record(org_id=org_id, record_id=record_id)
        if not row:
            raise ValueError("未找到版本记录")
    if row is None:
        row = ProjectVersionRecord.query.filter_by(project_id=project_id, version=normalized).first()
    if row is None:
        row = ProjectVersionRecord(
            organization_id=org_id,
            project_id=project_id,
            version=normalized,
        )
        db.session.add(row)
    elif row.project_id != project_id or row.version != normalized:
        conflict = ProjectVersionRecord.query.filter_by(
            project_id=project_id, version=normalized
        ).first()
        if conflict and conflict.id != row.id:
            raise ValueError(f"目标项目已存在版本 {normalized}")
        row.version = normalized
        row.project_id = project_id
    row.organization_id = org_id
    row.project_id = project_id
    # None = 不修改；空串 = 清空；非空 = 写入日期
    if released_at is not None:
        if str(released_at).strip() == "":
            row.released_at = None
        else:
            row.released_at = _parse_iso_date(str(released_at).strip())
    if product_name:
        row.product_name = product_name.strip()
    if chain_from_version:
        row.chain_from_version = parse_version(chain_from_version).normalized
    if chain_to_version:
        row.chain_to_version = parse_version(chain_to_version).normalized
    next_status = (generation_status or "").strip().lower()
    if next_status:
        current_status = (row.generation_status or "none").strip().lower()
        if allow_downgrade_status or _generation_status_rank(next_status) >= _generation_status_rank(current_status):
            row.generation_status = next_status
    elif not row.generation_status:
        row.generation_status = "none"
    if job_id:
        row.last_job_id = job_id
    return serialize_project_version_record(row)


def upsert_project_version_records(
    *,
    org_id: str,
    project_id: str,
    version_release_dates: dict[str, Any],
    product_name: str = "",
    chain_from_version: str = "",
    chain_to_version: str = "",
    generation_status: str = "",
    job_id: Optional[str] = None,
    allow_downgrade_status: bool = False,
) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    for raw_version, raw_date in (version_release_dates or {}).items():
        version = parse_version(str(raw_version or "").strip()).normalized
        released = _parse_iso_date(str(raw_date or "").strip()) if str(raw_date or "").strip() else None
        row = ProjectVersionRecord.query.filter_by(project_id=project_id, version=version).first()
        if not row:
            row = ProjectVersionRecord(
                organization_id=org_id,
                project_id=project_id,
                version=version,
            )
            db.session.add(row)
        row.organization_id = org_id
        if released:
            row.released_at = released
        if product_name:
            row.product_name = product_name.strip()
        if chain_from_version:
            row.chain_from_version = parse_version(chain_from_version).normalized
        if chain_to_version:
            row.chain_to_version = parse_version(chain_to_version).normalized
        next_status = (generation_status or "").strip().lower()
        if next_status:
            current_status = (row.generation_status or "none").strip().lower()
            if allow_downgrade_status or _generation_status_rank(next_status) >= _generation_status_rank(current_status):
                row.generation_status = next_status
        if job_id:
            row.last_job_id = job_id
        saved.append(serialize_project_version_record(row))
    return saved


def resolve_project_product_name(*, org_id: str, project_id: str) -> str:
    """从版本记录或最近预览批次解析应用市场产品名。"""
    pid = (project_id or "").strip()
    if not pid:
        return ""
    for row in list_project_version_records(org_id=org_id, project_id=pid):
        name = str(row.get("productName") or "").strip()
        if name:
            return name
    job = (
        VersionTaskGenerationJob.query.filter_by(organization_id=org_id, project_id=pid)
        .order_by(VersionTaskGenerationJob.updated_at.desc())
        .first()
    )
    if not job:
        return ""
    snap = job.rule_snapshot_json if isinstance(job.rule_snapshot_json, dict) else {}
    name = str(snap.get("productName") or "").strip()
    if name:
        return name
    preview = job.preview_json if isinstance(job.preview_json, dict) else {}
    return str(preview.get("productName") or "").strip()


def set_project_product_name(
    *,
    org_id: str,
    project_id: str,
    product_name: str,
) -> dict[str, Any]:
    """把应用市场产品名写回该项目的版本记录与预览批次。"""
    pid = (project_id or "").strip()
    name = (product_name or "").strip()
    if not pid:
        raise ValueError("projectId 不能为空")
    updated_records = 0
    for row in ProjectVersionRecord.query.filter_by(
        organization_id=org_id, project_id=pid
    ).all():
        row.product_name = name or None
        updated_records += 1
    updated_jobs = 0
    for job in VersionTaskGenerationJob.query.filter_by(
        organization_id=org_id, project_id=pid
    ).all():
        snap = dict(job.rule_snapshot_json) if isinstance(job.rule_snapshot_json, dict) else {}
        snap["productName"] = name
        job.rule_snapshot_json = snap
        if isinstance(job.preview_json, dict):
            preview = dict(job.preview_json)
            preview["productName"] = name
            job.preview_json = preview
        updated_jobs += 1
    return {
        "projectId": pid,
        "productName": name,
        "updatedRecords": updated_records,
        "updatedJobs": updated_jobs,
    }


def stamp_manual_preview_items(
    preview: Optional[dict[str, Any]],
    items: list[dict[str, Any]],
    *,
    recompute_keys: Optional[set[str]] = None,
) -> dict[str, Any]:
    """把当前预览行写入快照，并记录手工删除键。

    recompute_keys 不为 None 时，只重算这些 originKey 的变更标记，其余行原样保留。
    """
    out = dict(preview) if isinstance(preview, dict) else {}
    cleaned_items: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        key = _origin_key_of(raw)
        if recompute_keys is None or key in recompute_keys or not key:
            cleaned_items.append(annotate_preview_item(raw, fresh=False))
        else:
            cleaned_items.append(raw)

    rule_raw = out.get("ruleItems") if isinstance(out.get("ruleItems"), list) else []
    if recompute_keys is None or not rule_raw:
        rule_items = [annotate_preview_item(x, fresh=True) for x in rule_raw if isinstance(x, dict)]
        if not rule_items:
            rule_items = [
                annotate_preview_item(x, fresh=True)
                for x in cleaned_items
                if str(x.get("changeKind") or "") not in {"add", "delete"}
            ]
    else:
        rule_items = [
            split_legacy_file_version_alias(x) for x in rule_raw if isinstance(x, dict)
        ]
    rule_map = {_origin_key_of(x): x for x in rule_items}
    rule_by_dedupe = {_task_dedupe_key(x): x for x in rule_items}

    def _rule_baseline(rec: dict[str, Any]) -> Optional[dict[str, Any]]:
        hit = rule_map.get(_origin_key_of(rec))
        if hit:
            return hit
        return rule_by_dedupe.get(_task_dedupe_key(rec))

    for rec in cleaned_items:
        key = _origin_key_of(rec)
        if recompute_keys is not None and key not in recompute_keys:
            continue
        kind = str(rec.get("changeKind") or "")
        if kind == "update":
            rec["changeFields"] = summarize_item_diff(_rule_baseline(rec), rec)
            if not rec["changeFields"]:
                rec["changeKind"] = ""
        elif kind in {"add", "delete"} and not rec.get("changeFields"):
            rec["changeFields"] = []

    prev_rows = [
        x
        for x in list(out.get("items") or []) + list(out.get("deletedItems") or [])
        if isinstance(x, dict)
    ]
    deleted_now = {
        _task_dedupe_key(x)
        for x in cleaned_items
        if _preview_row_is_deleted(x)
    }
    prev_deleted = collect_deleted_dedupe_keys(prev_rows, out.get("manualDeletedKeys"))
    live_keys = {
        _task_dedupe_key(x)
        for x in cleaned_items
        if not _preview_row_is_deleted(x)
    }
    merged_deleted = (prev_deleted | deleted_now) - live_keys
    seen_keys = {_task_dedupe_key(x) for x in cleaned_items}
    for rec in prev_rows:
        key = _task_dedupe_key(rec)
        if key in merged_deleted and key not in seen_keys:
            cleaned_items.append(_mark_preview_row_deleted(rec))
            seen_keys.add(key)
    for rec in cleaned_items:
        if _task_dedupe_key(rec) in merged_deleted:
            rec["changeKind"] = "delete"
            rec["hideInPreview"] = True
    out["ruleItems"] = rule_items
    out["editedAt"] = now_local().isoformat()
    out["manualEdited"] = True
    out["manualDeletedKeys"] = [_serialize_dedupe_key(k) for k in sorted(merged_deleted)]
    split = split_preview_live_and_deleted({**out, "items": cleaned_items})
    out.update(split)
    out["changeLog"] = preview_change_log_from_items(
        list(out.get("items") or []) + list(out.get("deletedItems") or [])
    )
    return out


def _preview_item_version_key(item: dict[str, Any]) -> str:
    return str(
        item.get("targetVersion") or item.get("registrationVersion") or ""
    ).strip() or "未指定版本"


def _preview_item_sort_tuple(item: dict[str, Any]) -> tuple:
    ver = _preview_item_version_key(item)
    try:
        parsed = parse_version(ver)
        ver_key = (0, parsed.x, parsed.y, parsed.z, parsed.b)
    except ValueError:
        ver_key = (1, 0, 0, 0, 0) if ver == "未指定版本" else (2, 0, 0, 0, 0)
    try:
        order = int(item.get("sortOrder"))
    except (TypeError, ValueError):
        order = 0
    return (*ver_key, ver, order)


def merge_preview_item_patches(
    preview: Optional[dict[str, Any]],
    patches: list[dict[str, Any]],
    removed_origin_keys: Optional[list[Any]] = None,
) -> tuple[dict[str, Any], set[str]]:
    """把增删改补丁合并进已有快照，未出现在补丁里的行保持原样。"""
    existing_preview = dict(preview) if isinstance(preview, dict) else {}
    existing = [
        x
        for x in list(existing_preview.get("items") or [])
        + list(existing_preview.get("deletedItems") or [])
        if isinstance(x, dict)
    ]
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for rec in existing:
        key = _origin_key_of(rec)
        if not key:
            rec = annotate_preview_item(rec, fresh=False)
            key = _origin_key_of(rec)
        if key in by_key:
            continue
        by_key[key] = rec
        order.append(key)
    removed = {str(x or "").strip() for x in (removed_origin_keys or []) if str(x or "").strip()}
    for key in removed:
        by_key.pop(key, None)
    patched_keys: set[str] = set(removed)
    for raw in patches:
        if not isinstance(raw, dict):
            continue
        rec = annotate_preview_item(raw, fresh=False)
        key = _origin_key_of(rec)
        patched_keys.add(key)
        if key not in by_key:
            order.append(key)
        by_key[key] = rec
    merged = [by_key[key] for key in order if key in by_key]
    merged.sort(key=_preview_item_sort_tuple)
    stamped = stamp_manual_preview_items(
        existing_preview, merged, recompute_keys=patched_keys
    )
    return stamped, patched_keys


def save_version_task_preview_edits(
    *,
    org_id: str,
    job_id: str,
    items: Optional[list[dict[str, Any]]] = None,
    changed_items: Optional[list[dict[str, Any]]] = None,
    removed_origin_keys: Optional[list[Any]] = None,
    adjustments: Optional[list[dict[str, Any]]] = None,
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    """保存人工编辑后的预览清单，并可选写入反馈供下次生成生效。

    优先增量：只合并 changed_items / removed_origin_keys，未改动的行不重写。
    未传 changed_items 时仍接受全量 items（兼容旧客户端）。
    """
    jid = (job_id or "").strip()
    if not jid:
        raise ValueError("jobId 不能为空")
    incremental = changed_items is not None
    if incremental:
        if not isinstance(changed_items, list):
            raise ValueError("changedItems 必须为数组")
        if removed_origin_keys is not None and not isinstance(removed_origin_keys, list):
            raise ValueError("removedOriginKeys 必须为数组")
    elif not isinstance(items, list):
        raise ValueError("items 必须为数组")
    job = VersionTaskGenerationJob.query.filter_by(
        id=jid, organization_id=org_id
    ).first()
    if not job:
        raise ValueError("未找到预览批次")
    from sqlalchemy.orm.attributes import flag_modified

    existing_preview = job.preview_json if isinstance(job.preview_json, dict) else {}
    patched_count = 0
    if incremental:
        removed = [x for x in (removed_origin_keys or []) if str(x or "").strip()]
        if not changed_items and not removed:
            existing_items = [x for x in (existing_preview.get("items") or []) if isinstance(x, dict)]
            return {
                "jobId": job.id,
                "projectId": job.project_id or "",
                "itemCount": len(existing_items),
                "patchedCount": 0,
                "unchanged": True,
                "feedbackSaved": 0,
                "updatedAt": job.updated_at.isoformat() if job.updated_at else now_local().isoformat(),
                "items": existing_items,
                "ruleItems": existing_preview.get("ruleItems") or [],
                "changeLog": existing_preview.get("changeLog") or [],
                "feedbacks": [],
            }
        preview, patched_keys = merge_preview_item_patches(
            existing_preview,
            changed_items,
            removed,
        )
        merged_items = [x for x in (preview.get("items") or []) if isinstance(x, dict)]
        conflicts = find_preview_filename_conflicts(merged_items)
        if conflicts:
            raise ValueError(format_preview_filename_conflicts(conflicts))
        patched_count = len(patched_keys)
    else:
        conflicts = find_preview_filename_conflicts(items)
        if conflicts:
            raise ValueError(format_preview_filename_conflicts(conflicts))
        preview = stamp_manual_preview_items(existing_preview, items)
        patched_count = len([x for x in items if isinstance(x, dict)])

    payload = json.loads(json.dumps(preview, ensure_ascii=False, default=str))
    payload["savedAt"] = now_local().isoformat()
    payload["itemCount"] = len(payload.get("items") or [])
    saved_at = now_local()
    job.preview_json = payload
    flag_modified(job, "preview_json")
    job.updated_at = saved_at
    db.session.add(job)
    db.session.execute(
        sa_update(VersionTaskGenerationJob)
        .where(VersionTaskGenerationJob.id == job.id)
        .values(preview_json=payload, updated_at=saved_at)
    )
    if (job.status or "") != "applied":
        job.status = "previewed"
    if project_id and not job.project_id:
        job.project_id = str(project_id).strip() or None

    cleaned_items = list(payload.get("items") or [])
    feedback_saved = 0
    rows: list[VersionTaskGenerationFeedback] = []
    if adjustments:
        rows = build_adjustment_rows(
            org_id=org_id,
            source_job_id=job.id,
            project_id=(project_id or job.project_id or None),
            adjustments=adjustments,
        )
        for row in rows:
            db.session.add(row)
        feedback_saved = len(rows)
        db.session.flush()
    return {
        "jobId": job.id,
        "projectId": job.project_id or "",
        "itemCount": len(cleaned_items),
        "patchedCount": patched_count,
        "unchanged": False,
        "feedbackSaved": feedback_saved,
        "updatedAt": now_local().isoformat(),
        "items": cleaned_items,
        "ruleItems": payload.get("ruleItems") or [],
        "changeLog": payload.get("changeLog") or [],
        "manualDeletedKeys": payload.get("manualDeletedKeys") or [],
        "feedbacks": [serialize_version_task_feedback(row) for row in rows],
    }


def find_version_task_preview_job(
    *,
    org_id: str,
    project_id: str,
    from_version: str,
    to_version: str,
) -> Optional[VersionTaskGenerationJob]:
    """按公司 + 项目 + 起止版本查找已入库的预览快照（取最近一条）。"""
    pid = str(project_id or "").strip()
    if not pid:
        return None
    try:
        from_n = parse_version(from_version).normalized
        to_n = parse_version(to_version).normalized
    except ValueError:
        from_n, to_n = str(from_version or "").strip(), str(to_version or "").strip()
    return (
        VersionTaskGenerationJob.query.filter_by(
            organization_id=org_id,
            project_id=pid,
            from_version=from_n,
            to_version=to_n,
        )
        .filter(VersionTaskGenerationJob.preview_json.isnot(None))
        .order_by(VersionTaskGenerationJob.updated_at.desc())
        .first()
    )


def split_preview_live_and_deleted(preview: Optional[dict[str, Any]]) -> dict[str, Any]:
    """快照里 items 只保留可见行；删除行放到 deletedItems。刷新只读这个结构。"""
    out = dict(preview) if isinstance(preview, dict) else {}
    raw_items = [dict(x) for x in (out.get("items") or []) if isinstance(x, dict)]
    sidecar = [dict(x) for x in (out.get("deletedItems") or []) if isinstance(x, dict)]
    deleted_keys = collect_deleted_dedupe_keys(raw_items + sidecar, out.get("manualDeletedKeys"))
    live: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    seen_del: set[tuple[str, str, str]] = set()
    live_keys: set[tuple[str, str, str]] = set()

    def take_deleted(rec: dict[str, Any]) -> None:
        key = _task_dedupe_key(rec)
        if key in seen_del or key in live_keys:
            return
        seen_del.add(key)
        deleted.append(_mark_preview_row_deleted(rec))

    for rec in raw_items:
        key = _task_dedupe_key(rec)
        if _preview_row_is_deleted(rec, deleted_keys):
            take_deleted(rec)
            continue
        live.append(rec)
        live_keys.add(key)
    for rec in sidecar:
        take_deleted(rec)
    out["items"] = live
    out["deletedItems"] = deleted
    out["manualDeletedKeys"] = [
        _serialize_dedupe_key(k) for k in sorted((deleted_keys | seen_del) - live_keys)
    ]
    return out


def _normalize_preview_payload_items(preview: dict[str, Any]) -> dict[str, Any]:
    for key in ("items", "deletedItems", "ruleItems"):
        rows = preview.get(key)
        if not isinstance(rows, list):
            continue
        cleaned: list[Any] = []
        for x in rows:
            if isinstance(x, dict):
                normalize_preview_item_fields(x)
                cleaned.append(x)
            else:
                cleaned.append(x)
        preview[key] = cleaned
    return preview


def hydrate_preview_deleted_markers(preview: Optional[dict[str, Any]]) -> dict[str, Any]:
    """读取已保存快照：可见行在 items，删除行只在 deletedItems。不用于再次生成。"""
    out = split_preview_live_and_deleted(preview)
    return _normalize_preview_payload_items(out)


def get_latest_version_task_preview(
    *,
    org_id: str,
    project_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """返回组织内最近一次带 preview_json 的生成批次（可按项目过滤）。"""
    query = VersionTaskGenerationJob.query.filter_by(organization_id=org_id).filter(
        VersionTaskGenerationJob.preview_json.isnot(None)
    )
    if (project_id or "").strip():
        query = query.filter_by(project_id=str(project_id).strip())
    job = query.order_by(VersionTaskGenerationJob.updated_at.desc()).first()
    if not job or not isinstance(job.preview_json, dict):
        return None
    persist_normalized_preview_job(job)
    payload = hydrate_preview_deleted_markers(job.preview_json)
    product_name = str(payload.get("productName") or "").strip()
    if not product_name and job.project_id:
        product_name = resolve_project_product_name(
            org_id=org_id, project_id=str(job.project_id)
        )
    payload.update(
        {
            "jobId": job.id,
            "projectId": job.project_id or "",
            "status": job.status or "",
            "updatedAt": job.updated_at.isoformat() if job.updated_at else "",
            "productName": product_name,
        }
    )
    return payload


def persist_normalized_preview_job(job: VersionTaskGenerationJob) -> bool:
    """把历史快照的任务类型/说明/备注迁到新字段并写回，避免只在内存里改。"""
    from sqlalchemy.orm.attributes import flag_modified

    payload = job.preview_json if job is not None else None
    if not isinstance(payload, dict):
        return False
    dirty = False
    for key in ("items", "deletedItems", "ruleItems"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for rec in rows:
            if isinstance(rec, dict) and normalize_preview_item_fields(rec):
                dirty = True
    if not dirty:
        return False
    try:
        flag_modified(job, "preview_json")
        db.session.commit()
    except Exception:
        db.session.rollback()
        return False
    return True


