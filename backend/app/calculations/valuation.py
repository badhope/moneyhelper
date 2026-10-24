"""估值温度计与定投计划：位置分位、定投成本线、下一期日期。

为什么叫"位置分位"而不是"PE 分位"：本项目只从公开行情接口取价格序列，
拿不到可信的全历史 PE/PB。用价格在自身历史区间中的分位是可验证的真实计算，
把口径写清楚，好过编一个假 PE。

位置分位 =（当前价 - 区间最低）/（区间最高 - 区间最低）× 100
- 0–20：低位区；20–40：偏低；40–60：中枢；60–80：偏高；80–100：高位区
这条指标回答的是"现在贵不贵"，不预测涨跌。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .strategy import FUND_KINDS


@dataclass
class Valuation:
    symbol: str
    name: str
    current: float
    low: float
    high: float
    percentile: float
    zone: str
    zone_label: str
    drawdown_pct: float
    lookback_days: int
    observations: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "current": self.current,
            "low": self.low,
            "high": self.high,
            "percentile": self.percentile,
            "zone": self.zone,
            "zone_label": self.zone_label,
            "drawdown_pct": self.drawdown_pct,
            "lookback_days": self.lookback_days,
            "observations": self.observations,
        }


ZONES = (
    (20.0, "cheap", "低位区"),
    (40.0, "low", "偏低"),
    (60.0, "fair", "中枢"),
    (80.0, "high", "偏高"),
    (100.1, "expensive", "高位区"),
)


def _zone(pct: float) -> tuple[str, str]:
    for upper, key, label in ZONES:
        if pct < upper:
            return key, label
    return "expensive", "高位区"


def compute_valuation(symbol: str, name: str, closes: list[float], lookback_days: int = 750) -> Valuation | None:
    """closes 为按时间升序的收盘价序列（可长于 lookback，取最后 N 个）。"""
    pts = [float(c) for c in closes if c and float(c) > 0]
    if len(pts) < 2:
        return None
    pts = pts[-lookback_days:]
    cur = pts[-1]
    lo = min(pts)
    hi = max(pts)
    # 区间无波动时给 50（中枢）：除以零会得到 inf/nan，界面上就是一条坏数据
    pct = 50.0 if hi - lo <= 1e-12 else (cur - lo) / (hi - lo) * 100.0
    pct = max(0.0, min(100.0, pct))
    zone, label = _zone(pct)
    peak = max(pts)
    return Valuation(
        symbol=symbol,
        name=name,
        current=round(cur, 4),
        low=round(lo, 4),
        high=round(hi, 4),
        percentile=round(pct, 1),
        zone=zone,
        zone_label=label,
        drawdown_pct=round((cur / peak - 1.0) * 100, 2) if peak > 0 else 0.0,
        lookback_days=lookback_days,
        observations=len(pts),
    )


# --------------------------------------------------------------------------
# 定投计划
# --------------------------------------------------------------------------

FREQUENCIES = ("monthly", "weekly")


def next_run_date(day: int, freq: str = "monthly", today: date | None = None) -> date:
    """下一期定投日。

    monthly：day=每月几号（超过当月天数时取当月最后一天）；
    weekly：day=星期几（1=周一 … 7=周日）。
    """
    today = today or date.today()
    if freq == "weekly":
        wd = max(1, min(7, int(day or 1)))
        delta = (wd - today.isoweekday()) % 7
        # 今天就是定投日 → 顺延到下周，避免同一天重复执行
        return today + timedelta(days=delta or 7)
    d = max(1, min(28, int(day or 1)))
    try:
        candidate = today.replace(day=d)
    except ValueError:
        candidate = today.replace(day=28)
    if candidate <= today:
        # 下个月
        y, m = today.year, today.month + 1
        if m > 12:
            y, m = y + 1, 1
        candidate = date(y, m, min(d, 28))
    return candidate


def compute_dca_stats(
    plan: dict[str, Any],
    closes_by_date: list[dict[str, Any]],
    price_now: float | None,
) -> dict[str, Any]:
    """定投回测：从计划开始日按周期买入，算累计投入、份额、成本线、当前盈亏。

    closes_by_date: [{date, close}] 升序。
    """
    amount = float(plan.get("amount", 0) or 0)
    freq = str(plan.get("frequency") or "monthly")
    start = str(plan.get("start_date") or "")
    if amount <= 0 or not closes_by_date:
        return {"invested": 0.0, "shares": 0.0, "avg_cost": None, "value": None, "pnl": None, "pnl_pct": None, "periods": 0, "last_buy_date": None}

    pts = [p for p in closes_by_date if p.get("close")]
    if not pts:
        return {"invested": 0.0, "shares": 0.0, "avg_cost": None, "value": None, "pnl": None, "pnl_pct": None, "periods": 0, "last_buy_date": None}

    # 按周期建立买入日
    buy_dates: list[str] = []
    if freq == "weekly":
        step = 7
        d = date.fromisoformat(start) if start else date.fromisoformat(str(pts[0]["date"])[:10])
        last = date.fromisoformat(str(pts[-1]["date"])[:10])
        while d <= last:
            buy_dates.append(d.isoformat())
            d += timedelta(days=step)
    else:
        d = date.fromisoformat(start) if start else date.fromisoformat(str(pts[0]["date"])[:10])
        last = date.fromisoformat(str(pts[-1]["date"])[:10])
        while d <= last:
            buy_dates.append(d.isoformat())
            y, m = d.year, d.month + 1
            if m > 12:
                y, m = y + 1, 1
            d = date(y, m, min(d.day, 28))

    invested = 0.0
    shares = 0.0
    periods = 0
    last_buy = None
    # 数据覆盖起点之前的定投日不补记：我们没有那段时间的真实价格，
    # 用第一根 K 线价格"补买"会凭空制造出一段不存在的历史成本。
    first_data_date = str(pts[0]["date"])[:10]
    for bd in buy_dates:
        if bd < first_data_date:
            continue
        # 取买入日当天或之后第一个有价格的交易日（停牌/周末顺延）
        px = None
        for p in pts:
            if str(p["date"])[:10] >= bd:
                px = float(p["close"])
                break
        if not px or px <= 0:
            continue
        shares += amount / px
        invested += amount
        periods += 1
        last_buy = bd

    if shares <= 0:
        return {"invested": 0.0, "shares": 0.0, "avg_cost": None, "value": None, "pnl": None, "pnl_pct": None, "periods": 0, "last_buy_date": None}

    avg_cost = invested / shares
    px_now = price_now or float(pts[-1]["close"])
    value = shares * px_now
    return {
        "invested": round(invested, 2),
        "shares": round(shares, 4),
        "avg_cost": round(avg_cost, 4),
        "value": round(value, 2),
        "pnl": round(value - invested, 2),
        "pnl_pct": round((value / invested - 1.0) * 100, 2) if invested > 0 else None,
        "periods": periods,
        "last_buy_date": last_buy,
        "current_price": round(px_now, 4),
    }


def lot_hint(kind: str) -> str:
    return "按金额申购" if kind in FUND_KINDS else "按 100 股整手"
