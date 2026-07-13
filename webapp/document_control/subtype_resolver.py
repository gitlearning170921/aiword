"""DHF/注册文件：由文件名称英文单词首字母生成子类编号。"""

from __future__ import annotations

import re
from typing import Any, Iterator, Optional

from webapp.models import ControlledDocument, NumberAllocation, NumberingScheme

from .numbering_engine import (
    _prefix_from_project_code,
    _scheme_uses_subtype_template,
    _template_seq_regex,
    normalize_document_number,
)

_WORD_RE = re.compile(r"[A-Za-z]+")
_TITLE_WS_RE = re.compile(r"\s+")


class SubtypeChoiceRequired(ValueError):
    """台账中存在多个同名受控文件的子类编号，需用户选择。"""

    def __init__(self, choices: list[dict[str, Any]]):
        self.choices = choices
        super().__init__("台账中有多个同名文件的子类编号，请选择")


def normalize_title_key(title: str) -> str:
    return _TITLE_WS_RE.sub(" ", (title or "").strip()).casefold()


def english_words(title: str) -> list[str]:
    return [w for w in _WORD_RE.findall(title or "") if w]


def _letter_pool(words: list[str]) -> list[str]:
    if not words:
        return []
    max_len = max(len(w) for w in words)
    pool: list[str] = []
    for pos in range(max_len):
        for w in words:
            if len(w) > pos:
                pool.append(w[pos].upper())
    return pool


def iter_subtype_candidates(title: str) -> Iterator[str]:
    """子类候选：先取前 3～N 个英文单词首字母，用尽后按各单词第 2、3… 位字母递补。"""
    words = english_words(title)
    if not words:
        return
    first_letters = [w[0].upper() for w in words if w]
    n = len(first_letters)
    pool = _letter_pool(words)
    seen: set[str] = set()

    start_k = min(3, n)
    for k in range(start_k, n + 1):
        cand = "".join(first_letters[:k])
        if cand and cand not in seen:
            seen.add(cand)
            yield cand

    base_len = n
    for length in range(max(base_len + 1, start_k + 1), len(pool) + 1):
        cand = "".join(pool[:length])
        if cand and cand not in seen:
            seen.add(cand)
            yield cand


def extract_subtype_from_number(
    number: str,
    *,
    scheme: NumberingScheme,
    prefix: str,
) -> Optional[str]:
    norm = normalize_document_number(number or "")
    if not norm:
        return None
    prefix_norm = normalize_document_number(prefix or "")
    template = (scheme.render_template or "").strip()
    if "{subtype}" not in template:
        return None
    if prefix_norm:
        pat = re.compile(
            rf"^{re.escape(prefix_norm)}-([A-Z0-9]{{2,24}})-(\d+)$",
            re.I,
        )
        m = pat.match(norm)
        if m:
            return normalize_document_number(m.group(1))
    pattern = _template_seq_regex(scheme, prefix=prefix_norm or "", subtype="")
    m = pattern.match(norm)
    if not m:
        return None
    groups = m.groups()
    if len(groups) >= 2:
        return normalize_document_number(groups[-2])
    return None


def _controlled_docs_for_prefix(org_id: str, prefix: str) -> list[ControlledDocument]:
    from .numbering_engine import DOC_STATUS_CONTROLLED

    prefix_norm = normalize_document_number(prefix or "")
    if not prefix_norm:
        return []
    out: list[ControlledDocument] = []
    for row in ControlledDocument.query.filter_by(
        organization_id=org_id,
        status=DOC_STATUS_CONTROLLED,
    ).all():
        num = normalize_document_number(row.document_number or "")
        if num.startswith(prefix_norm + "-"):
            out.append(row)
    return out


def _active_allocations_for_prefix(org_id: str, prefix: str) -> list[NumberAllocation]:
    from .numbering_engine import allocation_counts_for_subtype_reuse

    prefix_norm = normalize_document_number(prefix or "")
    if not prefix_norm:
        return []
    out: list[NumberAllocation] = []
    for row in NumberAllocation.query.filter(
        NumberAllocation.organization_id == org_id,
        NumberAllocation.status == "issued",
    ).all():
        if not allocation_counts_for_subtype_reuse(row):
            continue
        num = normalize_document_number(row.allocated_number or "")
        if num.startswith(prefix_norm + "-"):
            out.append(row)
    return out


def _subtype_title_map(
    org_id: str,
    scheme: NumberingScheme,
    prefix: str,
) -> dict[str, set[str]]:
    """子类 → 已占用该子类的文件名称（规范化）。"""
    mapping: dict[str, set[str]] = {}
    for doc in _controlled_docs_for_prefix(org_id, prefix):
        sub = extract_subtype_from_number(doc.document_number or "", scheme=scheme, prefix=prefix)
        if not sub:
            continue
        title_key = normalize_title_key(doc.title or "")
        if not title_key:
            continue
        mapping.setdefault(sub, set()).add(title_key)
    for alloc in _active_allocations_for_prefix(org_id, prefix):
        sub = extract_subtype_from_number(alloc.allocated_number or "", scheme=scheme, prefix=prefix)
        if not sub:
            continue
        title_key = normalize_title_key(alloc.requested_title or "")
        if not title_key:
            continue
        mapping.setdefault(sub, set()).add(title_key)
    return mapping


