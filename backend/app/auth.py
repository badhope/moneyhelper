"""用户认证门面：登录/注册/我的信息端点，其余按域拆到 auth_jwt / auth_models /
auth_ratelimit / auth_guard，并在此 re-export 保持 `auth.<name>` 兼容。
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request

from . import db
from .auth_guard import require_user
from .auth_jwt import _make_jwt
from .auth_models import LoginReq, RegisterReq, TokenResp
from .auth_ratelimit import _rate_limited, client_ip
from .logging_utils import get_logger

log = get_logger(__name__)


async def login(req: LoginReq, request: Request | None = None) -> TokenResp:
    # 暴力破解保护：真实客户端 IP + 用户名 5 次 / 分钟（防分布式爆破）
    ip = client_ip(request)
    rate_key = f"{ip}:{req.username}"
    if _rate_limited(rate_key) or _rate_limited(f"user:{req.username}"):
        log.warning(
            "AUTH: rate-limited login attempt user=%s ip=%s", req.username, ip
        )
        raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后再试")

    user = await db.user_get_by_username(req.username)
    if not user or user.get("disabled"):
        log.warning(
            "AUTH: login failed user=%s ip=%s reason=%s",
            req.username,
            ip,
            "user_not_found" if not user else "disabled",
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not await db.user_verify_password(user, req.password):
        log.warning(
            "AUTH: login failed user=%s ip=%s reason=bad_password",
            req.username,
            ip,
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    await db.user_update_last_login(user["id"])
    token = _make_jwt(user)
    log.info("AUTH: login user=%s id=%d", user["username"], user["id"])
    return TokenResp(
        access_token=token,
        user={
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name", ""),
            "role": user.get("role", "user"),
        },
    )


async def register(req: RegisterReq) -> TokenResp:
    """注册：仅当系统中尚无任何用户时开放（首次部署自动创建首个管理员）。"""
    user_count = await db.user_count()
    if user_count > 0:
        raise HTTPException(status_code=403, detail="注册已关闭，请联系管理员")

    if len(req.username) < 3 or len(req.password) < 8:
        raise HTTPException(status_code=400, detail="用户名至少 3 位、密码至少 8 位")
    existing = await db.user_get_by_username(req.username)
    if existing:
        raise HTTPException(status_code=409, detail="用户名已被占用")
    uid = await db.user_create(
        req.username, req.password, display_name=req.display_name or req.username
    )
    user = await db.user_get(uid)
    if not user:
        raise HTTPException(status_code=500, detail="创建失败")
    token = _make_jwt(user)
    log.info(
        "AUTH: first user registered id=%d username=%s (auto-admin)",
        uid,
        user["username"],
    )
    return TokenResp(
        access_token=token,
        user={
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name", ""),
            "role": user.get("role", "user"),
        },
    )


async def me(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name", ""),
        "role": user.get("role", "user"),
        "last_login": user.get("last_login", ""),
        "created_at": user.get("created_at", ""),
    }


from .auth_guard import (  # noqa: F401,E402 — 对外同名导出
    admin_only,
    get_current_user,
    require_instance_admin,
    require_user,
    verify_api_token,
)
from .auth_jwt import (  # noqa: F401,E402
    _JWT_ALG,
    _JWT_EXPIRE_HOURS,
    _decode_jwt,
    _ensure_secret,
    check_jwt_secret,
    security,
)
from .auth_ratelimit import (  # noqa: F401,E402
    _LOGIN_ATTEMPTS,
    _MAX_ATTEMPTS,
    _WINDOW_SECONDS,
)
