"""现金流预测：按月净额 + 分位数区间，样本不足返回 note。"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from .cashflow_rules import MIN_MONTHS_FOR_FORECAST
from .cashflow_util import _month_key, _month_range, _parse_date, _quantile


def cashflow_forecast(
    transactions: list[dict[str, Any]],
    *,
    months_ahead: int = 3,
    opening_balance: float = 0.0,
    lookback_months: int = 6,
    large_amount_threshold: float = 20_000.0,
    as_of: date | None = None,
) -> dict[str, Any]:
    """未来现金流预测（三档）。

    returns:
      available / reason：样本不足时 available=false 并给原因
      monthly：历史逐月 收入 / 支出 / 净额
      stats：月净流入的 P20 / 中位数 / P80、均值、标准差
      scenarios：pessimistic / base / optimistic，各含逐月余额与期末余额
      excluded_large：被剔除的一次性大额
    """
    today = as_of or datetime.now().astimezone().date()
    start = today - timedelta(days=lookback_months * 31)
    monthly: dict[str, dict[str, float]] = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    large: list[dict[str, Any]] = []

    for t in transactions:
        d = _parse_date(t.get("date"))
        if d is None or d < start or d > today:
            continue
        amount = float(t.get("amount") or 0)
        key = _month_key(d)
        if amount > 0:
            monthly[key]["income"] += amount
        else:
            monthly[key]["expense"] += -amount
        if abs(amount) >= large_amount_threshold:
            large.append(
                {"date": d.isoformat(), "item": str(t.get("item") or ""), "amount": round(amount, 2)}
            )

    months = _month_range(start, today)
    series = []
    for key in months:
        row = monthly.get(key, {"income": 0.0, "expense": 0.0})
        series.append(
            {
                "month": key,
                "income": round(row["income"], 2),
                "expense": round(row["expense"], 2),
                "net": round(row["income"] - row["expense"], 2),
            }
        )

    # 只用「有流水」的月份做分布，空月会人为压低净流入
    active = [m for m in series if m["income"] > 0 or m["expense"] > 0]
    if len(active) < MIN_MONTHS_FOR_FORECAST:
        return {
            "available": False,
            "reason": f"有流水的月份不足 {MIN_MONTHS_FOR_FORECAST} 个，无法预测",
            "monthly": series,
            "excluded_large": large,
        }

    nets = [m["net"] for m in active]
    p20 = round(_quantile(nets, 0.2), 2)
    p50 = round(statistics.median(nets), 2)
    p80 = round(_quantile(nets, 0.8), 2)
    mean = round(statistics.fmean(nets), 2)
    stdev = round(statistics.pstdev(nets), 2) if len(nets) > 1 else 0.0

    horizon = max(1, min(int(months_ahead), 12))
    scenarios: dict[str, Any] = {}
    for name, per_month in (("pessimistic", p20), ("base", p50), ("optimistic", p80)):
        balance = opening_balance
        rows = []
        for i in range(1, horizon + 1):
            balance = round(balance + per_month, 2)
            rows.append({"offset_month": i, "month_net": per_month, "balance": balance})
        scenarios[name] = {
            "monthly_net": per_month,
            "rows": rows,
            "ending_balance": balance,
            "goes_negative": any(r["balance"] < 0 for r in rows),
        }

    warnings: list[str] = []
    if scenarios["pessimistic"]["goes_negative"]:
        warnings.append("按悲观档（P20）测算，未来期间余额会转负，建议先补充应急金或压缩支出")
    if stdev > abs(mean) and stdev > 0:
        warnings.append(f"月净流入波动较大（标准差 {stdev:,.0f}），预测区间宽，不宜当作确定性结论")

    return {
        "available": True,
        "basis": f"基于最近 {len(active)} 个有流水月份的净流入分布外推",
        "opening_balance": round(opening_balance, 2),
        "monthly": series,
        "stats": {
            "active_months": len(active),
            "p20": p20,
            "median": p50,
            "p80": p80,
            "mean": mean,
            "stdev": stdev,
        },
        "scenarios": scenarios,
        "excluded_large": large,
        "warnings": warnings,
        "disclaimer": "预测是对历史分布的外推，不含未发生的收入变化与突发支出。",
    }
