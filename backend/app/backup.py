"""本地加密备份：口令派生密钥 + Fernet 对称加密（cryptography）。

备份包 JSON 结构（加密态）：
    {"version": "moneyhelper-backup-v1", "encrypted": true, "kdf": "pbkdf2-sha256",
     "iters": 200000, "salt": "<b64>", "payload": "<b64 Fernet token>"}

口令只用于派生密钥，绝不落盘、不随备份包保存。忘记口令即无法恢复——
这是财务数据的刻意设计（宁可打不开，不能被人打开）。
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# PBKDF2-SHA256 迭代数（OWASP 建议 ≥600k）。每次导出会把当次迭代数写入备份包
# （"iters"），解密时读取该值派生密钥——因此即便以后上调此常量，旧备份仍可解开。
_ITERS = 600_000
# 解密时允许的迭代数范围：下限防过弱派生，上限防恶意构造超大迭代数拖垮解密（DoS）
_ITERS_MIN = 100_000
_ITERS_MAX = 2_000_000
_VERSION = "moneyhelper-backup-v1"


def _derive(passphrase: str, salt: bytes, iterations: int = _ITERS) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(passphrase.encode("utf-8"))


def _read_iters(payload: dict[str, Any]) -> int:
    """从备份包读取迭代数（带上下限保护），非法时回退默认值。"""
    try:
        iters = int(payload.get("iters") or _ITERS)
    except (TypeError, ValueError):
        return _ITERS
    if iters < _ITERS_MIN or iters > _ITERS_MAX:
        return _ITERS
    return iters


def encrypt_export(data: dict[str, Any], passphrase: str) -> dict[str, Any]:
    """全量导出数据 → 加密备份包（不包含口令本身）。"""
    salt = secrets.token_bytes(16)
    f = Fernet(base64.urlsafe_b64encode(_derive(passphrase, salt)))
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    token = f.encrypt(raw)
    return {
        "version": _VERSION,
        "encrypted": True,
        "kdf": "pbkdf2-sha256",
        "iters": _ITERS,
        "salt": base64.b64encode(salt).decode(),
        "payload": token.decode(),
    }


def decrypt_export(payload: dict[str, Any], passphrase: str) -> dict[str, Any]:
    """加密备份包 + 口令 → 原始导出 JSON。口令错误抛 ValueError。"""
    if not payload.get("encrypted"):
        return payload
    try:
        salt = base64.b64decode(str(payload.get("salt") or ""))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("备份文件已损坏（salt 无法解析）") from exc
    iters = _read_iters(payload)
    f = Fernet(base64.urlsafe_b64encode(_derive(passphrase, salt, iters)))
    try:
        raw = f.decrypt(str(payload.get("payload") or "").encode())
    except (InvalidToken, binascii.Error, ValueError) as exc:
        raise ValueError("口令不正确或备份文件已损坏") from exc
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("备份内容格式不正确")
    return data
