"""HTTP 壳层：FastAPI 应用、路由、中间件。

这一层只做三件事：**收请求、调 core、出响应**。业务计算一律下沉到 core，
否则同一段逻辑在 CLI / MCP 里就要重写一遍（这是本项目要避免的重复）。

当前实现映射：

    app        ← app.main        FastAPI 实例与路由装配（含 lifespan）
    middleware ← app.middleware  限流 / 鉴权 / Host 防护 / 安全头 / 观测 / 审计
    routes     ← app.routes      各域端点（auth/status/memory/export/qa/ledger/...）
    auth       ← app.auth        JWT 与访问口令

用法（与原入口等价）：

    from moneyhelper.server import app
    uvicorn moneyhelper.server:app --port 8788

旧的 `uvicorn app.main:app` 继续可用，二者是同一个对象。
"""

from __future__ import annotations

from app import (  # noqa: F401
    auth,
    middleware,
    routes,  # noqa: F401
)
from app.main import app  # noqa: F401

__all__ = ["app", "auth", "middleware", "routes"]
