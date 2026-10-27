"""策略回测引擎（股票投研 · 纯函数确定性计算）。

策略：
- ma_cross  双均线策略：MA5 上穿 MA20 全仓买入，下穿全仓卖出（单标的、无杠杆）。
- dca       定投策略：每 N 个交易日投入固定金额，持有至期末（不复利再投，逐笔累计成本）。

输出指标（口径与 portfolio_risk 一致，直接复用其函数）：
- 总收益率 / 年化收益率 / 最大回撤 / 夏普比率（日频、无风险利率 0）
- 交易次数 / 胜率（按完整买卖回合）/ 盈亏比（平均盈利 ÷ 平均亏损）
- 资金曲线（净值序列，含基准「买入持有」对比）

设计原则：
1. 纯函数、无 I/O。K 线由 quotes 层负责，这里只吃价格序列。
2. 交易成本可配置（默认单边 0.03%，买卖各扣一次），体现真实摩擦。
3. 数据不足 60 根日线（双均线预热）直接返回 None，不编造回测结论。
4. 回测结果仅作历史统计，不构成未来收益预测或投资建议。
"""

from __future__ import annotations

from typing import Any

from .portfolio_risk import (
    annualized_return,
    daily_returns,
    max_drawdown,
    sharpe_ratio,
)

TRADING_DAYS = 252
DEFAULT_COST = 0.0003  # 单边交易成本（佣金+滑点估算）
MA_CROSS_MIN_DAYS = 60
DCA_MIN_DAYS = 20
DCA_DEFAULT_FREQ = 5  # 每 5 个交易日投入一次


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


