"""双均线策略回测：MA5 上穿 MA20 全仓买、下穿全仓卖（单标的、无杠杆）。"""

from __future__ import annotations

from typing import Any

from ._shared import sma as _sma
from .backtest_series import (
    DEFAULT_COST,
    MA_CROSS_MIN_DAYS,
    _position_size,
    prepare_series,
)
from .portfolio_risk import (
    annualized_return,
    daily_returns,
    max_drawdown,
    sharpe_ratio,
)


def backtest_ma_cross(
    closes: list[float],
    dates: list[str] | None = None,
    fast: int = 5,
    slow: int = 20,
    cost: float = DEFAULT_COST,
    initial_capital: float = 100000.0,
) -> dict[str, Any] | None:
    """双均线策略回测。数据不足 slow×3 根返回 None。

    口径：MA_fast 上穿 MA_slow 的次日开盘全仓买入、下穿次日开盘清仓（简化为收盘触发、
    次日收盘执行）；不做日内优化，避免幸存者偏差式的好看数字。

    fast 必须严格小于 slow：两者反过来时"多头排列"变成均值回归条件，
    跑出来的仍是一份看起来正常的报告，但策略含义已经完全反了（静默错，最难发现）。
    这里直接拒绝，让调用方给出 400 而不是一个错的答案。
    """
    if fast < 2 or slow < 2 or fast >= slow:
        raise ValueError(f"均线参数非法：fast({fast}) 必须 >= 2 且严格小于 slow({slow})")
    closes, dates = prepare_series(closes, dates)
    if len(closes) < max(MA_CROSS_MIN_DAYS, slow * 3):
        return None
    fast_ma = _sma(closes, fast)
    slow_ma = _sma(closes, slow)

    equity = initial_capital
    cash = equity
    shares = 0.0
    equity_curve: list[float] = [equity]
    trades: list[dict[str, Any]] = []
    position = 0.0  # 0=空仓 1=满仓

    for i in range(1, len(closes)):
        f, fp = fast_ma[i], fast_ma[i - 1]
        s, sp = slow_ma[i], slow_ma[i - 1]
        if None in (f, fp, s, sp):
            equity_curve.append(equity)
            continue
        px = closes[i]
        # 入场条件用「均线多头排列」而不是只认「金叉那一刻」：
        # 金叉是一个瞬时事件，如果回测起点已经在多头排列中（或行情平滑上涨
        # 使交叉从未发生），策略会全程空仓——实测单边上涨 60% 报 0% 收益。
        # 多头排列（fast > slow）是状态量，任何时刻成立就应持仓。
        if position == 0 and f > s:
            # 多头排列：全仓买入
            if px <= 0:
                equity_curve.append(equity)
                continue
            shares, cash = _position_size(px, equity, cost)
            position = 1
            trades.append(
                {
                    "date": dates[i] if dates else i,
                    "side": "buy",
                    "price": round(px, 4),
                    "amount": round(shares * px, 2),
                }
            )
        elif position == 1 and fp >= sp and f < s:
            # 死叉：清仓（卖出所得净额入现金）
            if shares > 0 and px > 0:
                cash = shares * px * (1.0 - cost)
                trades.append(
                    {
                        "date": dates[i] if dates else i,
                        "side": "sell",
                        "price": round(px, 4),
                        "amount": round(shares * px, 2),
                    }
                )
                shares = 0.0
                position = 0
        equity = cash + shares * px
        equity_curve.append(round(equity, 2))

    # 期末未平仓按最后收盘价结算
    final_equity = cash + shares * closes[-1]
    benchmark = closes[-1] / closes[0] * initial_capital

    # 统计完整回合（buy→sell 配对）
    buys = [t for t in trades if t["side"] == "buy"]
    sells = [t for t in trades if t["side"] == "sell"]
    rounds: list[float] = []
    for b, s in zip(buys, sells, strict=False):
        if b["price"] > 0 and s["price"] > 0:
            ret = (s["price"] * (1 - cost)) / (b["price"] * (1 + cost)) - 1.0
            rounds.append(ret)
    wins = [r for r in rounds if r > 0]
    losses = [r for r in rounds if r <= 0]
    win_rate = round(len(wins) / len(rounds) * 100, 1) if rounds else None
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    # 盈亏比 = 总盈利 / |总亏损|。losses 存的是负收益率，分母必须取绝对值：
    # 旧写法直接除 sum(losses)，算出的是**负数**（实测胜率 80%、
    # 平均盈利 5.74% / 平均亏损 12.62% 的组合报出 profit_factor = -1.82），
    # 前端原样展示成"盈亏比 -1.82"，读起来像策略在稳定亏钱。
    gross_loss = abs(sum(losses))
    profit_factor = round(sum(wins) / gross_loss, 2) if (wins and gross_loss > 0) else None

    returns = daily_returns(equity_curve)
    total_ret = final_equity / initial_capital - 1.0
    return {
        "strategy": "ma_cross",
        "params": {"fast": fast, "slow": slow, "cost": cost, "initial_capital": initial_capital},
        "total_return_pct": round(total_ret * 100, 2),
        "annualized_return_pct": round(annualized_return(equity_curve) * 100, 2) if annualized_return(equity_curve) is not None else None,
        "max_drawdown_pct": round(max_drawdown(equity_curve) * 100, 2) if max_drawdown(equity_curve) is not None else None,
        "sharpe": round(sharpe_ratio(returns), 2) if sharpe_ratio(returns) is not None else None,
        # 交易次数按「成交笔数」计，不能用 len(trades)//2：
        # 只买未卖（期末仍持仓）时 //2 会得到 0，用户会以为策略从未交易。
        "trade_count": len(trades),
        "round_count": len(rounds),   # 完整买卖回合（用于胜率/盈亏比）
        "open_position": bool(shares > 0),
        "rounds": len(rounds),
        "win_rate_pct": win_rate,
        "profit_factor": profit_factor,
        "avg_win_pct": round(avg_win * 100, 2) if wins else None,
        "avg_loss_pct": round(avg_loss * 100, 2) if losses else None,
        "benchmark_return_pct": round((benchmark / initial_capital - 1.0) * 100, 2),
        "final_equity": round(final_equity, 2),
        "benchmark_equity": round(benchmark, 2),
        "curve": {
            "dates": dates or list(range(len(equity_curve))),
            "strategy": [round(v, 2) for v in equity_curve],
            "benchmark": [
                round(closes[i] / closes[0] * initial_capital, 2) for i in range(len(closes))
            ],
        },
        "trades": trades[-20:],
    }
