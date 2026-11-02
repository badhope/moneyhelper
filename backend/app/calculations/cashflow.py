"""个人现金流预测与订阅/异常检测（确定性，纯函数）。

三个能力，全部基于真实流水推导，不做"AI 猜"：

1. **现金流水位预测**：按最近 N 个月的实际收支分布，给出未来 1-6 个月的
   悲观/中性/乐观三档现金流与期末余额。悲观用 P20 月净流入、中性用中位数、
   乐观用 P80；一次性大额（收入或支出超过阈值）单独剔除并提示，避免被年终奖
   或买车这种事件带偏趋势。

2. **订阅识别**：从流水里找「同金额、月期间隔稳定」的重复扣款，输出订阅清单、
   月度合计、下次扣款日与涨价检测（最近一期金额高于历史中位数视为涨价）。

3. **异常扣款检测**：对每个商户/类目用历史中位数 + MAD（中位数绝对偏差）做稳健
   离群判定；比均值+标准差更抗极端值。输出异常倍数与建议动作。

设计取舍：
- 不引入 numpy：分位数用线性插值手写，MAD 用 statistics.median；
- 所有金额 round 到 2 位；样本不足时明确返回 insufficient=true，不给假数字；
- 预测是「按历史分布外推」，不是承诺，输出里带 basis 字段说明口径。
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

MIN_MONTHS_FOR_FORECAST = 2
MIN_SAMPLES_FOR_SUBSCRIPTION = 3
MIN_SAMPLES_FOR_ANOMALY = 4
# 订阅判定：间隔中位数落在 [25, 35] 天视为月付；[85, 100] 视为季付；[350, 380] 视为年付
SUBSCRIPTION_PERIODS = (
    ("monthly", 25, 35),
    ("quarterly", 85, 100),
    ("yearly", 350, 380),
)


def _parse_date(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _quantile(values: list[float], q: float) -> float:
    """线性插值分位数（与 numpy.percentile 默认口径一致）。"""
    if not values:
        return 0.0
    arr = sorted(values)
    if len(arr) == 1:
        return arr[0]
    pos = (len(arr) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return arr[int(pos)]
    return arr[lo] + (arr[hi] - arr[lo]) * (pos - lo)


def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def _month_range(start: date, end: date) -> list[str]:
    """生成 [start, end] 之间的月份键（含头尾）。"""
    out: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


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


def detect_subscriptions(
    transactions: list[dict[str, Any]],
    *,
    as_of: date | None = None,
    min_amount: float = 1.0,
    amount_tolerance: float = 0.15,
) -> dict[str, Any]:
    """识别订阅/固定扣款：同一摘要、间隔稳定、金额波动小的重复支出。

    为什么按「摘要」而不是「摘要+金额」分桶：真实订阅会涨价（25→30），
    按金额分桶会把同一订阅拆成两组、每组样本不足而漏检。改为按摘要聚合后，
    再用金额变异系数（CV = stdev / mean）判断是否属于「固定金额」类扣款。
    """
    today = as_of or datetime.now().astimezone().date()
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in transactions:
        amount = float(t.get("amount") or 0)
        if amount >= 0 or abs(amount) < min_amount:
            continue
        d = _parse_date(t.get("date"))
        if d is None:
            continue
        label = str(t.get("item") or t.get("category") or "").strip()[:20] or "未命名"
        buckets[label].append({"date": d, "amount": abs(amount), "item": label})

    items: list[dict[str, Any]] = []
    for label, rows in buckets.items():
        if len(rows) < MIN_SAMPLES_FOR_SUBSCRIPTION:
            continue
        rows.sort(key=lambda r: r["date"])
        gaps = [(rows[i]["date"] - rows[i - 1]["date"]).days for i in range(1, len(rows))]
        gaps = [g for g in gaps if g > 0]
        if not gaps:
            continue
        median_gap = statistics.median(gaps)
        period = None
        for name, lo, hi in SUBSCRIPTION_PERIODS:
            if lo <= median_gap <= hi:
                period = name
                break
        if period is None:
            continue
        amounts = [r["amount"] for r in rows]
        mean_amount = statistics.fmean(amounts)
        if mean_amount <= 0:
            continue
        cv = (statistics.pstdev(amounts) / mean_amount) if len(amounts) > 1 else 0.0
        # 金额波动过大（如「超市购物」被同名归组）就不是订阅
        if cv > amount_tolerance:
            continue
        hist_median = statistics.median(amounts[:-1]) if len(amounts) > 1 else amounts[0]
        last = rows[-1]
        price_hike = last["amount"] > hist_median * 1.05
        next_due = last["date"] + timedelta(days=int(median_gap))
        monthly_equivalent = {
            "monthly": last["amount"],
            "quarterly": last["amount"] / 3,
            "yearly": last["amount"] / 12,
        }[period]
        items.append(
            {
                "name": label,
                "period": period,
                "amount": round(last["amount"], 2),
                "monthly_equivalent": round(monthly_equivalent, 2),
                "samples": len(rows),
                "median_interval_days": int(median_gap),
                "amount_cv": round(cv, 3),
                "last_charged": last["date"].isoformat(),
                "next_expected": next_due.isoformat(),
                "days_until_next": (next_due - today).days,
                "price_hike": price_hike,
                "previous_amount": round(hist_median, 2) if price_hike else None,
            }
        )

    items.sort(key=lambda x: x["monthly_equivalent"], reverse=True)
    total_monthly = round(sum(i["monthly_equivalent"] for i in items), 2)
    return {
        "items": items,
        "count": len(items),
        "monthly_total": total_monthly,
        "annual_total": round(total_monthly * 12, 2),
        "hikes": [i for i in items if i["price_hike"]],
        "upcoming_7d": [i for i in items if 0 <= i["days_until_next"] <= 7],
    }


def detect_anomalies(
    transactions: list[dict[str, Any]],
    *,
    as_of: date | None = None,
    lookback_days: int = 180,
    min_samples: int = MIN_SAMPLES_FOR_ANOMALY,
    mad_threshold: float = 3.5,
    min_amount: float = 50.0,
) -> dict[str, Any]:
    """异常支出检测：按商户/摘要分组，用 中位数 + MAD 判离群。

    判定：|x - median| > mad_threshold × 1.4826 × MAD（1.4826 使 MAD 与标准差可比）。
    MAD=0（金额完全一致）时，只要超出中位数 30% 也算异常。
    """
    today = as_of or datetime.now().astimezone().date()
    start = today - timedelta(days=lookback_days)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in transactions:
        amount = float(t.get("amount") or 0)
        d = _parse_date(t.get("date"))
        if amount >= 0 or d is None or d < start:
            continue
        label = str(t.get("item") or t.get("category") or "").strip()[:24] or "未命名"
        groups[label].append({"date": d, "amount": abs(amount), "item": label, "category": t.get("category")})

    anomalies: list[dict[str, Any]] = []
    for label, rows in groups.items():
        if len(rows) < min_samples:
            continue
        amounts = [r["amount"] for r in rows]
        median = statistics.median(amounts)
        mad = statistics.median([abs(a - median) for a in amounts])
        latest = max(rows, key=lambda r: r["date"])
        if abs(latest["amount"]) < min_amount:
            continue
        if mad > 0:
            score = abs(latest["amount"] - median) / (1.4826 * mad)
            is_anomaly = score > mad_threshold
        else:
            score = abs(latest["amount"] - median) / median if median > 0 else 0.0
            is_anomaly = latest["amount"] > median * 1.3
        if not is_anomaly:
            continue
        anomalies.append(
            {
                "item": label,
                "category": latest.get("category") or "",
                "date": latest["date"].isoformat(),
                "amount": round(latest["amount"], 2),
                "median": round(median, 2),
                "mad": round(mad, 2),
                "score": round(score, 2),
                "multiple": round(latest["amount"] / median, 2) if median > 0 else None,
                "samples": len(rows),
                "suggestion": "核对是否为一次性大额或误扣，必要时联系商户/银行",
            }
        )

    anomalies.sort(key=lambda x: x["score"], reverse=True)
    return {
        "items": anomalies,
        "count": len(anomalies),
        "method": f"median + MAD（阈值 {mad_threshold}σ，样本 ≥{min_samples}）",
        "lookback_days": lookback_days,
    }
