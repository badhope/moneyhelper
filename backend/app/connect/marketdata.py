"""连接中心公开行情门面：基金 / 排行 / 指数 / 源状态。

数据源优先东财，部分网络下东财被重置时退新浪；失败一律返回 items=[] + note。
子模块统一经 `_facade.httpx` 建客户端，测试替换 `marketdata.httpx` 仍然生效。
"""

from __future__ import annotations

import httpx  # noqa: F401 — 测试按模块名替换客户端

from ..timeutil import now_iso as _now  # noqa: F401 — 时间戳策略按模块名守

__all__ = ["fund_history", "fund_nav", "index_snapshot", "market_movers", "source_status"]

from .marketdata_common import _UA, _num  # noqa: F401,E402
from .marketdata_fund import (  # noqa: F401,E402
    _fund_hist_cache,
    _fund_nav_cache,
    fund_history,
    fund_nav,
)
from .marketdata_indices import index_snapshot  # noqa: F401,E402
from .marketdata_movers import (  # noqa: F401,E402
    _movers_cache,
    _movers_eastmoney,
    _movers_sina,
    market_movers,
)
from .marketdata_status import source_status  # noqa: F401,E402
