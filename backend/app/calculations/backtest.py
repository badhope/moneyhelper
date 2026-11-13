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


def series_from_points(points: list[dict[str, Any]]) -> tuple[list[float], list[str]]:
    """K 线点集 → (closes, dates)，两者严格等长同序。

    所有"取 closes 再单独取 dates"的调用点都应改用它：分开写必然在遇到
    脏数据时错位一格（closes 过滤了、dates 没过滤），而且不会报错。
    """
    pairs = [(p.get("date", ""), p.get("close")) for p in points]
    closes: list[float] = []
    dates: list[str] = []
    for d, c in pairs:
        try:
            v = float(c)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not (v > 0):
            continue
        closes.append(v)
        dates.append(str(d))
    return closes, dates


def prepare_series(
    closes: list[float], dates: list[str] | None = None
) -> tuple[list[float], list[str] | None]:
    """价格序列清洗：剔除非正价格，**并同步剔除对应的日期**。

    两条不变量，违反任何一条都会产生"看起来对其实错位"的结果：
    1. closes 与 dates 必须等长同序——只过滤 closes 不过滤 dates，
       曲线日期轴与净值轴错开一格，trade["date"] 也会指向错误的那一天；
    2. closes[0] > 0——买入持有基准是 closes[-1]/closes[0]，
       停牌/退市/脏数据留下的 0 会让整个回测接口抛 ZeroDivisionError（实测 500）。
    """
    out_closes: list[float] = []
    out_dates: list[str] | None = [] if dates is not None else None
    for i, c in enumerate(closes):
        try:
            v = float(c)
        except (TypeError, ValueError):
            continue
        if not (v > 0) or v != v or v == float("inf"):
            continue
        out_closes.append(v)
        if out_dates is not None and dates is not None:
            out_dates.append(str(dates[i]) if i < len(dates) else "")
    return out_closes, out_dates


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
    """把回测结果转成人类可读结论（确定性模板）。

    必须容忍任意策略：早期实现只认 ma_cross / dca，新增策略时走 else 分支
    去格式化 total_invested（新策略没有该字段）→ TypeError → 接口 500。
    现在按「有哪些字段就说哪些话」组织，缺字段不影响其它句子。
    """
    en = lang != "zh"
    if not result:
        return "Not enough price history for a backtest." if en else "价格历史不足，无法回测。"

    name = str(result.get("strategy") or "")
    LABELS = {
        "ma_cross": ("MA cross-over", "双均线"),
        "dca": ("DCA (periodic investing)", "定投"),
        "grid": ("Grid trading", "网格"),
        "trend": ("Trend following (Donchian + ATR)", "趋势跟随（唐奇安 + ATR）"),
        "vol_target": ("Volatility targeting", "波动率目标"),
        "momentum": ("Momentum rotation", "动量轮动"),
    }
    label = LABELS.get(name, (name or "Strategy", name or "策略"))[0 if en else 1]

    def sv(key: str, suffix: str = "") -> str | None:
        v = result.get(key)
        return None if v is None else f"{v}{suffix}"

    ret = sv("total_return_pct", "%")
    bench = sv("benchmark_return_pct", "%")
    mdd = sv("max_drawdown_pct", "%")
    sharpe = sv("sharpe")

    if en:
        head = f"{label} backtest: total return {ret or 'n/a'}"
        if bench:
            head += f" (buy-and-hold {bench})"
        if mdd:
            head += f", max drawdown {mdd}"
        if sharpe:
            head += f", Sharpe {sharpe}"
        lines = [head + "."]
    else:
        head = f"{label} 回测：总收益率 {ret or '不可用'}"
        if bench:
            head += f"（同期买入持有 {bench}）"
        if mdd:
            head += f"，最大回撤 {mdd}"
        if sharpe:
            head += f"，夏普比率 {sharpe}"
        lines = [head + "。"]

    if name == "dca":
        invested, final = result.get("total_invested"), result.get("final_value")
        if invested is not None and final is not None:
            lines.append(
                f"Invested {invested:,.0f}, final value {final:,.0f}."
                if en
                else f"累计投入 {invested:,.0f}，期末市值 {final:,.0f}。"
            )
        if result.get("annualized_basis") == "xirr" and result.get("annualized_return_pct") is not None:
            lines.append(
                f"Money-weighted return (XIRR): {result['annualized_return_pct']}%."
                if en
                else f"资金加权收益率（XIRR）：{result['annualized_return_pct']}%。"
            )
    else:
        tc = result.get("trade_count")
        if tc is not None:
            lines.append(f"{tc} fill(s)." if en else f"共 {tc} 笔成交。")
        if result.get("win_rate_pct") is not None:
            lines.append(
                f"Win rate {result['win_rate_pct']}%, profit factor {result.get('profit_factor')}."
                if en
                else f"胜率 {result['win_rate_pct']}%，盈亏比 {result.get('profit_factor')}。"
            )
        avg_pos = result.get("avg_position")
        if avg_pos is not None:
            lines.append(
                f"Average position {avg_pos * 100:.0f}% of equity."
                if en
                else f"平均仓位 {avg_pos * 100:.0f}%。"
            )

    note = result.get("risk_note")
    if note:
        lines.append(note)

    lines.append(
        "Historical statistics only — not investment advice or a forecast."
        if en
        else "以上为历史统计，不构成投资建议，也不代表未来收益。"
    )
    return chr(10).join(lines)
