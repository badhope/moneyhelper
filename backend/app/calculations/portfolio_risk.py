"""组合风险与业绩归因：净值曲线、波动率、夏普、索提诺、最大回撤、Beta、VaR。

纯函数实现，只依赖标准库。所有指标以**日频**序列为输入，年化按 252 个交易日。

口径说明（对外展示必须一致，避免"看起来算过其实是拍脑袋"）：
- 收益率序列由净值曲线逐日相除得到，首日不计收益。
- 波动率 = 日收益标准差 × sqrt(252)（样本标准差，ddof=1）。
- 夏普 = (年化收益 - 无风险利率) / 年化波动率；年化收益用几何年化。
- 索提诺分母只统计下行偏差（低于目标收益的部分）。
- 最大回撤 = min(净值 / 历史峰值 - 1)，返回负值。
- Beta = cov(组合日收益, 基准日收益) / var(基准日收益)。
- VaR(95%) 用历史模拟法：日收益的 5% 分位数（返回负值）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

TRADING_DAYS = 252


@dataclass
class RiskMetrics:
    """组合风险指标快照。字段为 None 表示样本不足，前端据此显示"数据不足"而不是 0。"""

    observations: int
    total_return_pct: float | None = None
    annualized_return_pct: float | None = None
    annualized_volatility_pct: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    max_drawdown_pct: float | None = None
    calmar: float | None = None
    var_95_pct: float | None = None
    beta: float | None = None
    alpha_pct: float | None = None
    benchmark_return_pct: float | None = None
    excess_return_pct: float | None = None
    win_rate_pct: float | None = None
    best_day_pct: float | None = None
    worst_day_pct: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": self.observations,
            "total_return_pct": self.total_return_pct,
            "annualized_return_pct": self.annualized_return_pct,
            "annualized_volatility_pct": self.annualized_volatility_pct,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "max_drawdown_pct": self.max_drawdown_pct,
            "calmar": self.calmar,
            "var_95_pct": self.var_95_pct,
            "beta": self.beta,
            "alpha_pct": self.alpha_pct,
            "benchmark_return_pct": self.benchmark_return_pct,
            "excess_return_pct": self.excess_return_pct,
            "win_rate_pct": self.win_rate_pct,
            "best_day_pct": self.best_day_pct,
            "worst_day_pct": self.worst_day_pct,
            "notes": list(self.notes),
        }


def daily_returns(values: list[float]) -> list[float]:
    """净值序列 → 日收益率序列。非正净值视为无效点跳过（避免除零与假信号）。"""
    out: list[float] = []
    prev: float | None = None
    for v in values:
        if v is None or v <= 0:
            continue
        if prev is not None and prev > 0:
            out.append(v / prev - 1.0)
        prev = v
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _stdev(xs: list[float]) -> float:
    """样本标准差（ddof=1）。少于 2 个样本返回 0。"""
    n = len(xs)
    if n < 2:
        return 0.0
    mu = _mean(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))


def annualized_volatility(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    return _stdev(returns) * math.sqrt(TRADING_DAYS)


def annualized_return(values: list[float]) -> float | None:
    """几何年化：按实际交易日数量折算，样本少于 2 个点返回 None。"""
    pts = [v for v in values if v and v > 0]
    if len(pts) < 2:
        return None
    total = pts[-1] / pts[0]
    years = (len(pts) - 1) / TRADING_DAYS
    if years <= 0:
        return None
    if total <= 0:
        return None
    return total ** (1.0 / years) - 1.0


def max_drawdown(values: list[float]) -> float | None:
    """最大回撤（负值，如 -0.231 表示 -23.1%）。"""
    pts = [v for v in values if v and v > 0]
    if len(pts) < 2:
        return None
    peak = pts[0]
    worst = 0.0
    for v in pts:
        if v > peak:
            peak = v
        dd = v / peak - 1.0
        if dd < worst:
            worst = dd
    return worst


def sharpe_ratio(returns: list[float], risk_free: float = 0.0) -> float | None:
    """夏普比率：年化超额收益 / 年化波动。样本不足或零波动返回 None。"""
    if len(returns) < 20:
        return None
    vol = annualized_volatility(returns)
    if not vol or vol <= 1e-12:
        return None
    growth = 1.0
    for r in returns:
        growth *= 1.0 + r
    years = len(returns) / TRADING_DAYS
    if years <= 0 or growth <= 0:
        return None
    ann = growth ** (1.0 / years) - 1.0
    return (ann - risk_free) / vol


def sortino_ratio(returns: list[float], target: float = 0.0) -> float | None:
    """索提诺比率：分母只用下行偏差。"""
    if len(returns) < 20:
        return None
    downside = [min(0.0, r - target) for r in returns]
    dd = math.sqrt(sum(d * d for d in downside) / len(downside)) * math.sqrt(TRADING_DAYS)
    if dd <= 1e-12:
        return None
    growth = 1.0
    for r in returns:
        growth *= 1.0 + r
    ann = growth ** (TRADING_DAYS / len(returns)) - 1.0
    return (ann - target) / dd


def beta_alpha(
    portfolio_returns: list[float], benchmark_returns: list[float], risk_free: float = 0.0
) -> tuple[float | None, float | None]:
    """对齐长度后计算 Beta 与年化 Alpha（CAPM 单因子）。"""
    n = min(len(portfolio_returns), len(benchmark_returns))
    if n < 20:
        return None, None
    p = portfolio_returns[-n:]
    b = benchmark_returns[-n:]
    mb = _mean(b)
    mp = _mean(p)
    var_b = sum((x - mb) ** 2 for x in b) / (n - 1)
    if var_b <= 1e-18:
        return None, None
    cov = sum((p[i] - mp) * (b[i] - mb) for i in range(n)) / (n - 1)
    beta = cov / var_b
    ann_p = mp * TRADING_DAYS
    ann_b = mb * TRADING_DAYS
    alpha = ann_p - (risk_free + beta * (ann_b - risk_free))
    return beta, alpha


def historical_var(returns: list[float], confidence: float = 0.95) -> float | None:
    """历史模拟法 VaR：返回该置信度下的日收益分位（负值）。"""
    if len(returns) < 30:
        return None
    ordered = sorted(returns)
    idx = int((1.0 - confidence) * len(ordered))
    idx = max(0, min(idx, len(ordered) - 1))
    return ordered[idx]


def compute_risk_metrics(
    equity_values: list[float],
    benchmark_values: list[float] | None = None,
    risk_free: float = 0.02,
) -> RiskMetrics:
    """从净值曲线（组合 + 可选基准）计算全套风险指标。"""
    clean = [v for v in equity_values if v and v > 0]
    m = RiskMetrics(observations=len(clean))
    if len(clean) < 2:
        m.notes.append("净值样本不足，至少需要 2 个交易日")
        return m

    rets = daily_returns(clean)
    m.total_return_pct = round((clean[-1] / clean[0] - 1.0) * 100, 2)
    # 年化指标在样本 < 60 个交易日时会被极端放大（14 天涨 20% 会年化成 3000%+），
    # 这种数字放上界面就是误导。宁可返回 None，让前端显示「数据不足」。
    ann: float | None = None
    if len(rets) >= 60:
        ann = annualized_return(clean)
    m.annualized_return_pct = round(ann * 100, 2) if ann is not None else None
    vol = annualized_volatility(rets) if len(rets) >= 20 else None
    m.annualized_volatility_pct = round(vol * 100, 2) if vol is not None else None
    sr = sharpe_ratio(rets, risk_free)
    m.sharpe = round(sr, 3) if sr is not None else None
    so = sortino_ratio(rets, risk_free / TRADING_DAYS)
    m.sortino = round(so, 3) if so is not None else None
    mdd = max_drawdown(clean)
    m.max_drawdown_pct = round(mdd * 100, 2) if mdd is not None else None
    if ann is not None and mdd is not None and mdd < 0:
        m.calmar = round(ann / abs(mdd), 3)
    var = historical_var(rets)
    m.var_95_pct = round(var * 100, 2) if var is not None else None
    if rets:
        m.win_rate_pct = round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1)
        m.best_day_pct = round(max(rets) * 100, 2)
        m.worst_day_pct = round(min(rets) * 100, 2)

    if benchmark_values:
        bclean = [v for v in benchmark_values if v and v > 0]
        if len(bclean) >= 2:
            brets = daily_returns(bclean)
            b, a = beta_alpha(rets, brets, risk_free)
            m.beta = round(b, 3) if b is not None else None
            m.alpha_pct = round(a * 100, 2) if a is not None else None
            m.benchmark_return_pct = round((bclean[-1] / bclean[0] - 1.0) * 100, 2)
            m.excess_return_pct = round(m.total_return_pct - m.benchmark_return_pct, 2)
        else:
            m.notes.append("基准样本不足，未计算 Beta/Alpha")

    if len(clean) < 60:
        m.notes.append("样本少于 60 个交易日，年化指标参考意义有限")
    return m


def build_equity_curve(
    holdings: list[dict[str, Any]], price_history: dict[str, list[dict[str, Any]]], cash: float = 0.0
) -> list[float]:
    """按**当前持仓**回溯净值曲线（回测口径，非实盘历史净值）。

    holdings: [{symbol, shares}]；price_history: {symbol: [{date, close}]}。
    以各标的共同日期为轴，缺失价格用最近一个有效收盘价（前向填充）。
    这是"若一直持有当前仓位"的近似曲线，接口必须标注为回溯，不能当作真实历史业绩。
    """
    if not holdings:
        return []
    series: dict[str, dict[str, float]] = {}
    all_dates: set[str] = set()
    for h in holdings:
        sym = str(h.get("symbol", ""))
        pts = price_history.get(sym) or []
        if not pts:
            continue
        by_date: dict[str, float] = {}
        for p in pts:
            d = str(p.get("date", ""))
            c = p.get("close")
            if d and c:
                by_date[d] = float(c)
                all_dates.add(d)
        if by_date:
            series[sym] = by_date
    if not series or len(all_dates) < 2:
        return []
    dates = sorted(all_dates)
    last: dict[str, float] = {}
    out: list[float] = []
    for d in dates:
        total = cash
        for h in holdings:
            sym = str(h.get("symbol", ""))
            if sym not in series:
                continue
            if d in series[sym]:
                last[sym] = series[sym][d]
            px = last.get(sym)
            if px is None:
                continue
            total += float(h.get("shares", 0) or 0) * px
        if total > 0:
            out.append(round(total, 2))
    return out
