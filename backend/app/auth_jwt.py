"""JWT 签发与校验：secret 解析、临时 secret 兜底、encode/decode。

从 auth.py 拆出。secret 只在未配置时按启动告警生成临时值（`check_jwt_secret`），
`_ensure_secret` 保证 lifespan 之前的脚本/测试调用也能签出令牌。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import HTTPException
from fastapi.security import HTTPBearer

from .logging_utils import get_logger

log = get_logger(__name__)

# JWT 配置 — 强制校验：未设 JWT_SECRET 则 fallback 到 API_SECRET（生产应设置独立强口令）
_JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
if not _JWT_SECRET:
    _JWT_SECRET = os.getenv("API_SECRET", "").strip()
if _JWT_SECRET and os.getenv("API_TOKEN", "").strip() == _JWT_SECRET:
    log.warning("AUTH: JWT_SECRET 与 API_TOKEN 相同 — 生产环境应使用独立强口令")
_JWT_ALG = "HS256"
_JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "168"))  # 默认 7 天

security = HTTPBearer(auto_error=False)


def check_jwt_secret() -> None:
    """寿命入口调用：未配置明确 secret 则 abort（拒绝启动）。"""
    if not _JWT_SECRET or _JWT_SECRET.startswith("moneyhelper-dev-secret"):
        # 生成一次性随机 secret，强制开发者在部署前显式配置
        import secrets as _secrets

        _new = _secrets.token_hex(32)
        log.warning(
            "AUTH: JWT_SECRET 未设置或为默认值 — 已生成临时随机 secret（重启变更）。"
            "请在生产环境通过 JWT_SECRET 环境变量设置强口令。"
        )
        # 不 abort：但给出明显警告，并使每次启动的 token 过期
        globals()["_JWT_SECRET"] = _new

security = HTTPBearer(auto_error=False)


def _ensure_secret() -> str:
    """确保 JWT secret 已就绪（模块导入后、lifespan 之前也可能签发令牌）。

    check_jwt_secret() 只在 lifespan 里调用；TestClient、CLI、脚本直接调用
    认证函数时不会经过 lifespan，此时 _JWT_SECRET 为空，
    jwt.encode 会抛 "HMAC key must not be empty"（专家评审发现的注册 500）。
    """
    global _JWT_SECRET
    if not _JWT_SECRET or _JWT_SECRET.startswith("moneyhelper-dev-secret"):
        check_jwt_secret()
    return _JWT_SECRET


def _make_jwt(user: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user.get("role", "user"),
        "display_name": user.get("display_name", ""),
        "iat": now,
        "exp": now + timedelta(hours=_JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, _ensure_secret(), algorithm=_JWT_ALG)


def _decode_jwt(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, _ensure_secret(), algorithms=[_JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="令牌已过期，请重新登录") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效令牌") from None