def _subtype_conflicts_other_title(
    subtype: str,
    title_key: str,
    mapping: dict[str, set[str]],
) -> bool:
    titles = mapping.get(subtype) or set()
    if not titles:
        return False
    outsiders = {
        t for t in titles if t != title_key and not _title_keys_same_issue_line(t, title_key)
    }
    return bool(outsiders)


def _title_matches_for_duplicate(existing_title: str, input_title: str) -> bool:
    """精确同名，或已有记录的文件名称包含填写名称。"""
    existing_key = normalize_title_key(existing_title)
    input_key = normalize_title_key(input_title)
    if not input_key or not existing_key:
        return False
    if existing_key == input_key:
        return True
    return input_key in existing_key


def _title_same_issue_line(existing_title: str, input_title: str) -> bool:
    """判重/流水号/子类复用：精确同名或双向包含。"""
    if _title_matches_for_duplicate(existing_title, input_title):
        return True
    return _title_matches_for_duplicate(input_title, existing_title)


def _title_keys_same_issue_line(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    return a in b or b in a


def find_controlled_docs_for_exact_title(
    *,
    organization_id: str,
    prefix: str,
    title: str,
    project_id: Optional[str] = None,
) -> list[ControlledDocument]:
    """受控台账中与填写名称完全相同的文件（不含包含关系）。"""
    from .numbering_engine import DOC_STATUS_CONTROLLED

    title_key = normalize_title_key(title)
    if not title_key:
        return []
    prefix_norm = normalize_document_number(prefix or "")
    pid = (project_id or "").strip() or None

    matches: list[ControlledDocument] = []
    rows = (
        ControlledDocument.query.filter_by(
            organization_id=organization_id,
            status=DOC_STATUS_CONTROLLED,
        )
        .order_by(ControlledDocument.created_at.desc(), ControlledDocument.id.desc())
        .all()
    )
    for doc in rows:
        if normalize_title_key(doc.title or "") != title_key:
            continue
        doc_pid = (doc.project_id or "").strip()
        if pid and doc_pid and doc_pid != pid:
            continue
        if prefix_norm:
            doc_prefix = normalize_document_number(doc.project_code or "")
            if doc_prefix and doc_prefix != prefix_norm:
                continue
        matches.append(doc)
    return matches


def find_subtype_choices_for_exact_title(
    *,
    organization_id: str,
    scheme: NumberingScheme,
    prefix: str,
    title: str,
    project_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """同名受控文件已使用的子类编号（去重，按台账时间新→旧）。"""
    choices: list[dict[str, Any]] = []
    seen_sub: set[str] = set()
    for doc in find_controlled_docs_for_exact_title(
        organization_id=organization_id,
        prefix=prefix,
        title=title,
        project_id=project_id,
    ):
        sub = extract_subtype_from_number(doc.document_number or "", scheme=scheme, prefix=prefix)
        if not sub or sub in seen_sub:
            continue
        seen_sub.add(sub)
        choices.append(
            {
                "subtype": sub,
                "documentNumber": doc.document_number,
                "sheetCategory": doc.sheet_category,
                "title": doc.title,
                "documentId": doc.id,
                "projectName": (doc.project_name or "").strip() or None,
                "projectCode": (doc.project_code or "").strip() or None,
            }
        )
    return choices


def find_controlled_docs_for_issue_title(
    *,
    organization_id: str,
    prefix: str,
    title: str,
    project_id: Optional[str] = None,
) -> list[ControlledDocument]:
    """与判重一致：受控台账中名称相关的文件（精确或包含）。"""
    from .numbering_engine import DOC_STATUS_CONTROLLED

    if not normalize_title_key(title):
        return []
    prefix_norm = normalize_document_number(prefix or "")
    pid = (project_id or "").strip() or None

    matches: list[ControlledDocument] = []
    rows = (
        ControlledDocument.query.filter_by(
            organization_id=organization_id,
            status=DOC_STATUS_CONTROLLED,
        )
        .order_by(ControlledDocument.created_at.desc(), ControlledDocument.id.desc())
        .all()
    )
    for doc in rows:
        if not _title_same_issue_line(doc.title or "", title):
            continue
        doc_pid = (doc.project_id or "").strip()
        if pid and doc_pid and doc_pid != pid:
            continue
        if prefix_norm:
            doc_prefix = normalize_document_number(doc.project_code or "")
            if doc_prefix and doc_prefix != prefix_norm:
                continue
        matches.append(doc)
    return matches


def find_existing_controlled_doc_by_title(
    *,
    organization_id: str,
    prefix: str,
    title: str,
    project_id: Optional[str] = None,
) -> Optional[ControlledDocument]:
    """同组织内同名或名称包含关系的受控文件（用于申请前确认）。"""
    matches = find_controlled_docs_for_issue_title(
        organization_id=organization_id,
        prefix=prefix,
        title=title,
        project_id=project_id,
    )
    return matches[0] if matches else None


def find_existing_subtype_for_title(
    *,
    organization_id: str,
    scheme: NumberingScheme,
    prefix: str,
    title: str,
) -> Optional[str]:
    """名称相关文件复用已有子类，流水号由取号引擎递增。"""
    for doc in find_controlled_docs_for_issue_title(
        organization_id=organization_id,
        prefix=prefix,
        title=title,
    ):
        sub = extract_subtype_from_number(doc.document_number or "", scheme=scheme, prefix=prefix)
        if sub:
            return sub
    title_key = normalize_title_key(title)
    if not title_key:
        return None
    for alloc in _active_allocations_for_prefix(organization_id, prefix):
        if not _title_keys_same_issue_line(normalize_title_key(alloc.requested_title or ""), title_key):
            continue
        sub = extract_subtype_from_number(alloc.allocated_number or "", scheme=scheme, prefix=prefix)
        if sub:
            return sub
    return None


def resolve_subtype_from_title(
    *,
    organization_id: str,
    scheme: NumberingScheme,
    project_code: Optional[str],
    title: str,
    title_en: Optional[str] = None,
    project_id: Optional[str] = None,
) -> str:
    prefix = (
        _prefix_from_project_code(project_code, scheme.fixed_prefix)
        if (scheme.prefix_source or "fixed") == "from_project_code"
        else normalize_document_number(scheme.fixed_prefix or scheme.doc_type_code or "DOC")
    )
    title_key = normalize_title_key(title)
    if not title_key:
        raise ValueError("请填写文件名称")

    exact_choices = find_subtype_choices_for_exact_title(
        organization_id=organization_id,
        scheme=scheme,
        prefix=prefix,
        title=title,
        project_id=project_id,
    )
    if exact_choices:
        if len(exact_choices) == 1:
            return exact_choices[0]["subtype"]
        raise SubtypeChoiceRequired(exact_choices)

    existing_sub = find_existing_subtype_for_title(
        organization_id=organization_id,
        scheme=scheme,
        prefix=prefix,
        title=title,
    )
    if existing_sub:
        return existing_sub

    subtype_source = (title_en or title or "").strip()
    words = english_words(subtype_source)
    if not words:
        raise ValueError("无法从文件名称生成子类编号，请补充英文或稍后重试自动翻译")

    doc_type_code = normalize_document_number(scheme.doc_type_code or "")
    mapping = _subtype_title_map(organization_id, scheme, prefix)
    for cand in iter_subtype_candidates(subtype_source):
        if (
            doc_type_code
            and cand == doc_type_code
            and cand != "".join(w[0].upper() for w in words[: min(3, len(words))])
        ):
            continue
        if not _subtype_conflicts_other_title(cand, title_key, mapping):
            return cand

    raise ValueError("无法为当前文件名称生成唯一子类编号，请调整名称中的英文单词")


def resolve_allocation_subtype(
    *,
    organization_id: str,
    scheme: NumberingScheme,
    project_code: Optional[str],
    title: str,
    title_en: Optional[str] = None,
    manual_subtype: Optional[str] = None,
    subtype_from_title: bool = False,
    project_id: Optional[str] = None,
) -> str:
    prefix = (
        _prefix_from_project_code(project_code, scheme.fixed_prefix)
        if (scheme.prefix_source or "fixed") == "from_project_code"
        else normalize_document_number(scheme.fixed_prefix or scheme.doc_type_code or "DOC")
    )
    manual = (manual_subtype or "").strip()
    if manual:
        norm_manual = normalize_document_number(manual)
        exact_choices = find_subtype_choices_for_exact_title(
            organization_id=organization_id,
            scheme=scheme,
            prefix=prefix,
            title=title,
            project_id=project_id,
        )
        if len(exact_choices) > 1:
            allowed = {c["subtype"] for c in exact_choices}
            if norm_manual not in allowed:
                allowed_text = ", ".join(sorted(allowed))
                raise ValueError(f"请选择台账同名文件已有的子类编号：{allowed_text}")
        return norm_manual
    if subtype_from_title or _scheme_uses_subtype_template(scheme):
        return resolve_subtype_from_title(
            organization_id=organization_id,
            scheme=scheme,
            project_code=project_code,
            title=title,
            title_en=title_en,
            project_id=project_id,
        )
    return normalize_document_number(scheme.doc_type_code or "DOC")
