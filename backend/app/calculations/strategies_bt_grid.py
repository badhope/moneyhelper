"""网格策略：按等距网格分档调仓，信号与执行分离。"""

from __future__ import annotations

from typing import Any

from .strategies_bt_core import (
    _benchmark,
    _benchmark_curve,
    _metrics,
)


def backtest_grid(
    closes: list[float],
    *,
    dates: list[str] | None = None,
    grid_count: int = 10,
    grid_pct: float = 0.03,
    cost: float = 0.0003,
    initial_capital: float = 100_000.0,
) -> dict[str, Any] | None:
    """网格交易：在 [下沿, 上沿] 区间内等分网格，跌一格买、涨一格卖。

    参数依据：
      - grid_pct=3%：A 股宽基 ETF 日波动约 1.2~1.8%，3% 约两个交易日触发一次，
        既不会被噪声打穿，也保证足够交易频次。
      - grid_count=10：把资金分成 10 份，单格用 10% 资金，避免一次打满。
      - 区间取最近 120 日的 10%~90% 分位，避免用全样本（那是前视）。

    失效场景：单边下跌会逐格买满后套牢；单边上涨会过早卖光。这是网格的
    固有性质，不是 bug——所以结果里明确给出「区间位置」提示风险。
    """
    n = len(closes)
    if n < 60 or grid_count < 2 or grid_pct <= 0:
        return None
    lookback = min(120, n)
    window = sorted(closes[:lookback])
    low = window[int(lookback * 0.10)]
    high = window[int(lookback * 0.90)]
    if high <= low:
        return None

    per_grid = initial_capital / grid_count
    cash = initial_capital
    shares = 0.0
    curve: list[float] = [initial_capital]
    trades: list[dict[str, Any]] = []
    last_grid = 0
    step = high * grid_pct
    if step <= 0:
        return None

    for i in range(1, n):
        px = closes[i]
        if px <= 0:
            curve.append(round(cash + shares * closes[i - 1], 2))
            continue
        # 当前价格落在第几格
        level = int((px - low) / step)
        if level != last_grid:
            if level < last_grid and cash >= per_grid * 0.99:
                # 下穿：买入一格
                qty = per_grid / (px * (1 + cost))
                cash -= qty * px * (1 + cost)
                shares += qty
                trades.append({"date": dates[i] if dates else i, "side": "buy",
                               "price": round(px, 4), "shares": round(qty, 4), "reason": "grid_down"})
            elif level > last_grid and shares > 0:
                # 上穿：卖出一格
                qty = min(shares, per_grid / px)
                cash += qty * px * (1 - cost)
                shares -= qty
                trades.append({"date": dates[i] if dates else i, "side": "sell",
                               "price": round(px, 4), "shares": round(qty, 4), "reason": "grid_up"})
            last_grid = level
        curve.append(round(cash + shares * px, 2))

    m = _metrics(curve, initial_capital)
    bm = _benchmark(closes, initial_capital)
    # 区间位置：期末价在 [low, high] 的分位（0=下沿, 1=上沿）
    pos = (closes[-1] - low) / (high - low) if high > low else 0.5
    return {
        "strategy": "grid",
        "params": {"grid_count": grid_count, "grid_pct": grid_pct, "cost": cost,
                   "low": round(low, 2), "high": round(high, 2)},
        **m,
        "trade_count": len(trades),
        "benchmark_return_pct": bm["return_pct"],
        "benchmark_value": bm["value"],
        "grid_position": round(max(0.0, min(1.0, pos)), 3),
        "risk_note": (
            "单边行情下网格会失效：下跌会逐格买满，上涨会过早卖光。"
            "请结合区间位置判断当前是否仍在震荡。"
        ),
        "curve": {
            "dates": dates or list(range(n)),
            "strategy": curve,
            "benchmark": _benchmark_curve(closes, initial_capital),
        },
    }
