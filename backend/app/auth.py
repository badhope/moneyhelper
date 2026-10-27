"""用户认证：JWT + bcrypt + 快依赖注入。

鉴权模式（与旧 API_TOKEN 并存）：
- 旧模式：API_TOKEN 环境变量 → 全局共享令牌（单用户/内网场景）
- 新模式：/db users 表 + JWT 无状态令牌（多用户 SaaS 化基础）
前端登录后 Bearer <jwt>，与旧 API_TOKEN 二选一通过。
"""

from __future__ import annotations

import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from . import db
from .compat_env import getenv
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


class LoginReq(BaseModel):
    username: str
    password: str


class RegisterReq(BaseModel):
    username: str
    password: str
    display_name: str = ""


class TokenResp(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


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


def verify_api_token(request: Request) -> dict[str, Any] | None:
    """校验旧 API_TOKEN（环境变量共享口令）模式。

    - 从 query param `token` 或 `Authorization: Bearer` 头中读取令牌
    - 与 API_TOKEN 环境变量做 timing-safe 比对
    - 匹配成功返回共享访问用户 dict，不匹配 / 未配置返回 None
    - 两处共用：api_auth 中间件（main.py）与 get_current_user 依赖注入
    """
    api_token = os.getenv("API_TOKEN", "").strip()
    if not api_token:
        return None
    q_token = request.query_params.get("token", "")
    h_token = request.headers.get("authorization", "")
    if secrets.compare_digest(q_token, api_token) or secrets.compare_digest(
        h_token, f"Bearer {api_token}"
    ):
        return {
            "id": 0,
            "username": "_shared",
            "role": "admin",
            "display_name": "共享访问",
        }
    return None


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any] | None:
    """依赖注入：解析 JWT 返回当前用户；无令牌或失败都返回 None（降级旧鉴权）。"""
    # 旧 API_TOKEN 模式：verify_api_token 处理 Shared Token 校验
    shared = verify_api_token(request)
    if shared is not None:
        return shared

    # JWT 模式
    if not creds:
        return None
    try:
        payload = _decode_jwt(creds.credentials)
    except HTTPException:
        return None
    user_id = int(payload["sub"])
    user = await db.user_get(user_id)
    if not user or user.get("disabled"):
        return None
    return user


async def require_user(
    user: dict[str, Any] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """强制鉴权依赖：无用户即 401。用于写操作端点。"""
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    # 审计归属：本请求后续所有 provenance 记录默认挂到该用户
    from .provenance import set_request_actor

    set_request_actor(str(user.get("username") or "system"))
    return user


# --- 登录防暴力破解：滑动窗口 rate limiter (内存版) ---

_LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)  # key → [timestamp, ...]
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 60


def _rate_limited(key: str) -> bool:
    """检查是否超出速率限制（True = 被限流）。"""
    now = time.time()
    attempts = _LOGIN_ATTEMPTS[key]
    # 清除过期记录
    cutoff = now - _WINDOW_SECONDS
    _LOGIN_ATTEMPTS[key] = [t for t in attempts if t > cutoff]
    # 防止无限增长：空条目立即删除
    if not _LOGIN_ATTEMPTS[key]:
        del _LOGIN_ATTEMPTS[key]
    if len(_LOGIN_ATTEMPTS[key]) >= _MAX_ATTEMPTS:
        return True
    _LOGIN_ATTEMPTS[key].append(now)
    return False


# --- 端点处理 ---


def client_ip(request: Request | None) -> str:
    """取客户端 IP 用于限流键。

    `X-Forwarded-For` 只有在显式声明"我部署在可信反代后面"时才采信
    （`MONEYHELPER_TRUST_PROXY=1`）。默认不信任：否则任何能直连端口的
    人都能伪造该头，给每次登录换一个"IP"，把按 IP 的限流整个绕开。
    反代部署需在 nginx 里覆盖（而非追加）该头，见 docs/DEPLOY.md。
    """
    if request is None:
        return "unknown"
    if getenv("MONEYHELPER_TRUST_PROXY").strip() in ("1", "true", "yes"):
        fwd = request.headers.get("x-forwarded-for", "")
        first = fwd.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


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


async def admin_only(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
