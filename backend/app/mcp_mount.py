"""MCP 传输层挂载：ASGI 构建、动态转发器、精确路径挂载与启动探活。

注册（mcp 实例 / `_tool` / 各域包装器 import）仍在 mcp_server，本模块只负责
把子应用安全地接进 FastAPI —— 请求到来时读 holder 里的当前实例，避免
session manager「每实例只能 run 一次」导致的二次启动崩溃。
"""

from __future__ import annotations

from typing import Any

from starlette.routing import BaseRoute

from . import db
from .logging_utils import get_logger
from .mcp_server import MCP_AVAILABLE, _apply_shared_schemas, mcp

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# 集成入口：挂载到 FastAPI 应用
# ---------------------------------------------------------------------------


def build_asgi() -> tuple[Any, Any] | None:
    """构建 MCP 的 ASGI 子应用，返回 (streamable_app, sse_app)。

    必须由调用方在创建父 app **之前**调用，并把 streamable_app.lifespan
    接进父 app —— Streamable HTTP 的 session manager 在 lifespan 里启动
    task group，不接会报 "Task group is not initialized"（实测）。
    sse_app 可能为 None（旧版 fastmcp 无 create_sse_app）。
    """
    if not MCP_AVAILABLE:
        return None

    _apply_shared_schemas()

    # 传输层：**Streamable HTTP 为默认**，SSE 保留一个版本期（M2.2）。
    #
    # 为什么换默认：MCP 规范 2025-03 起用 Streamable HTTP 取代 HTTP+SSE。
    # SSE 需要两条长连接（/sse 收 + /messages/ 发），在反向代理与移动网络下
    # 容易断流；Streamable HTTP 单端点、按需升流，是当前官方推荐形态。
    #
    # 兼容策略：已接入的客户端仍指向 /mcp/sse + /mcp/messages/，因此两条路径
    # 并存挂载。SSE 的移除安排在下一个大版本，届时在 CHANGELOG 明示。
    from fastmcp.server.http import create_streamable_http_app

    # 内部路由保留 /mcp：下面用「精确路径挂载」把 /mcp 与 /mcp/ 都直接交给它，
    # 不经过 Starlette 的斜杠重定向（307 会让不跟随重定向的 MCP 客户端失败）。
    streamable = create_streamable_http_app(server=mcp, streamable_http_path="/mcp")
    sse = None
    try:
        from fastmcp.server.http import create_sse_app

        sse = create_sse_app(server=mcp, message_path="/messages/", sse_path="/sse")
    except ImportError:  # pragma: no cover — 仅旧版 fastmcp 走到
        log.warning("mcp.sse_unavailable: 当前 fastmcp 版本不提供 create_sse_app")
    return streamable, sse


class _DynamicMcp:
    """动态转发到"当前" MCP 子应用。

    为什么需要它：session manager 每个实例只能 run 一次（run() 不可重入），
    而父 app 的 lifespan 可能被多次进入（测试用 TestClient、热重载、嵌入式
    多实例）。若挂载时把子应用写死，lifespan 里就得复用同一实例 → 第二次
    启动直接抛 "can only be called once per instance"；若 lifespan 里重建，
    挂载的路由又指向旧实例 → session manager 从未启动，端点 500。

    解法：挂一个转发器，请求到达时读取 holder 里的当前实例。lifespan 负责
    写入新实例，两者永远指同一个对象。
    """

    def __init__(self, holder: dict[str, Any]) -> None:
        self._holder = holder

    async def __call__(self, scope, receive, send) -> None:
        built = self._holder.get("built")
        target = built[0] if built else None
        if target is None:  # pragma: no cover — lifespan 未跑或构建失败
            from starlette.responses import JSONResponse

            await JSONResponse({"error": "MCP 未就绪"}, status_code=503)(scope, receive, send)
            return
        await target(scope, receive, send)


class _DynamicSse(_DynamicMcp):
    """同上，转发到 SSE 子应用（holder 里的第 2 项）。"""

    async def __call__(self, scope, receive, send) -> None:
        built = self._holder.get("built")
        target = built[1] if built else None
        if target is None:  # pragma: no cover — 旧版 fastmcp 无 SSE
            from starlette.responses import JSONResponse

            await JSONResponse({"error": "MCP SSE 不可用"}, status_code=503)(scope, receive, send)
            return
        await target(scope, receive, send)


