"""预交易风控门面：常量与涨跌停 / 九项检查 / 委托换算。

检查项全部确定性计算，结果结构
`{"ok", "blocking", "warnings", "checks": [{id, ok, level, detail}]}`，
level: block=拒绝、warn=提示、info=通过记录。
"""

from __future__ import annotations

__all__ = [
    "A_SHARE_LOT",
    "DUPLICATE_WINDOW_SECONDS",
    "daily_order_amount",
    "limit_prices",
    "pre_trade_check",
    "price_limit",
    "rebalance_orders",
]

from .pretrade_check import _check, _pack, pre_trade_check  # noqa: F401,E402
from .pretrade_limits import (  # noqa: F401,E402
    A_SHARE_LOT,
    DEFAULT_CONCENTRATION_PCT,
    DEFAULT_DAILY_LIMIT,
    DEFAULT_DEVIATION_PCT,
    DUPLICATE_WINDOW_SECONDS,
    limit_prices,
    price_limit,
)
from .pretrade_orders import daily_order_amount, rebalance_orders  # noqa: F401,E402
