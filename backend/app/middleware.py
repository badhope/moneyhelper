"""全局中间件栈：异常兜底 / 限流 / 鉴权 / Host 防护 / 安全响应头 / 观测计数 / 审计。

从 main.py 拆出（M1.4）。注册顺序即原 main.py 定义顺序，执行语义不变：
请求流向 audit_logger → metrics_counter → security_headers → host_guard →
api_auth → CORS → rate_limiter → 路由（后注册者为外层）。
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import time
from collections.abc import Coroutine
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from . import db
from .auth import verify_api_token
from .compat_env import getenv
from .logging_utils import get_logger as _get_logger

log = _get_logger(__name__)

# 跳过鉴权的内部端点：只保留"不含用户数据"的存活探针与登录入口。
# /api/health-check 会输出财务体检结论，属敏感数据，不能免鉴权。
_SKIP_AUTH_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/user-count",
}

# ---------------------------------------------------------------------------
# 限流：in-memory 滑动窗口，按 IP 计数；单进程部署；多进程需换 Redis。
# ---------------------------------------------------------------------------
_RATE_LIMIT_ENABLED = not getenv("MONEYHELPER_DISABLE_RATE_LIMIT")
_RATE_LIMIT_MAX = 200  # 单 IP 每分钟上限
_RATE_LIMIT_WINDOW = 60.0  # 窗口大小（秒）
_rate_buckets: dict[str, list[float]] = {}
_RATE_BUCKETS_CAP = 4096


def _normalize_ip(ip: str) -> str:
    """把本地回环的各种写法归一到同一个 key，避免 IPv4/IPv6 各拿一份限流配额。"""
    raw = (ip or "").strip().lower()
    if raw in ("::1", "0:0:0:0:0:0:0:1", "localhost"):
        return "127.0.0.1"
    # IPv4-mapped IPv6：::ffff:127.0.0.1
    if raw.startswith("::ffff:"):
        return raw[7:]
    return raw


def _rate_limit_check(client_ip: str) -> tuple[bool, int]:
    """返回 (是否放行, 0=放行 or 秒数=retry_after)。"""
    if not _RATE_LIMIT_ENABLED:
        return True, 0
    now = time.time()
    if len(_rate_buckets) > _RATE_BUCKETS_CAP:
        cutoff = now - _RATE_LIMIT_WINDOW
        for k in [k for k, v in _rate_buckets.items() if not v or v[-1] <= cutoff]:
            _rate_buckets.pop(k, None)
    bucket = _rate_buckets.setdefault(client_ip, [])
    cutoff = now - _RATE_LIMIT_WINDOW
    _rate_buckets[client_ip] = [t for t in bucket if t > cutoff]
    bucket = _rate_buckets[client_ip]
    # 先计数再判定：新 IP 首个请求也计入窗口（修复旧实现"首请求不计数"）
    bucket.append(now)
    if len(bucket) >= _RATE_LIMIT_MAX:
        retry_after = int(bucket[0] + _RATE_LIMIT_WINDOW - now) + 1
        return False, max(1, retry_after)
    return True, 0


async def rate_limiter_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in _SKIP_AUTH_PATHS:
        client = request.client
        ip = client.host if client else "127.0.0.1"
        # 归一化：同一客户端可能以 127.0.0.1 / ::1 / ::ffff:127.0.0.1 多种形态出现
        # （双栈监听），按原始字符串建桶会让同一 IP 拿到多份配额。
        ok, retry_after = _rate_limit_check(_normalize_ip(ip))
        if not ok:
            return JSONResponse(
                {"error": "请求过于频繁，请稍后再试"},
                status_code=429,
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(_RATE_LIMIT_MAX),
                },
            )
    return await call_next(request)


# fire-and-forget 后台任务持有集：防止 create_task 返回的 Task 在完成前被 GC
# 取消（asyncio 只保留弱引用，无人持引用时任务可能静默失效）。
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

    # 审计归属：把本请求解析到的操作者写进 ContextVar，后续 record_provenance
    # 不传 username 时自动归属该用户（此前各路由硬编码 "system"，审计链全失真）。
    actor = _resolve_actor(request, key)
    if actor:
        from .provenance import set_request_actor

        set_request_actor(actor)

    # 租户隔离：JWT 用户决定这一请求读写哪份数据。
    # 无 JWT 时保持默认租户 0（本机单用户模式）；共享口令模式下同样归 0——
    # 一个实例仍然是一个账本。
    from .db.tenant import reset_current_user_id, set_current_user_id

    token = set_current_user_id(tenant_id)
    try:
        return await call_next(request)
    finally:
        reset_current_user_id(token)


async def _has_registered_users() -> bool:
    """当前实例是否已启用账号体系（有任意注册用户）。失败时按"有用户"处理（fail-closed）。"""
    try:
        from . import db

        return await db.user_count() > 0
    except Exception:  # noqa: BLE001 — 查询失败时宁可要求登录
        return True


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
    if not api_token:
        return "local"
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


# ---------------------------------------------------------------------------
# 无口令模式的 Host/Origin 防护（DNS rebinding / 跨站读取）：
# 未设 API_TOKEN 时仅放行本机与 ALLOWED_HOSTS 白名单；/api/health 恒免检；
# 设了口令则以口令为准（反代部署不拦截）。注册在 api_auth 之后 = 更外层。
# ---------------------------------------------------------------------------

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}


def _hostname(value: str) -> str:
    """剥离端口的主机名（支持 host:port 与 [v6]:port）。"""
    v = (value or "").strip().lower()
    if v.startswith("["):
        return v.split("]", 1)[0] + "]"
    return v.rsplit(":", 1)[0] if v.count(":") == 1 else v


def _allowed_hosts() -> set[str]:
    extra = {
        h.strip().lower()
        for h in os.getenv("ALLOWED_HOSTS", "").split(",")
        if h.strip()
    }
    return _LOCAL_HOSTS | extra


def _host_allowed(host: str, allowed: set[str]) -> bool:
    """ALLOWED_HOSTS 含 * 时放行所有主机名（预览域名等不可枚举的场景）。"""
    if "*" in allowed:
        return True
    return host in allowed


def _client_is_local(request: Request) -> bool:
    """判断直连来源是否本机/内网。

    Host 头可被任意客户端伪造，因此无口令模式不能只靠 Host 判断：
    公网来源即使伪造 `Host: localhost` 也必须拒绝。
    """
    client = request.client
    if client is None or not client.host:
        # TestClient / ASGI 内嵌调用没有 client 信息，按本机处理（与历史行为一致）
        return True
    ip = client.host
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        # client.host 不是 IP 说明不是 TCP 直连（unix socket / 进程内 ASGI / TestClient），
        # 这些场景本身就在本机，放行并交给 Host 头校验兜底。
        return True
    if addr.is_loopback:
        return True
    return addr.is_private or addr.is_link_local


def token_ok(request: Request) -> bool:
    """口令判定：未设 API_TOKEN 时恒为 True（无口令模式），否则要求匹配。

    供主中间件与 MCP 子应用共用，避免两处各自实现导致口径漂移。
    """
    key = os.getenv("API_TOKEN", "").strip()
    if not key:
        return True
    return verify_api_token(request) is not None


def host_guard_check(request: Request) -> str | None:
    """无口令模式的来源校验，返回错误文案；通过返回 None。

    三条同时满足才放行：
    1. 直连来源是本机/内网（防公网直连伪造 Host）
    2. Host 在白名单内
    3. Origin（若有）在白名单内
    """
    if os.getenv("API_TOKEN", "").strip():
        return None  # 有口令时以口令为准（反代部署不按 Host 拦截）
    if not _client_is_local(request):
        return "不允许的来源：未设置 API_TOKEN 时仅允许本机/内网访问，请设置口令后再对外提供服务"
    allowed = _allowed_hosts()
    host = _hostname(request.headers.get("host", ""))
    if host and not _host_allowed(host, allowed):
        return (
            "不允许的 Host：未设置 API_TOKEN 时仅限本机/内网访问，"
            "如需按主机名部署请设置 ALLOWED_HOSTS 或 API_TOKEN"
        )
    origin = request.headers.get("origin", "")
    if origin:
        oh = (urlsplit(origin).hostname or "").lower()
        if oh and not _host_allowed(oh, allowed) and oh != host:
            return "不允许的 Origin"
    return None


async def host_guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in _SKIP_AUTH_PATHS:
        denied = host_guard_check(request)
        if denied is not None:
            return JSONResponse({"error": denied}, status_code=403)
    return await call_next(request)


# ---------------------------------------------------------------------------
# 安全响应头：所有响应统一加固（防 MIME 嗅探 / 点击劫持 / 敏感来源泄露）
# 用 setdefault 避免覆盖下游主动设置；不设 CSP，避免破坏 Vite 内联 module 与 echarts。
# ---------------------------------------------------------------------------


async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # 本机语音输入用麦克风（voice_input），故保留 microphone；其余能力收紧
    resp.headers.setdefault(
        "Permissions-Policy",
        "camera=(), geolocation=(), payment=(), usb=(), microphone=(self)",
    )
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    return resp


# ---------------------------------------------------------------------------
# 轻量观测：请求计数 / 错误 / 运行时长（Prometheus 文本格式，可直接被采集器抓取）
# ---------------------------------------------------------------------------
_START_TS = time.monotonic()
METRICS: dict[str, int] = {"requests": 0, "errors": 0, "auth_401": 0, "messages": 0}


async def metrics_counter(request: Request, call_next):
    METRICS["requests"] += 1
    resp = await call_next(request)
    if resp.status_code >= 500:
        METRICS["errors"] += 1
    elif resp.status_code == 401:
        METRICS["auth_401"] += 1
    return resp


def metrics_body() -> Response:
    """渲染 Prometheus 文本格式（/api/metrics 用）。"""
    lines = [
        "# TYPE moneyhelper_requests_total counter",
        f"moneyhelper_requests_total {METRICS['requests']}",
        "# TYPE moneyhelper_errors_total counter",
        f"moneyhelper_errors_total {METRICS['errors']}",
        "# TYPE moneyhelper_auth_401_total counter",
        f"moneyhelper_auth_401_total {METRICS['auth_401']}",
        "# TYPE moneyhelper_messages_total counter",
        f"moneyhelper_messages_total {METRICS['messages']}",
        "# TYPE moneyhelper_uptime_seconds gauge",
        f"moneyhelper_uptime_seconds {time.monotonic() - _START_TS:.1f}",
    ]
    # 关键路径耗时（LLM / 工具 / 图节点）：只输出有采样的 label，避免刷空序列
    from .observability import snapshot as _snapshot

    stats = _snapshot()
    if stats:
        lines.append("# TYPE moneyhelper_op_average_ms gauge")
        lines.append("# TYPE moneyhelper_op_max_ms gauge")
        lines.append("# TYPE moneyhelper_op_total counter")
        for label, row in sorted(stats.items()):
            safe = label.replace('"', "")
            lines.append(f'moneyhelper_op_average_ms{{op="{safe}"}} {row["avg_ms"]}')
            lines.append(f'moneyhelper_op_max_ms{{op="{safe}"}} {row["max_ms"]}')
            lines.append(f'moneyhelper_op_total{{op="{safe}"}} {row["count"]}')
    lines.append("")
    return Response(
        content="\n".join(lines),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# 注：messages 计数沿用原 main.py 行为——初始化并在 /api/metrics 导出，暂无递增点。


# 审计日志（P2 金融级治理）：记录写操作与敏感读，便于追溯。
# - 写类（非 GET /api/*）：统一审计，排除健康/指标/审计自身等低敏或自引用路径；
# - 敏感读（导出、设置、备份相关）：单独标记 READ_SENSITIVE；
# - 触发鉴权（401/403）：标记 AUTH。
AUDIT_SKIP_PREFIXES = (
    "/api/health",
    "/api/metrics",
    "/api/audit",
    "/api/bootstrap",
    "/api/dashboard",
    "/api/quotes",
    "/api/market",
    "/api/kline",
    "/api/reports",
)
AUDIT_SENSITIVE_READ = ("/api/export", "/api/settings", "/api/reflections")


async def audit_logger(request: Request, call_next):
    started = time.monotonic()
    path = request.url.path
    method = request.method
    resp = await call_next(request)
    if not path.startswith("/api/"):
        return resp
    duration_ms = int((time.monotonic() - started) * 1000)
    try:
        actor = (request.client.host if request.client else "") or ""
        action = None
        # 敏感读：导出/设置/口令
        if method == "GET" and path in AUDIT_SENSITIVE_READ:
            action = "READ_SENSITIVE"
        elif method != "GET" and not path.startswith(AUDIT_SKIP_PREFIXES):
            action = "WRITE"
        elif resp.status_code == 401:
            action = "AUTH"
        if action:
            await db.add_audit_log(
                action=action,
                method=method,
                path=path,
                status=resp.status_code,
                actor=actor,
                detail=f"{method} {path}",
                duration_ms=duration_ms,
            )
    except Exception:  # noqa: BLE001 — 审计失败不影响请求
        pass
    return resp


# 兼容别名：旧 main.py 内部曾以 _metrics_counter / _audit_logger 引用
_metrics_counter = metrics_counter
_audit_logger = audit_logger


def setup(app: FastAPI) -> None:
    """按原 main.py 定义顺序把全部中间件注册到 app（语义不变）。"""
    app.middleware("http")(rate_limiter_middleware)

    _dev_origins = {"http://127.0.0.1:5198", "http://localhost:5198"}
    if os.getenv("CORS_ALLOW_ALL") == "1":  # 仅调试用
        _dev_origins = None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_dev_origins) if _dev_origins is not None else ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.middleware("http")(api_auth)
    app.middleware("http")(host_guard)
    app.middleware("http")(security_headers)
    app.middleware("http")(metrics_counter)
    app.middleware("http")(audit_logger)