class _ExactPathRoute(BaseRoute):
    """只匹配精确路径（含可选尾斜杠）并把原始 scope 交给子应用。

    为什么不用 Mount：Starlette 对 `Mount("/mcp")` 的精确路径 `/mcp` 会先做
    307 重定向到 `/mcp/`，而 MCP 客户端（含官方 SDK）默认不跟随重定向，
    表现为"连不上"。这里直接匹配、不改写路径，`/mcp` 与 `/mcp/` 都直达子应用。
    不匹配的路径返回 Match.NONE，后续静态托管等路由照常生效。
    """

    def __init__(self, path: str, app: Any) -> None:
        self.path = path
        self.app = app

    def matches(self, scope) -> tuple[Any, dict[str, Any]]:
        from starlette.routing import Match

        if scope["type"] != "http":
            return Match.NONE, {}
        raw = scope.get("path", "")
        if raw in (self.path, self.path + "/"):
            return Match.FULL, scope
        return Match.NONE, {}

    async def handle(self, scope, receive, send) -> None:
        await self.app(scope, receive, send)

    async def __call__(self, scope, receive, send) -> None:
        await self.handle(scope, receive, send)


def mount_to_app(app: Any, holder: dict[str, Any] | None = None) -> None:
    """把 MCP 子应用挂到 FastAPI app（/mcp 为 Streamable HTTP，/mcp-sse 为 SSE）。

    holder 是可变容器 {"built": (streamable, sse) | None}，由父 app 的 lifespan
    负责写入。不传则内部构建一次并写死（无 lifespan 接入，Streamable HTTP
    不可用，仅测试/特殊场景使用）。
    """
    if not MCP_AVAILABLE:
        log.info("mcp.skipped: fastmcp unavailable, not mounting")
        return

    if holder is None:
        built = build_asgi()
        if built is None:
            return
        holder = {"built": built}
    streamable = _DynamicMcp(holder)

    from starlette.requests import Request
    from starlette.responses import JSONResponse

    # /mcp 走 app.mount 会绕过主 app 的 @app.middleware("http") 中间件链，
    # 所以这里复用主 app 的同一套闸（口令 + 多用户 JWT fail-closed + Host/Origin
    # 白名单），否则就会出现"主站有防护、MCP 侧裸奔"的第二条信任边界。
    from .middleware import auth_gate, host_guard_check

    class _McpAuthGuard:
        """纯 ASGI 的 MCP 门卫：过闸后把原始 scope 直接转发下去。

        为什么不用 BaseHTTPMiddleware：它会把响应重新组装成事件流再吐出去，
        而 SSE（`/mcp-sse/sse`）是长连接流式响应，经它一转就会在服务端抛
        `AssertionError: Unexpected message: http.response.start`，客户端只看到
        连接挂住（实测超时，收不到任何 event）。纯 ASGI 只做判定、不碰 body，
        SSE 与 Streamable HTTP 都能原样流出去。
        """

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            request = Request(scope)
            gate = await auth_gate(request)
            if isinstance(gate, JSONResponse):
                await gate(scope, receive, send)
                return
            denied = host_guard_check(request)
            if denied is not None:
                await JSONResponse({"error": denied}, status_code=403)(scope, receive, send)
                return
            # 租户接线：auth_gate 返回的 tenant_id 必须写进 ContextVar，
            # 否则 MCP 工具里的 db.* 全部落到默认租户 0——多用户实例里
            # 用户 B 拿自己的 JWT 调 MCP，读写的是用户 A 的账本（跨租户读写）。
            from .db.tenant import reset_current_user_id, set_current_user_id

            token = set_current_user_id(gate)
            try:
                await self.app(scope, receive, send)
            finally:
                reset_current_user_id(token)

    # 路径布局：
    #   /mcp                 Streamable HTTP（默认，MCP 规范推荐；无斜杠即用）
    #   /mcp-sse/sse         SSE 端点（旧客户端兼容，保留一个版本期）
    #   /mcp-sse/messages/   SSE 上行端点（仅 POST）
    #
    # 绝不挂 Mount("/")：根挂载会拦截所有未匹配请求（含前端静态资源），
    # 导致单端口部署时首页 404。streamable 子应用的内部路由就是 "/mcp"，
    # 因此用精确路径路由直接转发原始 scope（/mcp 与 /mcp/ 都命中，无 307）。
    sse_dynamic = _DynamicSse(holder)
    app.mount("/mcp-sse", _McpAuthGuard(sse_dynamic))
    app.router.routes.append(_ExactPathRoute("/mcp", _McpAuthGuard(streamable)))
    log.info("mcp.transport: streamable-http at /mcp, sse at /mcp-sse/sse")


async def startup() -> None:
    """MCP Server 启动时检查 DB 可用性。"""
    try:
        await db.fetch_all("SELECT 1")
    except Exception:
        pass  # DB 未就绪时 MCP 工具会在调用时返回错误
