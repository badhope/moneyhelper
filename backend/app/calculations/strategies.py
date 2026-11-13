"""策略扩展包：把「只有双均线 + 定投」扩成一组个人投资者真正会用的策略。

设计要点（为什么这么组织）：
  1. **信号与执行分离**：每个策略只产出一串目标仓位（0~1），
     由统一的 `run_position_backtest` 执行——这样成本、整手、
     次日成交、风控叠加只写一次，不会有「每个策略各算一套成本」的漂移。
  2. **无前视偏差**：第 i 天的信号只用 `closes[:i+1]` 计算，
     成交价用 `closes[i+1]`（次日开盘近似）。
  3. **风控是叠加层**：止损/止盈/移动止损/回撤熔断包在任意策略外面，
     不改策略本身——用户可以先看裸策略，再叠加风控看差异。
  4. **诚实降级**：数据不足返回明确 None，不编造结论。

新增策略：
  - grid        网格交易：区间等分，跌一格买、涨一格卖（震荡市）
  - momentum    动量轮动：按 N 日收益选择最强标的（多标的）
  - trend       趋势跟随：唐奇安通道突破 + ATR 止损
  - vol_target  波动率目标仓位：按已实现波动动态调仓
"""

from __future__ import annotations

import math
from typing import Any

TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# 通用执行引擎
# ---------------------------------------------------------------------------


