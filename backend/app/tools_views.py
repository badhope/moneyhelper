"""只读视图类工具（从 tools.py 拆出）：持仓/账本/风控/预算/趋势/K线/目标。

返回的都是压缩后的摘要，明细留在前端；记账入口 record_transaction 也在这里。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from . import analysis, db, nlparse
from .provenance import record_provenance
from .quotes import kline as fetch_kline


def _compact_market(market: dict[str, Any]) -> dict[str, Any]:
    """market_view 结果压成给模型的摘要：总额 + 前 5 持仓 + 集中度告警。"""
    return {
        "total_market_value": market["total_market_value"],
        "total_cost": market["total_cost"],
        "total_pnl": market["total_pnl"],
        "total_pnl_pct": market["total_pnl_pct"],
        "top_positions": [
            {
                "name": p["name"],
                "symbol": p["symbol"],
                "market_value": p["market_value"],
                "pnl": p["pnl"],
                "pnl_pct": p["pnl_pct"],
            }
            for p in market["positions"][:5]
        ],
        "concentration_warnings": [
            a["name"] for a in market["concentration"]["asset_breaches"]
        ],
    }
def _compact_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    return {
        "month": ledger["month"],
        "income": ledger["income"],
        "expense": ledger["expense"],
        "net": ledger["net"],
        "savings_rate": ledger["savings_rate"],
        "top_categories": ledger["by_category"][:5],
        "subscription_monthly": ledger["subscription_monthly"],
        "debt_monthly": ledger["debt_monthly"],
        "dti_pct": ledger["dti_pct"],
        "emergency": ledger["emergency"],
    }
async def tool_get_market_view(_args: dict[str, Any]) -> str:
    """查持仓与行情：总市值、盈亏、集中度。无参数。"""
    positions = await db.list_positions()
    from .quotes import live_quotes

    live = await live_quotes(positions)
    if not positions:
        return json.dumps(
            {"empty": True, "hint": "还没有持仓，提示用户去添加持仓后再问"}, ensure_ascii=False
        )
    return json.dumps(_compact_market(analysis.market_view(positions, live)), ensure_ascii=False)
async def tool_get_ledger_view(_args: dict[str, Any]) -> str:
    """查账本：本月收支、结余、储蓄率、订阅、负债、应急金。无参数。"""
    settings = await db.get_settings()
    positions = await db.list_positions()
    from .quotes import live_quotes

    live = await live_quotes(positions)
    txs = await db.list_transactions()
    if not txs:
        return json.dumps(
            {"empty": True, "hint": "还没有流水，提示用户先记账再问"}, ensure_ascii=False
        )
    led = analysis.ledger_view(
        txs,
        await db.list_subscriptions(),
        await db.list_debts(),
        settings,
        positions,
        live,
    )
    return json.dumps(_compact_ledger(led), ensure_ascii=False)
async def tool_get_risk_flags(_args: dict[str, Any]) -> str:
    """查风控规则：集中度、应急金、高息负债、负债收入比、储蓄率告警。无参数。"""
    positions = await db.list_positions()
    from .quotes import live_quotes

    live = await live_quotes(positions)
    settings = await db.get_settings()
    m = analysis.market_view(positions, live)
    led = analysis.ledger_view(
        await db.list_transactions(),
        await db.list_subscriptions(),
        await db.list_debts(),
        settings,
        positions,
        live,
    )
    flags = analysis.risk_checks(m, led)
    return json.dumps(
        {"count": len(flags), "flags": [f["text"] for f in flags]},
        ensure_ascii=False,
    )
async def tool_get_budget(args: dict[str, Any]) -> str:
    """查预算：某月预算设置与实时使用率。参数：month（YYYY-MM，可省略=本月）。"""
    month = str(args.get("month") or "").strip() or datetime.now().strftime("%Y-%m")
    rows = await db.list_budgets(month)
    budgets = {
        ("总预算" if r["category"] == "__total" else r["category"]): r["amount"]
        for r in rows
    }
    spent = await db.month_expense_by_category(month)
    # 与 /api/budgets 同口径：投资/还款是储蓄与转移支付，不计入预算使用
    for cat in ("投资", "还款"):
        spent.pop(cat, None)
    total_spent = round(sum(spent.values()), 2)
    total_budget = budgets.get("总预算", 0.0)
    return json.dumps(
        {
            "month": month,
            "budgets": budgets,
            "spent_by_category": spent,
            "total_spent": total_spent,
            "total_budget": total_budget,
            "over": total_budget > 0 and total_spent > total_budget,
        },
        ensure_ascii=False,
    )
async def tool_get_trend(args: dict[str, Any]) -> str:
    """查收支趋势：最近 N 个月（默认 6）收入/支出/结余。参数：months（1-24）。"""
    try:
        months = max(1, min(int(args.get("months") or 6), 24))
    except (TypeError, ValueError):
        months = 6
    return json.dumps(await db.monthly_trend(months), ensure_ascii=False)
async def tool_record_transaction(args: dict[str, Any]) -> str:
    """一句话记账：把用户说的话解析为流水并入账。参数：text（一句话，含金额）。"""
    text = str(args.get("text") or "").strip()
    if not text:
        return "缺少 text 参数"
    parsed = nlparse.parse(text)
    if parsed is None:
        parsed = await nlparse.parse_with_ai(text)
    if parsed is None:
        return "无法从这句话里解析出金额，请让用户改说「昨天打车 32 元」这类格式"
    await db.add_transaction(
        parsed["date"], parsed["item"], parsed["category"], parsed["amount"]
    )
    # 异步审计
    await record_provenance(
        action="add_transaction",
        entity_type="transaction",
        entity_id=f"{parsed['date']}:{parsed['item']}:{parsed['amount']}",
        before=None,
        after=parsed,
        source="mcp",
    )
    return json.dumps(
        {
            "ok": True,
            "date": parsed["date"],
            "item": parsed["item"],
            "category": parsed["category"],
            "amount": parsed["amount"],
        },
        ensure_ascii=False,
    )
async def tool_get_kline(args: dict[str, Any]) -> str:
    """查某标的的 K 线走势。参数：symbol（6 位代码），period（daily/weekly/monthly，默认 daily），limit（默认 60）。"""
    symbol = str(args.get("symbol") or "").strip()
    if not symbol:
        return "缺少 symbol 参数"
    period = str(args.get("period") or "daily").strip()
    try:
        limit = max(10, min(int(args.get("limit") or 60), 500))
    except (TypeError, ValueError):
        limit = 60
    data = await fetch_kline(symbol, period, limit)
    if not data:
        return f"无法获取 {symbol} 的行情（可能不是 A 股/ETF 代码，或行情源不可用）"
    # 只回传近 N 个收盘价点，控制 token
    points = [
        {"date": p["date"], "close": p["close"], "pct_change": p.get("pct_change")}
        for p in data["points"][-30:]
    ]
    return json.dumps(
        {"symbol": symbol, "period": period, "source": data["source"], "points": points},
        ensure_ascii=False,
    )
async def tool_get_goals(_args: dict[str, Any]) -> str:
    """查财务目标：目标金额、已存金额、进度、距截止月、建议月存。无参数。"""
    goals = await db.list_goals()
    if not goals:
        return json.dumps(
            {"empty": True, "hint": "用户还没有设置财务目标，可提示用户到「记账 → 目标」添加"}, ensure_ascii=False
        )
    return json.dumps(analysis.goal_progress(goals), ensure_ascii=False)
