"""鉴权中间件：口令/JWT 总闸、租户上下文、后台任务登记、操作者归属。"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from .auth import verify_api_token
from .mw_common import _SKIP_AUTH_PATHS

_background_tasks: set[asyncio.Task[None]] = set()


def spawn_background(coro: Coroutine[Any, Any, None]) -> None:
    """登记后台任务并自动在完成时移除引用；登记失败不影响主流程。"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def auth_gate(request: Request) -> JSONResponse | int:
    """鉴权总闸：主 API（api_auth）与 MCP 子应用共用的同一套判定。

    返回 JSONResponse 表示拒绝；返回 int 表示放行并给出租户 id。

    - 共享口令模式：配置了 API_TOKEN 时，口令是进入实例的唯一凭据；
    - 多用户模式：库中已有账号时，除共享口令外必须具备有效 JWT（fail-closed）。
      此前只有主 API 有这条判定、MCP 侧没有——已注册用户的实例里，
      /mcp 仍可无令牌调用卖出/备份等写工具，形成第二条裸奔的信任边界。

    MCP 子应用的 mount 会绕过主 app 的 @app.middleware("http") 中间件链，
    因此两边都必须显式走这个闸，避免"主站有防护、MCP 侧裸奔"。
    """
    key = os.getenv("API_TOKEN", "").strip()
    if key and verify_api_token(request) is None:
        return JSONResponse({"error": "需要访问口令"}, status_code=401)

    from .db.tenant import LOCAL_USER_ID

    tenant_id = _resolve_tenant(request)
    shared = verify_api_token(request)
    # JWT 签名有效不代表账号仍然可用：停用/删除账号的旧令牌必须在总闸失效。
    # 此前只有 require_user 查用户状态，导致大量无该依赖的路由仍可访问。
    if tenant_id != LOCAL_USER_ID and not await _user_is_active(tenant_id):
        return JSONResponse({"error": "账号不存在或已停用"}, status_code=401)
    needs_login = (
        tenant_id == LOCAL_USER_ID
        and shared is None
        and not getattr(request.state, "auth_via_jwt", False)
    )
    if needs_login and await _has_registered_users():
        return JSONResponse(
            {"error": "需要登录（该实例已启用账号体系）"}, status_code=401
        )
    return tenant_id


async def api_auth(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path in _SKIP_AUTH_PATHS:
        return await call_next(request)

    key = os.getenv("API_TOKEN", "").strip()
    gate = await auth_gate(request)
    if isinstance(gate, JSONResponse):
        return gate
    tenant_id = gate

    # 审计中间件在 call_next 之后写日志，此时 ContextVar 已被重置；
    # 把租户 id 留在 request.state，供审计归属使用。
    request.state.tenant_id = tenant_id

    # 审计归属：把本请求解析到的操作者写进 ContextVar，后续 record_provenance
    # 不传 username 时自动归属该用户（此前各路由硬编码 "system"，审计链全失真）。
    actor = _resolve_actor(request, key)
    if actor:
        from .provenance import set_request_actor

        set_request_actor(actor)

    # 租户隔离：JWT 用户决定这一请求读写哪份数据。
    # 无 JWT 时保持默认租户 0（本机单用户模式）；共享口令模式下同样归 0——
    # 一个实例仍然是一个账本。
    from .db.org import resolve_tenant_id
    from .db.tenant import (
        reset_current_tenant_id,
        reset_current_user_id,
        set_current_tenant_id,
        set_current_user_id,
    )

    user_token = set_current_user_id(tenant_id)
    try:
        # 组织域使用显式 tenant_id；个人租户 id == user_id，现有账本仍读 user_id。
        try:
            org_tenant_id = await resolve_tenant_id(tenant_id)
        except Exception:  # noqa: BLE001 — 映射失败保持旧行为，不放大成 500
            org_tenant_id = tenant_id
        tenant_token = set_current_tenant_id(org_tenant_id)
        try:
            return await call_next(request)
        finally:
            reset_current_tenant_id(tenant_token)
    finally:
        reset_current_user_id(user_token)


async def _has_registered_users() -> bool:
    """当前实例是否已启用账号体系（有任意注册用户）。失败时按"有用户"处理（fail-closed）。"""
    try:
        from . import db

        return await db.user_count() > 0
    except Exception:  # noqa: BLE001 — 查询失败时宁可要求登录
        return True


async def _user_is_active(user_id: int) -> bool:
    """JWT 指向的账号仍存在且未停用；查询失败按不可用处理（fail-closed）。"""
    try:
        from . import db

        user = await db.user_get(user_id)
        return bool(user) and not user.get("disabled")
    except Exception:  # noqa: BLE001 — 无法确认就拒绝
        return False


def _resolve_tenant(request: Request) -> int:
    """从 Bearer JWT 解析租户（用户 id）；解析不出来归默认租户。"""
    from .db.tenant import LOCAL_USER_ID

    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return LOCAL_USER_ID
    try:
        from . import auth as auth_mod

        payload = auth_mod._decode_jwt(header[7:].strip())
        uid = int(payload.get("sub") or 0)
    except Exception:  # noqa: BLE001 — 解析失败按默认租户处理（鉴权层已拦截非法口令）
        return LOCAL_USER_ID
    if uid > 0:
        # 明确标记"本次请求带了合法 JWT"，供 api_auth 判定是否需要强制登录
        request.state.auth_via_jwt = True
    return uid


def _resolve_actor(request: Request, api_token: str) -> str:
    """尽力解析当前请求的操作者用户名（解析失败返回空串，回落到默认 system）。

    无口令模式（单机自用）统一记 "local"：真实使用人就是本机用户，
    记 "system" 会让审计链看起来像程序自动执行的。
    """
    shared = verify_api_token(request)
    if shared:
        return str(shared.get("username") or "local")
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return "local"
    try:
        from . import auth as auth_mod

        payload = auth_mod._decode_jwt(header[7:].strip())
        uid = int(payload.get("sub") or 0)
    except Exception:  # noqa: BLE001 — 审计归属失败不影响业务
        return "local"
    return f"user:{uid}" if uid else "local"
