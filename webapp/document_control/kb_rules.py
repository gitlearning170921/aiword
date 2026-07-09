"""知识库编号规则同步：写入 numbering_schemes。"""

from __future__ import annotations

from typing import Any, Optional

from webapp import db
from webapp.models import NumberingScheme


def _rule_pattern_regex(rule: dict[str, Any]) -> Optional[str]:
    code = (rule.get("docTypeCode") or "").strip().upper()
    template = (rule.get("renderTemplate") or "").strip()
    if not template or not rule.get("autoAllocatable"):
        return None
    if template == "{type}{seq:03d}" and code:
        return rf"^{code}(\d{{{int(rule.get('seqPad') or 3)},}})$"
    if template == "{prefix}-{type}{seq:03d}" and code:
        pad = int(rule.get("seqPad") or 3)
        return rf"^([A-Z0-9]{{2,24}})-{code}(\d{{{pad},}})$"
    if template == "{prefix}-{subtype}-{seq:03d}":
        pad = int(rule.get("seqPad") or 3)
        return rf"^([A-Z0-9]{{2,24}})-([A-Z]{{2,12}})-(\d{{{pad},}})$"
    return None


def upsert_schemes_from_kb_rules(org_id: str, rules: list[dict[str, Any]]) -> tuple[int, int, int]:
    """按 docTypeCode 幂等写入规则。返回 (created, updated, skipped)。"""
    created = updated = skipped = 0
    for rule in rules or []:
        code = (rule.get("docTypeCode") or "").strip().upper()
        name = (rule.get("name") or "").strip()
        if not code or not name:
            skipped += 1
            continue
        row = NumberingScheme.query.filter_by(organization_id=org_id, doc_type_code=code).first()
        render_template = (rule.get("renderTemplate") or "").strip() or "{prefix}-{type}-{seq:03d}"
        prefix_source = (rule.get("prefixSource") or "fixed").strip() or "fixed"
        if not rule.get("autoAllocatable"):
            prefix_source = (rule.get("prefixSource") or "fixed").strip() or "fixed"
        excerpt = (rule.get("kbRuleExcerpt") or rule.get("manualHint") or "").strip()
        example = (rule.get("example") or "").strip()
        if example and example not in excerpt:
            excerpt = f"{excerpt} 例如：{example}".strip() if excerpt else f"例如：{example}"
        payload = {
            "name": name,
            "pattern_regex": _rule_pattern_regex(rule),
            "render_template": render_template if rule.get("autoAllocatable") else (render_template or "{prefix}-{type}-{seq:03d}"),
            "prefix_source": prefix_source,
            "fixed_prefix": (rule.get("fixedPrefix") or "").strip() or None,
            "seq_start": max(1, int(rule.get("seqStart") or 1)),
            "seq_pad": max(1, int(rule.get("seqPad") or 3)),
            "is_active": bool(rule.get("autoAllocatable", True)),
            "kb_rule_excerpt": excerpt or None,
        }
        if row is None:
            row = NumberingScheme(
                organization_id=org_id,
                doc_type_code=code,
                **payload,
            )
            db.session.add(row)
            created += 1
        else:
            for k, v in payload.items():
                setattr(row, k, v)
            db.session.add(row)
            updated += 1
    if created or updated:
        db.session.commit()
    return created, updated, skipped
