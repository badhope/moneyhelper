"""市场与账本视图：指标摘要、集中度与分月明细（只读）。

从 analysis.py 拆出。阈值常量与月份口径也放这里，体检模块复用同一份。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .numeric import to_float

CONCENTRATION_MAX_PCT = 40.0
DTI_WARN_PCT = 40.0
SAVINGS_RATE_WARN_PCT = 20.0
HIGH_RATE_DEBT = 0.08

def _month_prefix() -> str:
    return datetime.now().strftime("%Y-%m")


def market_view(
    positions: list[dict[str, Any]], live: dict[str, float]
) -> dict[str, Any]:
    """持仓明细 + 市值/盈亏 + 集中度（按标的、按行业）。"""
    rows, total_mv, total_cost = [], 0.0, 0.0
    for p in positions:
        last = live.get(p["symbol"], float(p["last"]))
        mv = p["shares"] * last
        cost = p["shares"] * p["cost"]
        total_mv += mv
        total_cost += cost
        rows.append(
            {
                "symbol": p["symbol"],
                "name": p["name"],
                "kind": p["kind"],
                "industry": p["industry"],
                "shares": p["shares"],
                "last": round(last, 4),
                # 注意：cost / market_value 都是**总额**（单价 × 股数），
                # 前端若需要单价必须读 cost_per_share，不能直接把 cost 回填到"每股成本"输入框。
                "cost": round(cost, 2),
                "cost_per_share": round(float(p["cost"]), 6),
                "market_value": round(mv, 2),
                "pnl": round(mv - cost, 2),
                "pnl_pct": round((mv - cost) / cost * 100, 2) if cost else 0.0,
            }
        )

    # 集中度分母用「非现金市值」：现金占大头时不应稀释真实投资资产占比，
    # 否则单只股票的相对集中度被低估、可能漏报超限。若无非现金资产则回退总市值。
    non_cash_mv = sum(r["market_value"] for r in rows if r["kind"] != "现金")
    concentration_denom = non_cash_mv or total_mv

    # 两个口径必须分开，否则会同时出两种错：
    # - pct：相对**总市值**，各项之和 = 100%，供资产分布饼图与持仓表使用
    # - investable_pct：相对**非现金市值**，用于集中度判定（现金不该稀释股票权重）
    # 历史 bug：现金行也拿 non_cash_mv 当分母 → 所有 pct 之和 = 126%，
    # 且现金显示 26.3%（真实应为 20.8%），前端同屏出现两个不同百分比。
    by_asset = []
    for r in rows:
        by_asset.append(
            {
                "name": r["name"],
                "kind": r["kind"],
                "pct": round(r["market_value"] / total_mv * 100, 1) if total_mv else 0.0,
                "investable_pct": round(r["market_value"] / concentration_denom * 100, 1)
                if concentration_denom
                else 0.0,
                "market_value": r["market_value"],
            }
        )
    by_asset.sort(key=lambda x: -x["pct"])

    agg: dict[str, float] = {}
    for r in rows:
        agg[r["industry"]] = agg.get(r["industry"], 0.0) + r["market_value"]
    by_industry = [
        {
            "industry": k,
            "pct": round(v / total_mv * 100, 1) if total_mv else 0.0,
            "investable_pct": round(v / concentration_denom * 100, 1) if concentration_denom else 0.0,
        }
        for k, v in sorted(agg.items(), key=lambda kv: -kv[1])
    ]

    return {
        "positions": rows,
        "total_market_value": round(total_mv, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_mv - total_cost, 2),
        "total_pnl_pct": round((total_mv - total_cost) / total_cost * 100, 2)
        if total_cost
        else 0.0,
        "concentration": {
            "threshold_pct": CONCENTRATION_MAX_PCT,
            "by_asset": by_asset,
            "by_industry": by_industry,
            "asset_breaches": [
                a
                for a in by_asset
                if a["investable_pct"] > CONCENTRATION_MAX_PCT and a["kind"] != "现金"
            ],
            "industry_breaches": [
                i
                for i in by_industry
                if i["investable_pct"] > CONCENTRATION_MAX_PCT and i["industry"] != "现金"
            ],
        },
    }


# --------------------------------------------------------------------------
# 账本视角
# --------------------------------------------------------------------------


def ledger_view(
    transactions: list[dict[str, Any]],
    subscriptions: list[dict[str, Any]],
    debts: list[dict[str, Any]],
    settings: dict[str, str],
    positions: list[dict[str, Any]],
    live: dict[str, float],
) -> dict[str, Any]:
    """本月现金流 + 订阅 + 负债 + 应急金。所有"本月"口径都按 date 前缀过滤。"""
    month = _month_prefix()
    txs = [t for t in transactions if str(t.get("date", "")).startswith(month)]

    income = sum(t["amount"] for t in txs if t["amount"] > 0)
    expense = sum(-t["amount"] for t in txs if t["amount"] < 0)
    by_cat: dict[str, float] = {}
    for t in txs:
        if t["amount"] < 0:
            by_cat[t["category"]] = by_cat.get(t["category"], 0.0) + -t["amount"]
    ranked = sorted(by_cat.items(), key=lambda kv: -kv[1])

    subs_total = sum(s["monthly"] for s in subscriptions)
    income_num = _num(settings.get("monthly_income"))
    debt_monthly = sum(d["monthly"] for d in debts)
    dti = round(debt_monthly / income_num * 100, 1) if income_num else 0.0

    cash = sum(
        p["shares"] * live.get(p["symbol"], float(p["last"]))
        for p in positions
        if p["kind"] == "现金"
    )
    cats = [
        c.strip()
        for c in settings.get("essential_categories", "居住,餐饮,交通").split(",")
        if c.strip()
    ]
    essential = sum(
        -t["amount"] for t in txs if t["amount"] < 0 and t["category"] in cats
    )
    target = _num(settings.get("emergency_target_months"))
    has_data = essential > 0
    months = round(cash / essential, 1) if essential else 0.0

    return {
        "month": month,
        "income": round(income, 2),
        "expense": round(expense, 2),
        "net": round(income - expense, 2),
        "savings_rate": round((income - expense) / income * 100, 1) if income else 0.0,
        "by_category": [{"category": k, "amount": round(v, 2)} for k, v in ranked[:6]],
        "subscription_monthly": round(subs_total, 2),
        "subscription_annual": round(subs_total * 12, 2),
        "debt_monthly": round(debt_monthly, 2),
        "debt_count": len(debts),
        "dti_pct": dti,
        "high_rate_debts": [d for d in debts if d["rate"] >= HIGH_RATE_DEBT],
        "emergency": {
            "cash": round(cash, 2),
            "essential_monthly": round(essential, 2),
            "essential_categories": cats,
            "months_covered": months,
            "target_months": target,
            "has_data": has_data,
            "ok": (months >= target if target else True) if has_data else True,
        },
    }


_num = to_float
