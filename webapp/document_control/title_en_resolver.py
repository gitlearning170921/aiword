"""申请编号：文件名称 → 英文名（提取或自动翻译）。"""

from __future__ import annotations

import re
from typing import Optional

import requests
from flask import session

from webapp.user_facing import user_facing_upstream_error

from .subtype_resolver import english_words

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
) -> tuple[str, str]:
    """返回 (title_en, source)；source 为 embedded / translated / cached。"""
    manual = _clean_title_en(cached_title_en or "")
    if manual:
        return manual, "cached"
    raw = (title or "").strip()
    if not raw:
        raise ValueError("请填写文件名称")

    embedded = _clean_title_en(extract_embedded_english_title(raw))
    if embedded:
        return embedded, "embedded"
    words = english_words(raw)
    if words:
        return _clean_title_en(" ".join(words)), "embedded"

    if not session.get("user_id"):
        raise ValueError("请先登录后再申请编号（需自动翻译文件名称）")
    translated = translate_title_via_upstream(raw, org_id=org_id, collection=collection)
    return translated, "translated"
