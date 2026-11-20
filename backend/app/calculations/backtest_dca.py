"""定投策略回测：每 N 个交易日投入固定金额，持有至期末（逐笔累计成本）。"""

from __future__ import annotations

from typing import Any

from .backtest_series import (
    DCA_DEFAULT_FREQ,
    DCA_MIN_DAYS,
    DEFAULT_COST,
    prepare_series,
)
from .portfolio_risk import max_drawdown, sharpe_ratio


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
    if invest_amount <= 0 or freq_days < 1:
        return None
    closes, dates = prepare_series(closes, dates)
    if len(closes) < DCA_MIN_DAYS:
        return None

    shares_total = 0.0
    invested = 0.0
    buy_count = 0
    last_px = closes[-1]
    for i in range(0, len(closes), freq_days):
        px = closes[i]
        if px <= 0:
            continue
        buy_shares = invest_amount / (px * (1.0 + cost))
        shares_total += buy_shares
        invested += invest_amount
        buy_count += 1
    final_value = shares_total * last_px
    final_equity = final_value

    # 资金曲线：**必须包含未投入的现金**，否则曲线从 0 开始爬升，
    # 收益率/年化/夏普/回撤全部失真。
    # 实测缺陷：单边下跌 62% 的行情下曾报出「年化 +44887%、夏普 243、
    # 最大回撤 −1.99%」——因为曲线只累计已投入份额的市值，越买越"涨"。
    #
    # 正确口径：每日净值 = 累计投入现金 − 已花掉的成本 + 持仓市值。
    # 等价于「每期投入的现金先进入组合，再按当日价买入」，曲线始终 ≥ 0 且
    # 反映了真实的资金占用。
    equity_curve: list[float] = []
    acc_shares = 0.0
    cash_in = 0.0          # 累计投入的现金
    cash_spent = 0.0       # 累计用于买入的现金（含成本）
    for i, px in enumerate(closes):
        if i % freq_days == 0:
            cash_in += invest_amount
            if px > 0:
                cost_total = invest_amount
                bought = invest_amount / (px * (1.0 + cost))
                acc_shares += bought
                cash_spent += cost_total
        # 未买入部分（例如 px<=0 无法成交）留在现金里，不被吞掉
        mv = acc_shares * px if px > 0 else 0.0
        equity_curve.append(round(cash_in - cash_spent + mv, 2))

    benchmark = closes[-1] / closes[0] * initial_capital
    # 定投的日收益率必须剔除「新投入现金」的影响，否则每期注入都会体现为
    # 一段正收益——净值曲线单调上升、最大回撤恒为 0、夏普虚高（实测 243）。
    # 做法：把每期投入当作「外部现金流」，用 Modified Dietz 的日度近似：
    #   r_t = (V_t - V_{t-1} - flow_t) / (V_{t-1} + flow_t)
    # 这里 flow_t 只在投入日非零。这是 TWR 的逐日版本，也是基金净值法的口径。
    returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        cur = equity_curve[i]
        flow = invest_amount if i % freq_days == 0 else 0.0
        base = prev + flow
        if base > 0:
            returns.append((cur - prev - flow) / base)
    # 用 TWR 日收益累乘出「不含新增资金」的等值净值曲线（起点 1.0），
    # 回撤/波动都应基于它，否则定投的曲线永远向上。
    twr_curve: list[float] = [1.0]
    for r in returns:
        twr_curve.append(twr_curve[-1] * (1.0 + r))
    total_ret = final_equity / invested - 1.0 if invested else None

    # 年化收益率对定投必须用 XIRR（资金加权），不能用「首尾净值之比」。
    # 首尾之比对定投毫无意义：首日只投了期初那笔，末日却含全部累计投入，
    # 比值会把「越投越多」当成「涨了很多」——实测曾报出年化 +44887%。
    # 这里用每笔投入日作为现金流（负）与期末市值（正）求内部收益率。
    xirr_val: float | None = None
    try:
        from datetime import date, timedelta

        from .returns import calculate_xirr

        base_day = date(2026, 1, 1)
        flows: list[tuple[date, float]] = []
        for i in range(0, len(closes), freq_days):
            if closes[i] > 0:
                flows.append((base_day + timedelta(days=i), -invest_amount))
        if flows and final_equity > 0:
            flows.append((base_day + timedelta(days=len(closes) - 1), final_equity))
            xirr_val = calculate_xirr(flows)
    except (ValueError, ZeroDivisionError, OverflowError):
        xirr_val = None
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
        # 定投的交易次数 = **实际成交的买入笔数**。
        # 旧写法用 len(range(...)) 数的是"计划投入次数"，遇到被跳过的
        # 非正价格日会虚报笔数，与 total_invested/invest_amount 对不上。
        "trade_count": buy_count,
        "round_count": 0,
        "open_position": shares_total > 0,
        "total_return_pct": round(total_ret * 100, 2) if total_ret is not None else None,
        # 定投年化必须用 XIRR（资金加权）：首尾净值之比会把「越投越多」当成
        # 「涨了很多」，实测曾报出年化 +44887%（真实是 −84%）。
        "annualized_return_pct": round(xirr_val * 100, 2) if xirr_val is not None else None,
        "annualized_basis": "xirr" if xirr_val is not None else "unavailable",
        # 回撤同样必须基于「时间加权净值」：含现金的曲线因持续注入而几乎不回撤
        # （实测跌 62% 的行情只报 −1.99%）。这里用 TWR 序列重建等值曲线。
        "max_drawdown_pct": round(max_drawdown(twr_curve) * 100, 2) if max_drawdown(twr_curve) is not None else None,
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