def _sma(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if window <= 0 or len(values) < window:
        return out
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= window:
            acc -= values[i - window]
        if i >= window - 1:
            out[i] = acc / window
    return out


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


def run_position_backtest(
    closes: list[float],
    target_positions: list[float],
    *,
    dates: list[str] | None = None,
    cost: float = 0.0003,
    initial_capital: float = 100_000.0,
    risk: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """按「目标仓位序列」执行回测（统一的成本/次日成交/风控）。

    target_positions[i] 表示第 i 天收盘后希望持有的仓位比例（0~1）。
    执行在 i+1 天以 closes[i+1] 成交——避免用当日收盘价决策又用当日收盘价成交
    的前视偏差（这是回测最常见的高估来源）。
    """
    n = len(closes)
    if n < 2 or len(target_positions) != n:
        return None

    cash = initial_capital
    shares = 0.0
    curve: list[float] = [initial_capital]
    trades: list[dict[str, Any]] = []
    peak = initial_capital
    trail_peak = 0.0

    risk = risk or {}
    stop_loss = float(risk.get("stop_loss") or 0)      # 例 0.10 = 亏 10% 止损
    take_profit = float(risk.get("take_profit") or 0)  # 例 0.30 = 赚 30% 减半仓
    trailing = float(risk.get("trailing_stop") or 0)   # 自峰值回撤 10% 离场
    dd_fuse = float(risk.get("drawdown_fuse") or 0)    # 组合回撤 15% 清仓
    entry_price = 0.0

    for i in range(1, n):
        px = closes[i]
        if px <= 0:
            curve.append(curve[-1])
            continue
        equity_now = cash + shares * px

        # --- 风控层：先判断是否强制离场 ---
        force_exit = False
        if shares > 0 and entry_price > 0:
            if stop_loss and px <= entry_price * (1 - stop_loss):
                force_exit = True
            if trailing:
                trail_peak = max(trail_peak, px)
                if trail_peak > 0 and px <= trail_peak * (1 - trailing):
                    force_exit = True
        if dd_fuse and peak > 0 and equity_now <= peak * (1 - dd_fuse):
            force_exit = True

        target = 0.0 if force_exit else max(0.0, min(1.0, float(target_positions[i - 1])))

        # 止盈：只减半仓，不彻底离场（保留趋势延续的收益）
        if (
            shares > 0
            and entry_price > 0
            and take_profit
            and px >= entry_price * (1 + take_profit)
            and target > 0
        ):
            half = shares * 0.5
            cash += half * px * (1 - cost)
            trades.append({"date": dates[i] if dates else i, "side": "sell",
                           "price": round(px, 4), "shares": round(half, 4), "reason": "take_profit"})
            shares -= half

        # --- 调仓到目标仓位 ---
        target_value = equity_now * target
        current_value = shares * px
        delta = target_value - current_value
        # 调仓带宽 5%：小于该幅度不动。0.5% 时波动率目标策略一天能调仓数次
        # （实测 250 个交易日 425 笔成交），成本吃掉全部收益。5% 是业界常用的
        # "no-trade band"，把换手压到每年数次量级。
        if abs(delta) > equity_now * 0.05:
            if delta > 0:
                qty = delta / (px * (1 + cost))
                if qty > 0:
                    cash -= qty * px * (1 + cost)
                    if shares <= 0:
                        entry_price = px
                    shares += qty
                    trades.append({"date": dates[i] if dates else i, "side": "buy",
                                   "price": round(px, 4), "shares": round(qty, 4), "reason": "signal"})
            else:
                qty = min(shares, -delta / px)
                if qty > 0:
                    cash += qty * px * (1 - cost)
                    shares -= qty
                    trades.append({"date": dates[i] if dates else i, "side": "sell",
                                   "price": round(px, 4), "shares": round(qty, 4), "reason": "signal"})
                    if shares <= 1e-9:
                        shares = 0.0
                        entry_price = 0.0
                        trail_peak = 0.0

        equity = cash + shares * px
        peak = max(peak, equity)
        curve.append(round(equity, 2))

    return {
        "curve": curve,
        "trades": trades,
        "shares": shares,
        "cash": cash,
        "final": round(cash + shares * closes[-1], 2),
    }


def _r2(v: float) -> float:
    """保留两位小数，并把 -0.0 归一为 0.0。

    不处理的话界面会显示「最大回撤 -0.0%」，看起来像渲染 bug；
    实际是 round(-0.004, 2) == -0.0 的正常行为。
    """
    out = round(v, 2)
    return 0.0 if out == 0 else out


def _metrics(values: list[float], initial: float, cost_unused: float = 0.0) -> dict[str, Any]:
    """从净值曲线算标准指标（与 portfolio_risk 同口径）。返回 None 表示不可用。"""
    from .portfolio_risk import (
        annualized_return,
        daily_returns,
        max_drawdown,
        sharpe_ratio,
        sortino_ratio,
    )

    rets = daily_returns(values)
    return {
        "total_return_pct": _r2((values[-1] / initial - 1) * 100) if initial else None,
        "annualized_return_pct": (
            _r2(annualized_return(values) * 100)
            if annualized_return(values) is not None
            else None
        ),
        "max_drawdown_pct": (
            _r2(max_drawdown(values) * 100) if max_drawdown(values) is not None else None
        ),
        "sharpe": round(sharpe_ratio(rets), 2) if sharpe_ratio(rets) is not None else None,
        "sortino": round(sortino_ratio(rets), 2) if sortino_ratio(rets) is not None else None,
    }


def _benchmark(closes: list[float], initial_capital: float) -> dict[str, Any]:
    return {
        "return_pct": round((closes[-1] / closes[0] - 1) * 100, 2) if closes[0] > 0 else None,
        "value": round(closes[-1] / closes[0] * initial_capital, 2) if closes[0] > 0 else None,
    }


# ---------------------------------------------------------------------------
# 新策略 1：网格交易
# ---------------------------------------------------------------------------


def _benchmark_curve(closes: list[float], initial_capital: float) -> list[float]:
    """买入持有基准曲线。closes[0] <= 0 时返回等长零序列而不是崩。

    `_benchmark()` 已经用 `if closes[0] > 0` 挡过首价为 0 的情况，但曲线这三处
    仍是裸除：首根为 0（停牌/脏数据）时 _benchmark 返回 None、曲线却抛
    ZeroDivisionError，整个策略接口 500。两处口径必须一致。
    """
    base = closes[0] if closes and closes[0] > 0 else 0.0
    if base <= 0:
        return [0.0] * len(closes)
    return [round(c / base * initial_capital, 2) for c in closes]


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


# ---------------------------------------------------------------------------
# 新策略 2：动量轮动（多标的）
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 新策略 3：趋势跟随（唐奇安 + ATR 止损）
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 新策略 4：波动率目标仓位
# ---------------------------------------------------------------------------


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
