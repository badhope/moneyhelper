"""鉴权依赖：旧 API_TOKEN 共享口令、JWT 当前用户、管理员与实例管理员边界。"""

from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

from . import db
from .auth_jwt import _decode_jwt, security


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


async def admin_only(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


async def require_instance_admin(
    user: dict[str, Any] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """实例级管理操作（MCP 配置、审计清空、备份恢复）的管理员边界。

    三种放行情况：
    - 共享 API_TOKEN：verify_api_token 已把它映射为 admin；
    - 已登录的 admin 用户；
    - 本机单用户模式：未设 API_TOKEN 且实例内还没有任何账号。

    其余一律 401/403。这里不复用 admin_only，因为单机无账号模式没有 JWT，
    但它确实是本机所有者，不能被误伤。
    """
    if user is None:
        if os.getenv("API_TOKEN", "").strip():
            raise HTTPException(status_code=401, detail="需要登录或访问口令")
        try:
            has_any_user = await db.user_count() > 0
        except Exception:  # noqa: BLE001 — 查询失败按"有账号"处理（fail-closed）
            has_any_user = True
        if has_any_user:
            raise HTTPException(status_code=401, detail="需要登录（该实例已启用账号体系）")
        return {
            "id": 0,
            "username": "local",
            "role": "admin",
            "display_name": "本机用户",
        }
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
