"""使用 Flask SECRET_KEY 派生 Fernet，加密存储用户 LLM api_key。"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def _fernet(secret: str) -> Fernet:
    key = hashlib.sha256((secret or "aiword-llm-key").encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def normalize_api_key_plain(plain: str) -> str:
    """保存/解密后统一清理：去 BOM、换行、误粘贴的 Bearer 前缀、零宽字符等。"""
    s = (plain or "").replace("\r", "").replace("\n", "")
    for zw in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u00a0"):
        s = s.replace(zw, "")
    s = s.strip()
    while s.lower().startswith("bearer "):
        s = s[7:].strip()
    return s


def normalize_llm_base_url(provider: str, base: str) -> str:
    """OpenAI 兼容 Base URL 规范化（DeepSeek 缺 /v1 时自动补全）。"""
    p = (provider or "").strip().lower()
    b = (base or "").strip().rstrip("/")
    if not b:
        return ""
    if p == "deepseek" and "api.deepseek.com" in b.lower():
        path = b.split("://", 1)[-1].split("/", 1)
        rest = path[1] if len(path) > 1 else ""
        if not rest.startswith("v1"):
            return b + "/v1"
    return b


def coerce_encrypted_blob(token: bytes | memoryview | bytearray | str | None) -> bytes | None:
    """MySQL BLOB 经部分驱动可能为 memoryview/str，统一转为 bytes。"""
    if not token:
        return None
    if isinstance(token, memoryview):
        return token.tobytes()
    if isinstance(token, (bytes, bytearray)):
        return bytes(token)
    if isinstance(token, str):
        return token.encode("latin-1")
    return None


def encrypt_api_key(app_secret_key: str, plain: str) -> bytes:
    norm = normalize_api_key_plain(plain)
    return _fernet(app_secret_key).encrypt(norm.encode("utf-8"))


def decrypt_api_key(app_secret_key: str, token: bytes | memoryview | bytearray | str | None) -> str:
    blob = coerce_encrypted_blob(token)
    if not blob:
        return ""
    try:
        return normalize_api_key_plain(
            _fernet(app_secret_key).decrypt(blob).decode("utf-8")
        )
    except Exception:
        return ""


def verify_api_key_roundtrip(app_secret_key: str, plain: str) -> bool:
    """保存前自检：加密再解密须与规范化明文一致（排除 SECRET_KEY/存储损坏）。"""
    norm = normalize_api_key_plain(plain)
    if not norm:
        return True
    enc = encrypt_api_key(app_secret_key, norm)
    return decrypt_api_key(app_secret_key, enc) == norm
