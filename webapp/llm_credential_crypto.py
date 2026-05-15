"""使用 Flask SECRET_KEY 派生 Fernet，加密存储用户 LLM api_key。"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def _fernet(secret: str) -> Fernet:
    key = hashlib.sha256((secret or "aiword-llm-key").encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_api_key(app_secret_key: str, plain: str) -> bytes:
    return _fernet(app_secret_key).encrypt((plain or "").encode("utf-8"))


def decrypt_api_key(app_secret_key: str, token: bytes | None) -> str:
    if not token:
        return ""
    try:
        return _fernet(app_secret_key).decrypt(token).decode("utf-8")
    except Exception:
        return ""
