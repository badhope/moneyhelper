"""涨跌停与交易常量：主板/创业板/科创/北交所/ST 的价格区间换算。"""

from __future__ import annotations

A_SHARE_LOT = 100
DEFAULT_DAILY_LIMIT = 200_000.0
DEFAULT_DEVIATION_PCT = 3.0
DEFAULT_CONCENTRATION_PCT = 30.0
DUPLICATE_WINDOW_SECONDS = 60


# 涨跌停幅度：按代码前缀判定板块
_LIMIT_RULES: tuple[tuple[str, float], ...] = (
    ("688", 0.20),  # 科创板
    ("689", 0.20),
    ("300", 0.20),  # 创业板
    ("301", 0.20),
    ("8", 0.30),    # 北交所
    ("4", 0.30),
    ("9", 0.30),
)


def price_limit(symbol: str, prev_close: float, is_st: bool = False) -> float:
    """返回该标的的涨跌停幅度（0.05/0.10/0.20/0.30）。"""
    if prev_close <= 0:
        return 0.10
    if is_st:
        return 0.05
    for prefix, pct in _LIMIT_RULES:
        if symbol.startswith(prefix):
            return pct
    return 0.10


def limit_prices(symbol: str, prev_close: float, is_st: bool = False) -> dict[str, float]:
    """计算涨停价/跌停价（A 股四舍五入到分）。"""
    pct = price_limit(symbol, prev_close, is_st)
    up = round(prev_close * (1 + pct) + 1e-9, 2)
    down = round(prev_close * (1 - pct) + 1e-9, 2)
    return {"up": up, "down": down, "pct": pct}
