"""订阅识别与异常支出：按周期聚类 + 分位数偏离。"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from .cashflow_rules import (
    MIN_SAMPLES_FOR_ANOMALY,
    MIN_SAMPLES_FOR_SUBSCRIPTION,
    SUBSCRIPTION_PERIODS,
)
from .cashflow_util import _parse_date


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
