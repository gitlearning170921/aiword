# -*- coding: utf-8 -*-
"""钉钉 HTTP 回调加解密（Token + EncodingAESKey + OwnerKey，与开放平台文档一致）。"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import struct
from typing import Any, Optional

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class DingTalkCallbackCryptoError(Exception):
    pass


class DingTalkCallbackCrypto:
    """企业内部应用 / 机器人 HTTP 回调消息体加解密。"""

    BLOCK_SIZE = 32

    def __init__(self, token: str, encoding_aes_key: str, owner_key: str):
        self.token = (token or "").strip()
        self.owner_key = (owner_key or "").strip()
        aes_key = (encoding_aes_key or "").strip()
        if not self.token or not aes_key or not self.owner_key:
            raise DingTalkCallbackCryptoError("token / encoding_aes_key / owner_key 不能为空")
        try:
            self.aes_key = base64.b64decode(aes_key + "=")
        except Exception as e:
            raise DingTalkCallbackCryptoError(f"EncodingAESKey 无效: {e}") from e
        if len(self.aes_key) != 32:
            raise DingTalkCallbackCryptoError("EncodingAESKey 解码后须为 32 字节")

    @staticmethod
    def _sha1_signature(*parts: str) -> str:
        items = sorted(str(p) for p in parts)
        return hashlib.sha1("".join(items).encode("utf-8")).hexdigest()

    def _pad(self, data: bytes) -> bytes:
        pad_len = self.BLOCK_SIZE - (len(data) % self.BLOCK_SIZE)
        return data + bytes([pad_len] * pad_len)

    def _unpad(self, data: bytes) -> bytes:
        if not data:
            raise DingTalkCallbackCryptoError("解密结果为空")
        pad_len = data[-1]
        if pad_len < 1 or pad_len > self.BLOCK_SIZE:
            raise DingTalkCallbackCryptoError("解密 padding 无效")
        return data[:-pad_len]

    def encrypt(self, plain_text: str) -> str:
        msg = (plain_text or "").encode("utf-8")
        owner = self.owner_key.encode("utf-8")
        rand = secrets.token_bytes(16)
        body = rand + struct.pack(">I", len(msg)) + msg + owner
        body = self._pad(body)
        cipher = Cipher(
            algorithms.AES(self.aes_key),
            modes.CBC(self.aes_key[:16]),
            backend=default_backend(),
        )
        enc = cipher.encryptor()
        encrypted = enc.update(body) + enc.finalize()
        return base64.b64encode(encrypted).decode("utf-8")

    def decrypt(self, encrypt: str) -> str:
        try:
            raw = base64.b64decode(encrypt)
        except Exception as e:
            raise DingTalkCallbackCryptoError(f"encrypt Base64 无效: {e}") from e
        cipher = Cipher(
            algorithms.AES(self.aes_key),
            modes.CBC(self.aes_key[:16]),
            backend=default_backend(),
        )
        dec = cipher.decryptor()
        plain = self._unpad(dec.update(raw) + dec.finalize())
        if len(plain) < 20:
            raise DingTalkCallbackCryptoError("解密明文过短")
        msg_len = struct.unpack(">I", plain[16:20])[0]
        msg = plain[20 : 20 + msg_len]
        try:
            return msg.decode("utf-8")
        except UnicodeDecodeError as e:
            raise DingTalkCallbackCryptoError(f"解密消息非 UTF-8: {e}") from e

    def verify_and_decrypt(
        self,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        encrypt: str,
    ) -> str:
        sig = self._sha1_signature(self.token, timestamp, nonce, encrypt)
        if sig != (msg_signature or "").strip():
            raise DingTalkCallbackCryptoError("msg_signature 校验失败")
        return self.decrypt(encrypt)

    def encrypted_response_map(self, plain_text: str) -> dict[str, str]:
        encrypt = self.encrypt(plain_text)
        timestamp = str(int(__import__("time").time()))
        nonce = secrets.token_hex(8)
        signature = self._sha1_signature(self.token, timestamp, nonce, encrypt)
        return {
            "msg_signature": signature,
            "timeStamp": timestamp,
            "nonce": nonce,
            "encrypt": encrypt,
        }


def build_text_reply_json(content: str) -> str:
    return json.dumps(
        {"msgtype": "text", "text": {"content": content}},
        ensure_ascii=False,
    )


def parse_callback_query_args(args: Any) -> tuple[str, str, str]:
    """从 query 取 msg_signature / timestamp / nonce（兼容 signature / timestamp 命名）。"""
    sig = (
        args.get("msg_signature")
        or args.get("signature")
        or args.get("msgSignature")
        or ""
    )
    ts = args.get("timestamp") or args.get("timeStamp") or args.get("TimeStamp") or ""
    nonce = args.get("nonce") or args.get("Nonce") or ""
    return str(sig).strip(), str(ts).strip(), str(nonce).strip()
