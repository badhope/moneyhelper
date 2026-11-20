"""信号类策略：动量 / 趋势（ATR+唐奇安） / 波动目标。"""

from __future__ import annotations

from typing import Any

from .strategies_bt_core import (
    _benchmark,
    _benchmark_curve,
    _metrics,
    run_position_backtest,
)
from .strategies_indicators import atr, donchian, rolling_vol


def backtest_momentum(
    panels: dict[str, list[float]],
    *,
    dates: list[str] | None = None,
    lookback: int = 20,
    hold: int = 1,
    cost: float = 0.0003,
    initial_capital: float = 100_000.0,
) -> dict[str, Any] | None:
    """动量轮动：每期选过去 lookback 日涨幅最强的标的持有。

    参数依据：
      - lookback=20（约一个月）：太短会被噪声主导，太长会错过切换。
      - hold=1：只持有最强 1 只，降低换手；A 股 ETF 无做空，故只在正动量时持仓。
      - 绝对动量过滤：若最强标的的 lookback 收益 <= 0，则空仓（避免熊市硬撑）。

    数据要求：所有标的必须有等长价格序列（调用方负责对齐与填充）。
    """
    if not panels:
        return None
    symbols = list(panels.keys())
    n = min(len(v) for v in panels.values())
    if n < lookback + 2:
        return None
    series = {s: panels[s][:n] for s in symbols}

    cash = initial_capital
    holdings: dict[str, float] = {s: 0.0 for s in symbols}
    curve: list[float] = [initial_capital]
    trades: list[dict[str, Any]] = []

    for i in range(lookback, n):
        # 用 i-1 及之前的数据算动量（避免前视）
        scores: list[tuple[str, float]] = []
        for s in symbols:
            past = series[s][i - lookback]
            now = series[s][i - 1]
            if past > 0 and now > 0:
                scores.append((s, now / past - 1.0))
        scores.sort(key=lambda x: x[1], reverse=True)
        picks = [s for s, r in scores[:hold] if r > 0]

        equity = cash + sum(holdings[s] * series[s][i - 1] for s in symbols)
        target_weight = 1.0 / len(picks) if picks else 0.0

        # 先卖后买
        for s in symbols:
            want = equity * target_weight if s in picks else 0.0
            cur_val = holdings[s] * series[s][i - 1]
            if cur_val - want > equity * 0.005 and holdings[s] > 0:
                px = series[s][i]
                qty = min(holdings[s], (cur_val - want) / px)
                cash += qty * px * (1 - cost)
                holdings[s] -= qty
                trades.append({"date": dates[i] if dates else i, "side": "sell", "symbol": s,
                               "price": round(px, 4), "shares": round(qty, 4)})
        for s in picks:
            want = equity * target_weight
            cur_val = holdings[s] * series[s][i - 1]
            if want - cur_val > equity * 0.005:
                px = series[s][i]
                qty = min((want - cur_val) / (px * (1 + cost)), cash / (px * (1 + cost)))
                if qty > 0:
                    cash -= qty * px * (1 + cost)
                    holdings[s] += qty
                    trades.append({"date": dates[i] if dates else i, "side": "buy", "symbol": s,
                                   "price": round(px, 4), "shares": round(qty, 4)})
        curve.append(round(cash + sum(holdings[s] * series[s][i] for s in symbols), 2))

    m = _metrics(curve, initial_capital)
    # 基准：等权买入持有
    eq_bm = sum(series[s][-1] / series[s][0] for s in symbols) / len(symbols)
    return {
        "strategy": "momentum",
        "params": {"lookback": lookback, "hold": hold, "cost": cost, "symbols": symbols},
        **m,
        "trade_count": len(trades),
        "benchmark_return_pct": round((eq_bm - 1) * 100, 2),
        "benchmark_value": round(eq_bm * initial_capital, 2),
        "risk_note": "震荡市中动量会反复打脸（追高杀低），建议同时看换手率与最大回撤。",
        "curve": {
            "dates": dates or list(range(len(curve))),
            "strategy": curve,
            "benchmark": [
                round(sum(series[s][i] / series[s][0] for s in symbols) / len(symbols) * initial_capital, 2)
                for i in range(n)
            ],
        },
    }

