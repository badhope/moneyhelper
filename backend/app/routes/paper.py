"""团队模拟盘路由门面（v4.2）：账户域与桥接域分别拆在 `paper_accounts.py` /
`paper_bridge.py`，此处只装配两条子路由，对外仍是单一 `router`。

设计要点：事件溯源重放持仓与现金；估值用最近成交价；校验都在引擎层。
"""

from __future__ import annotations

from fastapi import APIRouter

from .paper_accounts import router as accounts_router
from .paper_bridge import router as bridge_router

router = APIRouter()
router.include_router(accounts_router)
router.include_router(bridge_router)