def _position_size(close: float, equity: float, cost: float) -> tuple[float, float]:
    """按净值全仓买入（含成本）：返回 (买入数量, 扣成本后剩余现金)。"""
    afford = equity / (1.0 + cost)
    shares = afford / close
    cash = equity - shares * close * (1.0 + cost)
    return shares, cash


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
    """
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
        if position == 0 and fp <= sp and f > s:
            # 金叉：全仓买入
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
    profit_factor = round((sum(wins) / (sum(losses) if losses else 0.0)), 2) if (wins and losses) else None

    returns = daily_returns(equity_curve)
    total_ret = final_equity / initial_capital - 1.0
    return {
        "strategy": "ma_cross",
        "params": {"fast": fast, "slow": slow, "cost": cost, "initial_capital": initial_capital},
        "total_return_pct": round(total_ret * 100, 2),
        "annualized_return_pct": round(annualized_return(equity_curve) * 100, 2) if annualized_return(equity_curve) is not None else None,
        "max_drawdown_pct": round(max_drawdown(equity_curve) * 100, 2) if max_drawdown(equity_curve) is not None else None,
        "sharpe": round(sharpe_ratio(returns), 2) if sharpe_ratio(returns) is not None else None,
        "trade_count": len(trades) // 2,
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


def backtest_dca(
    closes: list[float],
    dates: list[str] | None = None,
    invest_amount: float = 1000.0,
    freq_days: int = DCA_DEFAULT_FREQ,
    cost: float = DEFAULT_COST,
    initial_capital: float = 100000.0,
) -> dict[str, Any] | None:
    """定投策略回测：每 freq_days 个交易日投入 invest_amount，持有至期末。

    基准为「期初一次性买入持有」。期末净值 = Σ 各笔投入的份额 × 期末价 + 剩余现金。
    """
    if len(closes) < DCA_MIN_DAYS or invest_amount <= 0 or freq_days < 1:
        return None

    shares_total = 0.0
    invested = 0.0
    last_px = closes[-1]
    for i in range(0, len(closes), freq_days):
        px = closes[i]
        if px <= 0:
            continue
        buy_shares = invest_amount / (px * (1.0 + cost))
        shares_total += buy_shares
        invested += invest_amount
    final_value = shares_total * last_px
    final_equity = final_value

    # 资金曲线：按日累加已投入份额的市值
    equity_curve: list[float] = []
    acc_shares = 0.0
    for i, px in enumerate(closes):
        if px <= 0:
            continue
        if i % freq_days == 0:
            acc_shares += invest_amount / (px * (1.0 + cost))
        equity_curve.append(round(acc_shares * px, 2))
    # 资金曲线未满长度时补齐（首日即建仓时长度一致）
    benchmark = closes[-1] / closes[0] * initial_capital
    returns = daily_returns(equity_curve)
    total_ret = final_equity / invested - 1.0 if invested else None
    return {
        "strategy": "dca",
        "params": {
            "invest_amount": invest_amount,
            "freq_days": freq_days,
            "cost": cost,
            "initial_capital": initial_capital,
        },
        "total_invested": round(invested, 2),
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_ret * 100, 2) if total_ret is not None else None,
        "annualized_return_pct": round(annualized_return(equity_curve) * 100, 2) if annualized_return(equity_curve) is not None else None,
        "max_drawdown_pct": round(max_drawdown(equity_curve) * 100, 2) if max_drawdown(equity_curve) is not None else None,
        "sharpe": round(sharpe_ratio(returns), 2) if sharpe_ratio(returns) is not None else None,
        "benchmark_return_pct": round((benchmark / initial_capital - 1.0) * 100, 2),
        "benchmark_value": round(benchmark, 2),
        "curve": {
            "dates": dates or list(range(len(equity_curve))),
            "strategy": equity_curve,
            "benchmark": [
                round(closes[i] / closes[0] * initial_capital, 2) for i in range(len(closes))
            ],
        },
    }


def run_backtest(
    closes: list[float],
    dates: list[str] | None = None,
    strategy: str = "ma_cross",
    **params: Any,
) -> dict[str, Any] | None:
    """策略分发入口。strategy ∈ {ma_cross, dca}，参数透传。"""
    if strategy == "ma_cross":
        return backtest_ma_cross(closes, dates, **params)
    if strategy == "dca":
        return backtest_dca(closes, dates, **params)
    return None


def backtest_text(result: dict[str, Any], lang: str = "zh") -> str:
    """把回测结果转成人类可读结论（确定性模板）。"""
    en = lang != "zh"
    if not result:
        return "Not enough price history for a backtest." if en else "价格历史不足，无法回测。"
    name = result["strategy"]
    label = "DCA (periodic investing)" if name == "dca" else "MA cross-over (5/20)"
    ret = result.get("total_return_pct")
    bench = result.get("benchmark_return_pct")
    mdd = result.get("max_drawdown_pct")
    sharpe = result.get("sharpe")
    if en:
        lines = [
            f"{label} backtest: total return {ret}% (buy-and-hold {bench}%), "
            f"max drawdown {mdd}%, Sharpe {sharpe}."
        ]
        if name == "ma_cross":
            lines.append(
                f"{result.get('trade_count')} round-trip trade(s), win rate {result.get('win_rate_pct')}%, "
                f"profit factor {result.get('profit_factor')}."
            )
        else:
            lines.append(
                f"Invested {result.get('total_invested'):,.0f}, final value {result.get('final_value'):,.0f}."
            )
    else:
        lines = [
            f"{label} 回测：总收益率 {ret}%（同期买入持有 {bench}%），"
            f"最大回撤 {mdd}%，夏普比率 {sharpe}。"
        ]
        if name == "ma_cross":
            lines.append(
                f"共 {result.get('trade_count')} 次完整买卖，胜率 {result.get('win_rate_pct')}%，"
                f"盈亏比 {result.get('profit_factor')}。"
            )
        else:
            lines.append(f"累计投入 {result.get('total_invested'):,.0f}，期末市值 {result.get('final_value'):,.0f}。")
    lines.append(
        "Historical statistics only — not investment advice or a forecast."
        if en
        else "以上为历史统计，不构成投资建议，也不代表未来收益。"
    )
    return "\n".join(lines)