def backtest_trend(
    closes: list[float],
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    dates: list[str] | None = None,
    entry_window: int = 20,
    exit_window: int = 10,
    atr_mult: float = 2.0,
    cost: float = 0.0003,
    initial_capital: float = 100_000.0,
) -> dict[str, Any] | None:
    """趋势跟随：突破 N 日高入场，跌破 M 日低或 ATR 止损离场。

    参数依据（海龟交易法则的日线简化版）：
      - entry_window=20 / exit_window=10：20 日突破抓中期趋势，10 日跌破止盈止损，
        非对称设置让盈利单拿得住、亏损单走得快。
      - atr_mult=2.0：ATR(14)×2 约覆盖正常波动的 2 个标准差，避免被噪声止损。
    """
    n = len(closes)
    if n < entry_window + 20:
        return None
    highs = highs if highs and len(highs) == n else closes
    lows = lows if lows and len(lows) == n else closes

    upper, _ = donchian(highs, lows, entry_window)
    _, lower_exit = donchian(highs, lows, exit_window)
    atr_series = atr(highs, lows, closes, 14)

    cash = initial_capital
    shares = 0.0
    stop = 0.0
    curve: list[float] = [initial_capital]
    trades: list[dict[str, Any]] = []

    for i in range(1, n):
        px = closes[i]
        if px <= 0:
            curve.append(round(cash + shares * closes[i - 1], 2))
            continue
        up = upper[i - 1]
        down = lower_exit[i - 1]
        a = atr_series[i - 1]

        if shares <= 0:
            if up is not None and px > up:
                qty = cash / (px * (1 + cost))
                cash -= qty * px * (1 + cost)
                shares = qty
                stop = px - (a * atr_mult if a else px * 0.08)
                trades.append({"date": dates[i] if dates else i, "side": "buy",
                               "price": round(px, 4), "shares": round(qty, 4), "reason": "breakout"})
        else:
            hit_exit = (down is not None and px < down) or (stop > 0 and px < stop)
            if hit_exit:
                cash += shares * px * (1 - cost)
                trades.append({"date": dates[i] if dates else i, "side": "sell",
                               "price": round(px, 4), "shares": round(shares, 4),
                               "reason": "trailing_exit"})
                shares = 0.0
                stop = 0.0
            elif a:
                stop = max(stop, px - a * atr_mult)  # 移动止损只上移

        curve.append(round(cash + shares * px, 2))

    m = _metrics(curve, initial_capital)
    bm = _benchmark(closes, initial_capital)
    return {
        "strategy": "trend",
        "params": {"entry_window": entry_window, "exit_window": exit_window,
                   "atr_mult": atr_mult, "cost": cost},
        **m,
        "trade_count": len(trades),
        "benchmark_return_pct": bm["return_pct"],
        "benchmark_value": bm["value"],
        "risk_note": "震荡市中会频繁假突破（胜率偏低），收益主要来自少数大趋势。",
        "curve": {
            "dates": dates or list(range(n)),
            "strategy": curve,
            "benchmark": _benchmark_curve(closes, initial_capital),
        },
    }

def backtest_vol_target(
    closes: list[float],
    *,
    dates: list[str] | None = None,
    target_vol: float = 0.15,
    window: int = 20,
    max_leverage: float = 1.0,
    min_position: float = 0.2,
    cost: float = 0.0003,
    initial_capital: float = 100_000.0,
) -> dict[str, Any] | None:
    """波动率目标：仓位 = 目标波动 / 已实现波动（上限 max_leverage）。

    参数依据：
      - target_vol=15%：沪深 300 长期年化波动约 20%，15% 对应常态 75% 仓位，
        回撤显著低于满仓，同时不会因过度保守错失收益。
      - window=20：约一个月，既能反映当前波动状态又不会太滞后。
      - min_position=0.2：始终保留底仓，避免波动率跳升时清仓错过反弹。

    这是一个「仓位层」而不是独立策略：可叠加在任何方向上。
    """
    n = len(closes)
    if n < window + 5:
        return None
    vols = rolling_vol(closes, window)
    targets: list[float] = [0.0] * n
    for i in range(n):
        v = vols[i]
        if v is None or v <= 0:
            targets[i] = min_position
        else:
            pos = target_vol / v
            targets[i] = max(min_position, min(max_leverage, pos))

    res = run_position_backtest(
        closes, targets, dates=dates, cost=cost, initial_capital=initial_capital
    )
    if res is None:
        return None
    m = _metrics(res["curve"], initial_capital)
    bm = _benchmark(closes, initial_capital)
    avg_pos = sum(targets) / len(targets) if targets else 0
    return {
        "strategy": "vol_target",
        "params": {"target_vol": target_vol, "window": window,
                   "max_leverage": max_leverage, "cost": cost},
        **m,
        "trade_count": len(res["trades"]),
        "benchmark_return_pct": bm["return_pct"],
        "benchmark_value": bm["value"],
        "avg_position": round(avg_pos, 3),
        "risk_note": "波动率跳升有滞后，急跌时仓位下降较慢；目标波动越低越保守。",
        "curve": {
            "dates": dates or list(range(n)),
            "strategy": res["curve"],
            "benchmark": _benchmark_curve(closes, initial_capital),
        },
    }
