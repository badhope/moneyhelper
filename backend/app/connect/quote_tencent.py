"""腾讯行情门面：基座 / 档案 / 分时 / K 线 / 市场温度。

为什么加腾讯源：
- 东财 push2 在本机运营商出口被直接重置（curl 000 / httpx RemoteProtocolError）；
- 新浪 hq.sinajs.cn 可用但只有基础字段，没有 PE/PB/市值/量比；
- 腾讯 qt.gtimg.cn 返回 50+ 字段，且同时支持指数与个股，一个请求批量拿。

口径：GBK + `~` 分隔，下标见 `_TENCENT_FIELDS`；市值单位「亿元」。
"""

from __future__ import annotations

from ..timeutil import now_iso as _now  # noqa: F401 — 时间戳策略按模块名守，必须保留

__all__ = ["kline", "market_breadth", "minute", "profile", "quote", "quotes_batch", "to_tencent"]

from .quote_tencent_breadth import market_breadth  # noqa: F401,E402
from .quote_tencent_core import (  # noqa: F401,E402 — 对外同名导出
    _TENCENT_FIELDS,
    KLINE_URL,
    MINUTE_URL,
    QT_URL,
    _num,
    _parse_quote_body,
    _quote_cache,
    _tx_kline_cache,
    quote,
    quotes_batch,
    to_tencent,
)
from .quote_tencent_kline import kline  # noqa: F401,E402
from .quote_tencent_minute import minute  # noqa: F401,E402
from .quote_tencent_profile import profile  # noqa: F401,E402
