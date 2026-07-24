"""页面1 / 文控台账：项目编号唯一；跨项目不可重复；同项目可修改并同步相关记录。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from webapp import db
from webapp.document_control.numbering_engine import normalize_document_number
from webapp.document_control.project_link import (
    controlled_document_labels_for_project_id,
    count_controlled_documents_for_project_id,
)
from webapp.document_control.subtype_resolver import normalize_title_key
from webapp.models import ControlledDocument, NumberAllocation, Project, UploadRecord, now_local
from webapp.project_identity import (
    canonical_project_identity_key,
    find_page1_project,
    registered_country_identity_part,
    scope_field_tokens,
)

_PROJECT_CODE_SPLIT_RE = re.compile(r"[,，、]|\s*/\s*")


@dataclass
class ProjectCodeSaveCheck:
    hard_error: Optional[str] = None
    needs_confirmation: bool = False
    confirmation_message: Optional[str] = None
    old_codes: tuple[str, ...] = ()
    new_code: Optional[str] = None
    related_upload_count: int = 0
    related_document_count: int = 0
    related_allocation_count: int = 0
    controlled_document_count: int = 0
    controlled_document_samples: tuple[str, ...] = ()


def project_code_tokens(value: Optional[str]) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    parts = _PROJECT_CODE_SPLIT_RE.split(text)
    tokens = [normalize_document_number(p.strip()) for p in parts if p and p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


_NAME_PAREN_RE = re.compile(r"[\(（].*$")


def _project_name_keys(value: Optional[str]) -> set[str]:
    """项目名归一化键集合：支持多项目逗号串、括号后缀（如「软件（CE, NMPA）」）。"""
    keys: set[str] = set()
    text = (value or "").strip()
    if not text:
        return keys
    parts = scope_field_tokens(text)
    # 括号内常含逗号，纯 split 会拆坏；对未配对片段做一次粘合回退
    if not parts:
        parts = [text]
    for part in parts:
        raw = (part or "").strip()
        if not raw:
            continue
        k = normalize_title_key(raw)
        if k:
            keys.add(k)
        base = _NAME_PAREN_RE.sub("", raw).strip()
        if base and base != raw:
            bk = normalize_title_key(base)
            if bk:
                keys.add(bk)
    full = normalize_title_key(text)
    if full:
        keys.add(full)
    return keys


def _project_name_matches(target_name: Optional[str], stored_name: Optional[str]) -> bool:
    """双向匹配：单项目名 ↔ 多项目逗号串中任一段。"""
    left = _project_name_keys(target_name)
    right = _project_name_keys(stored_name)
    if not left or not right:
        return False
    return bool(left & right)


def _countries_compatible(
    left: Optional[str],
    right: Optional[str],
) -> bool:
    """注册国家兼容：任一侧为空、完全相等、或集合有交集（多国家串）均可。"""
    a = {
        x
        for x in registered_country_identity_part(left).split("|")
        if x
    }
    b = {
        x
        for x in registered_country_identity_part(right).split("|")
        if x
    }
    if not a or not b:
        return True
    return bool(a & b)


def record_belongs_to_project(
    *,
    record_project_id: Optional[str],
    record_project_name: Optional[str],
    record_registered_country: Optional[str],
    project_id: Optional[str],
    project_name: Optional[str],
    registered_country: Optional[str] = None,
) -> bool:
    target_key = canonical_project_identity_key(
        project_id, project_name, registered_country
    )
    row_key = canonical_project_identity_key(
        record_project_id,
        record_project_name,
        record_registered_country,
    )
    if target_key and row_key and target_key == row_key:
        return True
    if (
        (project_id or "").strip()
        and (record_project_id or "").strip() == (project_id or "").strip()
    ):
        return True
    # 多项目台账串 / 单项目名：名称命中且国家兼容即视为同项目作用域
    if _project_name_matches(project_name, record_project_name):
        return _countries_compatible(registered_country, record_registered_country)
    return False


def _registration_scope_entries(meta: Optional[dict]) -> list[dict[str, Any]]:
    if not isinstance(meta, dict):
        return []
    items = meta.get("registrationProjects")
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict)]


def document_belongs_to_project(
    doc: ControlledDocument,
    *,
    project_id: Optional[str],
    project_name: Optional[str],
    registered_country: Optional[str] = None,
) -> bool:
    pid = (project_id or "").strip()
    if pid and (doc.project_id or "").strip() == pid:
        return True
    if record_belongs_to_project(
        record_project_id=doc.project_id,
        record_project_name=doc.project_name,
        record_registered_country=doc.registered_country,
        project_id=project_id,
        project_name=project_name,
        registered_country=registered_country,
    ):
        return True
    target_key = normalize_title_key(project_name or "")
    if not target_key:
        return False
    rc_key = registered_country_identity_part(registered_country)
    for entry in _registration_scope_entries(doc.metadata_json):
        entry_name = normalize_title_key(entry.get("projectName") or "")
        if entry_name != target_key:
            continue
        if not rc_key:
            return True
        entry_rc = registered_country_identity_part(entry.get("registeredCountry"))
        if entry_rc == rc_key:
            return True
    return False


def _load_code_rows(
    organization_id: Optional[str],
) -> list[tuple[str, str, Optional[str], Optional[str], Optional[str], Optional[str]]]:
    org = (organization_id or "").strip() or None
    upload_q = UploadRecord.query.filter(
        UploadRecord.project_code.isnot(None),
        UploadRecord.project_code != "",
    )
    if org:
        upload_q = upload_q.filter(
            (UploadRecord.organization_id == org) | (UploadRecord.organization_id.is_(None))
        )
    upload_rows = [
        (row.id, "upload", row.project_id, row.project_name, row.country, row.project_code)
        for row in upload_q.all()
    ]

    proj_q = Project.query.filter(
        Project.project_code.isnot(None),
        Project.project_code != "",
    )
    if org:
        proj_q = proj_q.filter(
            (Project.organization_id == org) | (Project.organization_id.is_(None))
        )
    project_rows = [
        (row.id, "project", row.id, row.name, row.registered_country, row.project_code)
        for row in proj_q.all()
    ]

    doc_q = ControlledDocument.query.filter(
        ControlledDocument.project_code.isnot(None),
        ControlledDocument.project_code != "",
        ControlledDocument.status == "controlled",
    )
    if org:
        doc_q = doc_q.filter_by(organization_id=org)
    doc_rows: list[
        tuple[str, str, Optional[str], Optional[str], Optional[str], Optional[str]]
    ] = []
    for row in doc_q.all():
        # 台账常把多项目/多国家/多编号拼在同一字段；拆成作用域对再判重，
        # 避免整串被当成「另一个项目」误拦同编号新增。
        pairs = _expand_scope_code_pairs(
            row.project_name or "",
            row.registered_country or "",
            row.project_code or "",
        )
        if not pairs:
            doc_rows.append(
                (
                    row.id,
                    "doc",
                    row.project_id,
                    row.project_name,
                    row.registered_country,
                    row.project_code,
                )
            )
            continue
        for pn, rc, pc in pairs:
            if not (pc or "").strip():
                continue
            doc_rows.append(
                (
                    row.id,
                    "doc",
                    row.project_id,
                    pn or row.project_name,
                    rc or row.registered_country,
                    pc,
                )
            )
    return project_rows + upload_rows + doc_rows


def _expand_scope_code_pairs(
    project_name: str,
    registered_country: str,
    project_code: str,
) -> list[tuple[str, str, str]]:
    """将逗号分隔的项目名/国家/项目编号展开为对齐的三元组。"""
    pn_tokens = [p for p in scope_field_tokens(project_name) if p]
    rc_tokens = [p for p in scope_field_tokens(registered_country) if p]
    pc_tokens = project_code_tokens(project_code)
    # project_code_tokens 已规范化；展示仍用原始分段更利于名称匹配
    raw_pc = [p for p in scope_field_tokens(project_code) if p] or [
        (project_code or "").strip()
    ]
    raw_pc = [p for p in raw_pc if p]
    if not pn_tokens and not rc_tokens and not raw_pc:
        return []

    if len(pn_tokens) > 1 and len(rc_tokens) > 1:
        count = max(len(pn_tokens), len(rc_tokens), len(raw_pc) or 1)
    elif len(pn_tokens) > 1:
        count = max(len(pn_tokens), len(raw_pc) or 1)
    elif len(rc_tokens) > 1:
        count = max(len(rc_tokens), len(raw_pc) or 1)
    elif len(raw_pc) > 1:
        count = len(raw_pc)
    else:
        count = 1

    def _at(tokens: list[str], index: int) -> str:
        if not tokens:
            return ""
        if len(tokens) == 1:
            return tokens[0]
        return tokens[index] if index < len(tokens) else ""

    pairs: list[tuple[str, str, str]] = []
    for i in range(count):
        pn = _at(pn_tokens, i)
        rc = _at(rc_tokens, i)
        pc = _at(raw_pc, i)
        if not pc and pc_tokens:
            pc = _at(list(pc_tokens), i) or (pc_tokens[0] if len(pc_tokens) == 1 else "")
        if not pn and not rc and not pc:
            continue
        pairs.append((pn, rc, pc))
    return pairs


def _collect_existing_codes_for_project(
    rows: Iterable[tuple[str, str, Optional[str], Optional[str], Optional[str], Optional[str]]],
    *,
    current: str,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
    registered_country: Optional[str] = None,
    exclude_upload_id: Optional[str],
    exclude_document_id: Optional[str],
) -> set[str]:
    codes: set[str] = set()
    for record_id, record_kind, pid, pname, pcountry, pcode in rows:
        if record_kind == "upload" and exclude_upload_id and record_id == exclude_upload_id:
            continue
        if record_kind == "doc" and exclude_document_id and record_id == exclude_document_id:
            continue
        row_key = canonical_project_identity_key(pid, pname, pcountry)
        same = bool(current and row_key and row_key == current)
        if not same:
            same = record_belongs_to_project(
                record_project_id=pid,
                record_project_name=pname,
                record_registered_country=pcountry,
                project_id=project_id,
                project_name=project_name,
                registered_country=registered_country,
            )
        if not same:
            continue
        codes.update(project_code_tokens(pcode))
    return codes


def _count_related_records(
    organization_id: Optional[str],
    *,
    project_id: Optional[str],
    project_name: Optional[str],
    registered_country: Optional[str] = None,
    exclude_upload_id: Optional[str],
    exclude_document_id: Optional[str],
) -> tuple[int, int, int]:
    org = (organization_id or "").strip() or None
    upload_count = 0
    upload_q = UploadRecord.query.filter(
        UploadRecord.project_code.isnot(None),
        UploadRecord.project_code != "",
    )
    if org:
        upload_q = upload_q.filter(
            (UploadRecord.organization_id == org) | (UploadRecord.organization_id.is_(None))
        )
    for row in upload_q.all():
        if exclude_upload_id and row.id == exclude_upload_id:
            continue
        if record_belongs_to_project(
            record_project_id=row.project_id,
            record_project_name=row.project_name,
            record_registered_country=row.country,
            project_id=project_id,
            project_name=project_name,
            registered_country=registered_country,
        ):
            upload_count += 1

    doc_count = 0
    doc_q = ControlledDocument.query.filter_by(status="controlled")
    if org:
        doc_q = doc_q.filter_by(organization_id=org)
    for row in doc_q.all():
        if exclude_document_id and row.id == exclude_document_id:
            continue
        if not (row.project_code or "").strip():
            continue
        if document_belongs_to_project(
            row,
            project_id=project_id,
            project_name=project_name,
            registered_country=registered_country,
        ):
            doc_count += 1

    alloc_count = 0
    alloc_q = NumberAllocation.query.filter(
        NumberAllocation.project_code.isnot(None),
        NumberAllocation.project_code != "",
    )
    if org:
        alloc_q = alloc_q.filter_by(organization_id=org)
    pid = (project_id or "").strip()
    for row in alloc_q.all():
        if pid and (row.project_id or "").strip() == pid:
            alloc_count += 1

    return upload_count, doc_count, alloc_count


def _build_change_confirmation_message(
    *,
    old_show: str,
    new_code: str,
    uploads_n: int,
    docs_n: int,
    allocs_n: int,
    controlled_n: int,
    controlled_samples: list[str],
) -> str:
    lines = [
        f"该项目当前项目编号为「{old_show}」，将修改为「{new_code}」。",
        "",
    ]
    if controlled_n > 0:
        sample = "、".join(controlled_samples[:3])
        if controlled_n > 3:
            sample += f" 等 {controlled_n} 条"
        lines.append(
            f"文控中心关联本项目已有 {controlled_n} 条受控文件"
            + (f"（如：{sample}）" if sample else "")
            + "。"
        )
        lines.append("")
    parts = []
    if uploads_n:
        parts.append(f"{uploads_n} 条任务记录")
    if docs_n:
        parts.append(f"{docs_n} 条文控台账项目编号")
    if allocs_n:
        parts.append(f"{allocs_n} 条编号预留")
    if parts:
        lines.append(f"确认后将同步更新：{'、'.join(parts)}。")
    else:
        lines.append("确认后将同步更新相关记录中的项目编号字段。")
    lines.extend(
        [
            "受控文件编号（纸质记录前缀）不会自动修改，请在文控中心手动核对并修改，以保持与纸质记录一致。",
            "",
            "是否仍要修改项目编号？",
        ]
    )
    return "\n".join(lines)


def check_project_code_save(
    organization_id: Optional[str],
    project_code: str,
    *,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
    registered_country: Optional[str] = None,
    exclude_upload_id: Optional[str] = None,
    exclude_document_id: Optional[str] = None,
) -> ProjectCodeSaveCheck:
    tokens = project_code_tokens(project_code)
    if not tokens:
        return ProjectCodeSaveCheck()

    resolved_country = registered_country
    resolved_project = find_page1_project(
        project_id=project_id,
        project_name=project_name,
        registered_country=registered_country,
    )
    if not (resolved_country or "").strip() and resolved_project:
        resolved_country = getattr(resolved_project, "registered_country", None)
    resolved_project_id = (project_id or "").strip() or (
        str(getattr(resolved_project, "id", "") or "").strip() or None
    )

    current = canonical_project_identity_key(
        resolved_project_id, project_name, resolved_country
    )
    if not current:
        return ProjectCodeSaveCheck()

    if len(tokens) > 1:
        show = ", ".join(tokens)
        return ProjectCodeSaveCheck(
            hard_error=f"同一项目只能有一个项目编号，不能填写多个（{show}）"
        )

    new_code = tokens[0]
    eff_name = project_name or (
        getattr(resolved_project, "name", None) if resolved_project else None
    )

    # 本项目在 Project 表已登记该编号：新增任务/台账记录一律放行（最常见业务路径）
    if resolved_project and new_code in project_code_tokens(
        getattr(resolved_project, "project_code", None)
    ):
        return ProjectCodeSaveCheck(new_code=new_code)

    # 其他页面1项目已占用该编号 → 硬拦截（以 Project 表为准）
    for other_proj in Project.query.filter(
        Project.project_code.isnot(None),
        Project.project_code != "",
    ).all():
        if organization_id:
            other_org = str(getattr(other_proj, "organization_id", "") or "").strip()
            if other_org and other_org != str(organization_id).strip():
                continue
        if new_code not in project_code_tokens(getattr(other_proj, "project_code", None)):
            continue
        if resolved_project_id and other_proj.id == resolved_project_id:
            continue
        if record_belongs_to_project(
            record_project_id=other_proj.id,
            record_project_name=other_proj.name,
            record_registered_country=getattr(other_proj, "registered_country", None),
            project_id=resolved_project_id,
            project_name=eff_name,
            registered_country=resolved_country,
        ):
            continue
        other_label = (other_proj.name or "").strip() or other_proj.id
        other_rc = (getattr(other_proj, "registered_country", None) or "").strip()
        if other_rc:
            other_label = f"{other_label}（{other_rc}）"
        return ProjectCodeSaveCheck(
            hard_error=(
                f"项目编号「{new_code}」已被项目「{other_label}」使用，"
                f"不同项目的项目编号不能重复"
            )
        )

    all_rows = _load_code_rows(organization_id)

    same_project_codes = _collect_existing_codes_for_project(
        all_rows,
        current=current,
        project_id=resolved_project_id,
        project_name=eff_name,
        registered_country=resolved_country,
        exclude_upload_id=exclude_upload_id,
        exclude_document_id=exclude_document_id,
    )
    if resolved_project:
        same_project_codes.update(
            project_code_tokens(getattr(resolved_project, "project_code", None))
        )

    # 同项目已有相同编号（任务/台账）：允许继续新增
    if new_code in same_project_codes:
        return ProjectCodeSaveCheck(new_code=new_code)

    for record_id, record_kind, pid, pname, pcountry, pcode in all_rows:
        if record_kind == "project":
            # 已在上方按 Project 表处理
            continue
        if record_kind == "upload" and exclude_upload_id and record_id == exclude_upload_id:
            continue
        if record_kind == "doc" and exclude_document_id and record_id == exclude_document_id:
            continue
        row_tokens = project_code_tokens(pcode)
        if not row_tokens or new_code not in row_tokens:
            continue
        if record_belongs_to_project(
            record_project_id=pid,
            record_project_name=pname,
            record_registered_country=pcountry,
            project_id=resolved_project_id,
            project_name=eff_name,
            registered_country=resolved_country,
        ):
            continue
        other = canonical_project_identity_key(pid, pname, pcountry)
        if other and other == current:
            continue
        # 台账多项目串：名称有任一命中即视为同作用域，不拦截新增
        if _project_name_matches(eff_name, pname):
            continue
        other_label = (pname or "").strip() or pid or "其他项目"
        if (pcountry or "").strip():
            other_label = f"{other_label}（{pcountry}）"
        return ProjectCodeSaveCheck(
            hard_error=(
                f"项目编号「{new_code}」已被项目「{other_label}」使用，"
                f"不同项目的项目编号不能重复"
            )
        )

    if same_project_codes and new_code not in same_project_codes:
        uploads_n, docs_n, allocs_n = _count_related_records(
            organization_id,
            project_id=resolved_project_id,
            project_name=project_name,
            registered_country=resolved_country,
            exclude_upload_id=exclude_upload_id,
            exclude_document_id=exclude_document_id,
        )
        controlled_n = count_controlled_documents_for_project_id(resolved_project_id)
        controlled_samples = controlled_document_labels_for_project_id(resolved_project_id)
        old_show = ", ".join(sorted(same_project_codes))
        return ProjectCodeSaveCheck(
            needs_confirmation=True,
            confirmation_message=_build_change_confirmation_message(
                old_show=old_show,
                new_code=new_code,
                uploads_n=uploads_n,
                docs_n=docs_n,
                allocs_n=allocs_n,
                controlled_n=controlled_n,
                controlled_samples=controlled_samples,
            ),
            old_codes=tuple(sorted(same_project_codes)),
            new_code=new_code,
            related_upload_count=uploads_n,
            related_document_count=docs_n,
            related_allocation_count=allocs_n,
            controlled_document_count=controlled_n,
            controlled_document_samples=tuple(controlled_samples),
        )

    return ProjectCodeSaveCheck(new_code=new_code)


def confirmation_response_payload(check: ProjectCodeSaveCheck) -> dict[str, Any]:
    return {
        "message": check.confirmation_message or "项目编号变更需确认",
        "needsConfirmation": True,
        "confirmationKind": "projectCodeSync",
        "syncPreview": {
            "uploads": check.related_upload_count,
            "documents": check.related_document_count,
            "allocations": check.related_allocation_count,
            "controlledDocuments": check.controlled_document_count,
            "controlledSamples": list(check.controlled_document_samples),
            "oldCodes": list(check.old_codes),
            "newCode": check.new_code,
            "manualDocumentNumberNote": (
                "受控文件编号（纸质记录前缀）不会自动修改，请在文控中心手动核对并修改。"
            ),
        },
    }


def gate_project_code_save(
    organization_id: Optional[str],
    project_code: str,
    *,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
    registered_country: Optional[str] = None,
    exclude_upload_id: Optional[str] = None,
    exclude_document_id: Optional[str] = None,
    confirm_sync: bool = False,
) -> Optional[tuple[str, Any]]:
    """返回 None 表示可继续；('error', msg) 硬拦截；('confirm', payload) 需用户确认。"""
    resolved = find_page1_project(
        project_id=project_id,
        project_name=project_name,
        registered_country=registered_country,
    )
    eff_pid = (project_id or "").strip() or (
        str(getattr(resolved, "id", "") or "").strip() or None
    )
    eff_country = (registered_country or "").strip() or (
        str(getattr(resolved, "registered_country", "") or "").strip() or None
    )
    check = check_project_code_save(
        organization_id,
        project_code,
        project_id=eff_pid,
        project_name=project_name
        or (getattr(resolved, "name", None) if resolved else None),
        registered_country=eff_country,
        exclude_upload_id=exclude_upload_id,
        exclude_document_id=exclude_document_id,
    )
    if check.hard_error:
        return ("error", check.hard_error)
    if check.needs_confirmation and not confirm_sync:
        return ("confirm", confirmation_response_payload(check))
    if check.needs_confirmation and confirm_sync and check.new_code:
        sync_project_code_for_project(
            organization_id,
            check.new_code,
            project_id=eff_pid,
            project_name=project_name
            or (getattr(resolved, "name", None) if resolved else None),
            registered_country=eff_country,
            old_codes=check.old_codes,
        )
    return None


def _rebuild_doc_project_code_from_meta(doc: ControlledDocument, meta: dict[str, Any]) -> None:
    entries = _registration_scope_entries(meta)
    if not entries:
        return
    codes: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        pc = (entry.get("projectCode") or "").strip()
        if not pc:
            continue
        key = normalize_document_number(pc)
        if key in seen:
            continue
        seen.add(key)
        codes.append(pc)
    if codes:
        doc.project_code = ", ".join(codes)


def _sync_controlled_document_code(
    doc: ControlledDocument,
    *,
    project_id: Optional[str],
    project_name: Optional[str],
    registered_country: Optional[str],
    new_code: str,
    old_codes: set[str],
) -> bool:
    if not document_belongs_to_project(
        doc,
        project_id=project_id,
        project_name=project_name,
        registered_country=registered_country,
    ):
        return False

    changed = False
    meta = dict(doc.metadata_json or {}) if isinstance(doc.metadata_json, dict) else {}
    entries = _registration_scope_entries(meta)
    target_key = normalize_title_key(project_name or "")

    if entries and target_key:
        for entry in entries:
            if normalize_title_key(entry.get("projectName") or "") != target_key:
                continue
            prev = (entry.get("projectCode") or "").strip()
            prev_norm = normalize_document_number(prev) if prev else ""
            if prev_norm in old_codes or prev:
                if prev != new_code:
                    entry["projectCode"] = new_code
                    changed = True
        if changed:
            meta["registrationProjects"] = entries
            doc.metadata_json = meta
            _rebuild_doc_project_code_from_meta(doc, meta)
    else:
        prev_norm = normalize_document_number(doc.project_code or "")
        if prev_norm in old_codes or (doc.project_code or "").strip():
            if (doc.project_code or "").strip() != new_code:
                doc.project_code = new_code
                changed = True

    if changed:
        doc.updated_at = now_local()
    return changed


def sync_project_code_for_project(
    organization_id: Optional[str],
    new_code: str,
    *,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
    registered_country: Optional[str] = None,
    old_codes: Optional[Iterable[str]] = None,
) -> dict[str, int]:
    """同步项目编号字段（不修改受控文件编号/document_number）。"""
    display_code = (new_code or "").strip()
    norm_new = normalize_document_number(display_code)
    if not norm_new:
        return {"uploads": 0, "documents": 0, "allocations": 0}

    resolved_country = registered_country
    if not (resolved_country or "").strip() and project_id:
        proj = find_page1_project(project_id=project_id, project_name=project_name)
        if proj:
            resolved_country = getattr(proj, "registered_country", None)

    old_norms = {normalize_document_number(c) for c in (old_codes or []) if c}
    org = (organization_id or "").strip() or None

    upload_updates = 0
    upload_q = UploadRecord.query
    if org:
        upload_q = upload_q.filter(
            (UploadRecord.organization_id == org) | (UploadRecord.organization_id.is_(None))
        )
    for row in upload_q.all():
        if not record_belongs_to_project(
            record_project_id=row.project_id,
            record_project_name=row.project_name,
            record_registered_country=row.country,
            project_id=project_id,
            project_name=project_name,
            registered_country=resolved_country,
        ):
            continue
        prev = (row.project_code or "").strip()
        if not prev:
            continue
        if old_norms and normalize_document_number(prev) not in old_norms:
            continue
        if prev != display_code:
            row.project_code = display_code
            upload_updates += 1
        if project_id and not (row.project_id or "").strip():
            row.project_id = project_id
            upload_updates += 1

    doc_updates = 0
    doc_q = ControlledDocument.query.filter_by(status="controlled")
    if org:
        doc_q = doc_q.filter_by(organization_id=org)
    for row in doc_q.all():
        if project_id and not (row.project_id or "").strip():
            from webapp.document_control.project_link import (
                link_controlled_document_to_page1_project,
            )

            link_controlled_document_to_page1_project(row, organization_id=org)
        if _sync_controlled_document_code(
            row,
            project_id=project_id,
            project_name=project_name,
            registered_country=resolved_country,
            new_code=display_code,
            old_codes=old_norms,
        ):
            doc_updates += 1

    alloc_updates = 0
    alloc_q = NumberAllocation.query
    if org:
        alloc_q = alloc_q.filter_by(organization_id=org)
    pid = (project_id or "").strip()
    for row in alloc_q.all():
        if pid and (row.project_id or "").strip() != pid:
            continue
        if not pid:
            continue
        prev = (row.project_code or "").strip()
        if not prev:
            continue
        if old_norms and normalize_document_number(prev) not in old_norms:
            continue
        if prev != display_code:
            row.project_code = display_code
            alloc_updates += 1

    project_updates = 0
    pid = (project_id or "").strip()
    if pid:
        proj = Project.query.get(pid)
        if proj and (proj.project_code or "").strip() != display_code:
            proj.project_code = display_code
            project_updates += 1

    if upload_updates or doc_updates or alloc_updates or project_updates:
        db.session.flush()

    return {
        "uploads": upload_updates,
        "documents": doc_updates,
        "allocations": alloc_updates,
        "projects": project_updates,
    }


def find_project_code_conflict(
    organization_id: Optional[str],
    project_code: str,
    *,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
    registered_country: Optional[str] = None,
    exclude_upload_id: Optional[str] = None,
    exclude_document_id: Optional[str] = None,
    confirm_sync: bool = False,
) -> Optional[str]:
    """兼容旧调用：仅返回硬错误文案；同项目变更需确认时不返回错误。"""
    gate = gate_project_code_save(
        organization_id,
        project_code,
        project_id=project_id,
        project_name=project_name,
        registered_country=registered_country,
        exclude_upload_id=exclude_upload_id,
        exclude_document_id=exclude_document_id,
        confirm_sync=confirm_sync,
    )
    if gate and gate[0] == "error":
        return gate[1]
    return None
