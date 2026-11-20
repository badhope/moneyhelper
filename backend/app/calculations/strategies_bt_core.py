"""回测执行引擎：目标仓位序列 → 成本/次日成交/风控，外加指标与基准助手。

统一口径：第 i 天收盘后决策，i+1 天成交，避免前视偏差。
"""

from __future__ import annotations

from typing import Any


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
