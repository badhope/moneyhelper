"""观测与审计：安全响应头、请求计数、Prometheus 指标、写操作/敏感读审计日志。"""

from __future__ import annotations

import os
import time

from fastapi import Request
from fastapi.responses import Response

from . import db
from .mw_auth import _resolve_actor


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


AUDIT_SKIP_PREFIXES = (
    "/api/health",
    "/api/metrics",
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
        # 审计归属使用稳定身份（共享口令用户名 / JWT 用户 id / local），
        # 而不是客户端 IP——IP 会变、会共享，无法回答"是谁做的"。
        actor = _resolve_actor(request, os.getenv("API_TOKEN", "").strip()) or (
            (request.client.host if request.client else "") or ""
        )
        action = None
        # 敏感读：导出/设置/口令
        if method == "GET" and path in AUDIT_SENSITIVE_READ:
            action = "READ_SENSITIVE"
        elif method != "GET" and not path.startswith(AUDIT_SKIP_PREFIXES):
            action = "WRITE"
        elif resp.status_code in (401, 403):
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
                user_id=int(getattr(request.state, "tenant_id", 0) or 0),
            )
    except Exception:  # noqa: BLE001 — 审计失败不影响请求
        pass
    return resp


_metrics_counter = metrics_counter


_audit_logger = audit_logger
