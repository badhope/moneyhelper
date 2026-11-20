"""连接中心深化路由（v4.5）：腾讯行情 / 市场温度 / 个股档案 / 预交易风控 /
券商持仓对账 / 发票归档 / 条件单。

与 routes/connect.py 分文件：连接中心基础能力（目录/连接/配对/同步/意图）已 377 行，
再往里堆会让单文件超过 400 行，违反仓库「按职责分文件」的约定。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])




# ---------------------------------------------------------------------------
# 腾讯行情 / 市场温度 / 个股档案 / 分时 / K 线备源
# ---------------------------------------------------------------------------


# 五个业务域已拆成独立路由；挂载顺序与拆分前一致（行情 → 持仓 → 发票 → 条件单 → 账单）
from .connect_conditionals import router as conditionals_router  # noqa: E402
from .connect_holdings import router as holdings_router  # noqa: E402
from .connect_invoices import router as invoices_router  # noqa: E402
from .connect_quotes import router as quotes_router  # noqa: E402
from .connect_statements import router as statements_router  # noqa: E402

router.include_router(quotes_router)
router.include_router(holdings_router)
router.include_router(invoices_router)
router.include_router(conditionals_router)
router.include_router(statements_router)
