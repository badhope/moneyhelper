"""策略指标：滚动波动、ATR、唐奇安通道。

从 strategies.py 拆出；纯函数，无状态、无前视偏差。
"""

from __future__ import annotations

import math

TRADING_DAYS = 252

def _stdev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(max(0.0, var))

def rolling_vol(closes: list[float], window: int = 20) -> list[float | None]:
    """滚动已实现年化波动率（简单收益率标准差 × √252）。"""
    out: list[float | None] = [None] * len(closes)
    rets: list[float | None] = [None]
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        rets.append((closes[i] / prev - 1.0) if prev > 0 else None)
    for i in range(len(closes)):
        if i < window:
            continue
        window_rets = [r for r in rets[i - window + 1 : i + 1] if r is not None]
        if len(window_rets) < window // 2:
            continue
        out[i] = _stdev(window_rets) * math.sqrt(TRADING_DAYS)
    return out

def atr(highs: list[float], lows: list[float], closes: list[float], window: int = 14) -> list[float | None]:
    """平均真实波幅（ATR）。数据长度不足以 high/low 时返回全 None。"""
    n = min(len(highs), len(lows), len(closes))
    out: list[float | None] = [None] * len(closes)
    if n < window + 1:
        return out
    trs: list[float] = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    # Wilder 平滑
    prev = sum(trs[:window]) / window
    out[window] = prev
    for i in range(window + 1, n):
        prev = (prev * (window - 1) + trs[i - 1]) / window
        out[i] = prev
    return out

def donchian(
    highs: list[float], lows: list[float], window: int = 20
) -> tuple[list[float | None], list[float | None]]:
    """唐奇安通道：过去 window 日的最高/最低（不含当日，避免自我触发）。"""
    n = min(len(highs), len(lows))
    upper: list[float | None] = [None] * len(highs)
    lower: list[float | None] = [None] * len(highs)
    for i in range(window, n):
        upper[i] = max(highs[i - window : i])
        lower[i] = min(lows[i - window : i])
    return upper, lower
