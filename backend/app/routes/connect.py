"""连接中心路由门面：目录 / 连接 / 配对 / 收件箱 / 行情 / 意图六个子路由。

鉴权：与主 API 同一套中间件（登录 JWT 或共享口令）。
所有端点都允许降级：外部数据源失败返回 items=[] + note，不返回 5xx。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..connect.catalog import get_connector

router = APIRouter(dependencies=[Depends(get_current_user)])

__all__ = ["get_connector", "router"]

from .connect_catalog import _kind_labels  # noqa: F401,E402
from .connect_catalog import router as _catalog_router  # noqa: E402
from .connect_connections import router as _connections_router  # noqa: E402
from .connect_inbox import router as _inbox_router  # noqa: E402
from .connect_intents import router as _intents_router  # noqa: E402
from .connect_market import router as _market_router  # noqa: E402
from .connect_pairing import _extract_rows, _ingest_rows  # noqa: F401,E402
from .connect_pairing import router as _pairing_router  # noqa: E402

for _r in (
    _catalog_router,
    _connections_router,
    _pairing_router,
    _inbox_router,
    _market_router,
    _intents_router,
):
    router.include_router(_r)
