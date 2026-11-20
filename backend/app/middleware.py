"""全局中间件栈：异常兜底 / 限流 / 鉴权 / Host 防护 / 安全响应头 / 观测计数 / 审计。

实现按域拆到 mw_auth / mw_host / mw_observ（共享常量在 mw_common）；
限流组保留在本模块——测试通过 monkeypatch 打本模块全局配额桶。

注册顺序即原 main.py 定义顺序，执行语义不变：
请求流向 audit_logger → metrics_counter → security_headers → host_guard →
api_auth → CORS → rate_limiter → 路由（后注册者为外层）。
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .compat_env import getenv
from .logging_utils import get_logger as _get_logger
from .mw_auth import (  # noqa: F401,E402
    _has_registered_users,
    _resolve_actor,
    _resolve_tenant,
    _user_is_active,
    api_auth,
    auth_gate,
    spawn_background,
)
from .mw_common import _SKIP_AUTH_PATHS  # noqa: F401
from .mw_host import (  # noqa: F401,E402
    _client_is_local,
    host_guard,
    host_guard_check,
    token_ok,
)
from .mw_observ import (  # noqa: F401,E402
    METRICS,
    _audit_logger,
    _metrics_counter,
    audit_logger,
    metrics_body,
    metrics_counter,
    security_headers,
)

log = _get_logger(__name__)

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
    # 用 > 而不是 >=：文档写的是"每分钟 200 次"，第 200 次应当放行。
    # 旧写法的实际配额是 199，与 X-RateLimit-Limit 自相矛盾（已有回归测试）。
    if len(bucket) > _RATE_LIMIT_MAX:
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


_INGEST_PATH = "/api/connect/ingest"


async def ingest_cors(request: Request, call_next):
    if request.url.path != _INGEST_PATH:
        return await call_next(request)
    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "600",
            },
        )
    resp = await call_next(request)
    resp.headers.setdefault("Access-Control-Allow-Origin", "*")
    return resp


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
    app.middleware("http")(ingest_cors)
    app.middleware("http")(security_headers)
    app.middleware("http")(metrics_counter)
    app.middleware("http")(audit_logger)
