# -*- coding: utf-8 -*-
"""aicheckword 核心 REST 代理（训练/审核点/知识库/文本审核等，非 integration job 流）。"""
from __future__ import annotations

import json
from typing import Any, Optional

import requests
from flask import jsonify

from ._integration_common import (
    format_upstream_request_error,
    integration_api_base,
    integration_requests_timeout,
    msg_upstream_http,
    msg_upstream_not_configured_env,
    upstream_headers,
)


def upstream_unconfigured_response():
    return jsonify({"message": msg_upstream_not_configured_env()}), 503


def upstream_form_post(
    path: str,
    *,
    data: dict[str, Any] | None = None,
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
    organization_id: str | None = None,
    read_seconds: int = 600,
    extra_headers: dict[str, str] | None = None,
) -> tuple[Any, int]:
    base = integration_api_base()
    if not base:
        return upstream_unconfigured_response()
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    headers = upstream_headers(for_multipart=bool(files), organization_id=organization_id)
    if extra_headers:
        headers.update(extra_headers)
    try:
        resp = requests.post(
            url,
            data=data or {},
            files=files or [],
            headers=headers,
            timeout=integration_requests_timeout(read_seconds=read_seconds),
        )
    except requests.RequestException as exc:
        return jsonify({"message": format_upstream_request_error(exc, base)}), 502
    try:
        body = resp.json()
    except Exception:
        body = {"raw": (resp.text or "")[:8000]}
    if resp.status_code >= 400:
        detail = body.get("detail") if isinstance(body, dict) else None
        msg = detail or (body.get("message") if isinstance(body, dict) else None) or f"上游 HTTP {resp.status_code}"
        return jsonify({"message": msg, "upstream": body}), resp.status_code
    return jsonify({"ok": True, "upstream": body, "organizationId": organization_id}), 200


def upstream_json_post(
    path: str,
    *,
    body: dict[str, Any],
    organization_id: str | None = None,
    read_seconds: int = 120,
    extra_headers: dict[str, str] | None = None,
) -> tuple[Any, int]:
    base = integration_api_base()
    if not base:
        return upstream_unconfigured_response()
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    headers = upstream_headers(for_multipart=False, organization_id=organization_id)
    if extra_headers:
        headers.update(extra_headers)
    try:
        resp = requests.post(
            url,
            json=body,
            headers=headers,
            timeout=integration_requests_timeout(read_seconds=read_seconds),
        )
    except requests.RequestException as exc:
        return jsonify({"message": format_upstream_request_error(exc, base)}), 502
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": (resp.text or "")[:8000]}
    if resp.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        msg = detail or (payload.get("message") if isinstance(payload, dict) else None) or f"上游 HTTP {resp.status_code}"
        return jsonify({"message": msg, "upstream": payload}), resp.status_code
    return jsonify({"ok": True, "upstream": payload, "organizationId": organization_id}), 200


def upstream_get(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    organization_id: str | None = None,
    read_seconds: int = 30,
) -> tuple[Any, int]:
    base = integration_api_base()
    if not base:
        return upstream_unconfigured_response()
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    try:
        resp = requests.get(
            url,
            params=params or {},
            headers=upstream_headers(for_multipart=False, organization_id=organization_id),
            timeout=integration_requests_timeout(read_seconds=read_seconds),
        )
    except requests.RequestException as exc:
        return jsonify({"message": format_upstream_request_error(exc, base)}), 502
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": (resp.text or "")[:8000]}
    if resp.status_code >= 400:
        return jsonify({"message": msg_upstream_http(resp.status_code), "upstream": payload}), resp.status_code
    return jsonify({"ok": True, "upstream": payload, "organizationId": organization_id}), 200


def parse_checklist_json(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, str):
        data = json.loads(raw)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict) and isinstance(data.get("checklist"), list):
            return [x for x in data["checklist"] if isinstance(x, dict)]
    if isinstance(raw, dict) and isinstance(raw.get("checklist"), list):
        return [x for x in raw["checklist"] if isinstance(x, dict)]
    raise ValueError("checklist 须为 JSON 数组或含 checklist 字段的对象")
