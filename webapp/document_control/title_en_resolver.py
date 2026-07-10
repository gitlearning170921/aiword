"""申请编号：文件名称 → 英文名（台账/缓存/提取/自动翻译）。"""

from __future__ import annotations

import re
from typing import Optional

import requests
from flask import session

from webapp.user_facing import user_facing_upstream_error

from .subtype_resolver import english_words, normalize_title_key

_EN_SEGMENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9\s\-,/()]*[A-Za-z0-9]|[A-Za-z]+")
_QUOTE_RE = re.compile(r'^[\s"\'「」『』《》]+|[\s"\'「」『』《》]+$')


def _clean_title_en(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    lines = raw.splitlines()
    line = (lines[0] if lines else raw).strip()
    line = _QUOTE_RE.sub("", line)
    return line[:255]


def extract_embedded_english_title(title: str) -> str:
    parts = [p.strip() for p in _EN_SEGMENT_RE.findall(title or "") if p.strip()]
    return " ".join(parts).strip()


def has_sufficient_english_for_subtype(title: str) -> bool:
    words = english_words(title)
    if len(words) >= 2:
        return True
    if len(words) == 1 and len(words[0]) >= 4:
        return True
    embedded = extract_embedded_english_title(title)
    return len(english_words(embedded)) >= 2


def lookup_title_en_from_ledger(org_id: str, title: str) -> Optional[str]:
    """精确同名台账记录中的英文名（含 metadata_json.titleEn）。"""
    from webapp.models import ControlledDocument

    key = normalize_title_key(title)
    if not key or not (org_id or "").strip():
        return None
    rows = (
        ControlledDocument.query.filter_by(organization_id=org_id.strip())
        .order_by(ControlledDocument.updated_at.desc(), ControlledDocument.created_at.desc())
        .all()
    )
    for doc in rows:
        if normalize_title_key(doc.title or "") != key:
            continue
        te = _clean_title_en(doc.title_en or "")
        if not te and isinstance(doc.metadata_json, dict):
            te = _clean_title_en(str(doc.metadata_json.get("titleEn") or ""))
        if te:
            return te
    return None


def lookup_title_en_from_cache(org_id: str, title: str) -> Optional[str]:
    from webapp.models import DocumentTitleTranslationCache

    key = normalize_title_key(title)
    if not key or not (org_id or "").strip():
        return None
    row = DocumentTitleTranslationCache.query.filter_by(
        organization_id=org_id.strip(),
        title_key=key,
    ).first()
    if not row:
        return None
    te = _clean_title_en(row.title_en or "")
    return te or None


def persist_title_en_cache(
    org_id: str,
    title: str,
    title_en: str,
    *,
    source: str = "translated",
) -> None:
    from webapp import db
    from webapp.models import DocumentTitleTranslationCache

    key = normalize_title_key(title)
    te = _clean_title_en(title_en)
    oid = (org_id or "").strip()
    if not key or not te or not oid:
        return
    row = DocumentTitleTranslationCache.query.filter_by(
        organization_id=oid,
        title_key=key,
    ).first()
    raw = (title or "").strip()[:255] or None
    src = (source or "translated").strip() or "translated"
    if row:
        row.title_en = te
        row.title_raw = raw or row.title_raw
        row.source = src
        db.session.add(row)
    else:
        db.session.add(
            DocumentTitleTranslationCache(
                organization_id=oid,
                title_key=key,
                title_raw=raw,
                title_en=te,
                source=src,
            )
        )


def translate_title_via_upstream(
    title: str,
    *,
    org_id: str,
    collection: str,
) -> str:
    from webapp._integration_common import (
        client_llm_headers_for_session,
        format_upstream_request_error,
        integration_api_base,
        integration_requests_timeout,
        upstream_headers,
    )

    base = (integration_api_base() or "").strip().rstrip("/")
    if not base:
        raise ValueError("文档服务未配置，无法自动翻译文件名称")
    headers = {
        **upstream_headers(for_multipart=False, organization_id=org_id),
        **client_llm_headers_for_session(),
    }
    payload = {"text": (title or "").strip(), "collection": collection or "regulations"}
    try:
        resp = requests.post(
            f"{base}/api/integration/document-control/translate-title",
            json=payload,
            headers=headers,
            timeout=integration_requests_timeout(read_seconds=90),
        )
    except requests.RequestException as exc:
        raise ValueError(
            user_facing_upstream_error(
                f"翻译文件名称失败：{format_upstream_request_error(exc, base)}",
                "自动翻译文件名称失败，请稍后重试或在名称中补充英文",
            )
        ) from exc
    if resp.status_code != 200:
        snippet = (resp.text or "")[:200]
        raise ValueError(
            user_facing_upstream_error(
                f"翻译接口 HTTP {resp.status_code}: {snippet}",
                "自动翻译文件名称失败，请稍后重试或在名称中补充英文",
            )
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise ValueError("自动翻译返回格式异常") from exc
    title_en = _clean_title_en(str((data or {}).get("titleEn") or ""))
    if not title_en:
        raise ValueError("自动翻译未得到有效英文名称，请在名称中补充英文单词")
    return title_en


def resolve_title_en_for_issue(
    title: str,
    *,
    org_id: str,
    collection: str,
    cached_title_en: Optional[str] = None,
    persist_translation: bool = True,
    session_cache: Optional[dict[str, tuple[str, str]]] = None,
) -> tuple[str, str]:
    """返回 (title_en, source)。

    source: cached / embedded / ledger / cache / translated
    """
    manual = _clean_title_en(cached_title_en or "")
    if manual:
        return manual, "cached"

    raw = (title or "").strip()
    if not raw:
        raise ValueError("请填写文件名称")

    key = normalize_title_key(raw)
    if session_cache is not None and key in session_cache:
        te, src = session_cache[key]
        if te:
            return te, src

    embedded = _clean_title_en(extract_embedded_english_title(raw))
    if embedded:
        if session_cache is not None:
            session_cache[key] = (embedded, "embedded")
        return embedded, "embedded"
    words = english_words(raw)
    if words:
        te = _clean_title_en(" ".join(words))
        if session_cache is not None:
            session_cache[key] = (te, "embedded")
        return te, "embedded"

    ledger_te = lookup_title_en_from_ledger(org_id, raw)
    if ledger_te:
        if session_cache is not None:
            session_cache[key] = (ledger_te, "ledger")
        return ledger_te, "ledger"

    cache_te = lookup_title_en_from_cache(org_id, raw)
    if cache_te:
        if session_cache is not None:
            session_cache[key] = (cache_te, "cache")
        return cache_te, "cache"

    if not session.get("user_id"):
        raise ValueError("请先登录后再申请编号（需自动翻译文件名称）")
    translated = translate_title_via_upstream(raw, org_id=org_id, collection=collection)
    if persist_translation:
        persist_title_en_cache(org_id, raw, translated, source="translated")
    if session_cache is not None:
        session_cache[key] = (translated, "translated")
    return translated, "translated"
