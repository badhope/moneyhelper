"""团队模拟盘工具（从 tools.py 拆出）：开户、下单、总览排行。

下单会真扣费并写快照，但只作用于模拟盘账户，不碰真实账本。
"""

from __future__ import annotations

import json
from typing import Any

from . import db
from .calculations import estimate, fee_for, ranking, team_summary, validate_trade


async def tool_paper_open(args: dict[str, Any]) -> str:
    """团队模拟盘开户：为成员创建虚拟账户（独立初始资金）。"""
    try:
        acc = await db.open_account(
            str(args.get("name") or "模拟账户"),
            float(args.get("initial_cash") or 100000),
        )
    except ValueError as e:
        return f"开户失败：{e}"
    return json.dumps(
        {
            "ok": True,
            "account_id": acc["account_id"],
            "name": acc["name"],
            "initial_cash": acc["initial_cash"],
            "hint": "用 paper_trade 开始交易（买入需 100 股整手）",
        },
        ensure_ascii=False,
    )
async def tool_paper_trade(args: dict[str, Any]) -> str:
    """团队模拟盘下单：买入/卖出，自动扣费、更新净值与排行。"""
    account_id = str(args.get("account_id") or "").strip()
    if not account_id:
        return "缺少 account_id 参数"
    acc = await db.get_account(account_id)
    if not acc:
        return f"账户 {account_id} 不存在（可用 paper_overview 查看账户列表）"
    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol.isdigit() or len(symbol) != 6:
        return "symbol 必须是 6 位 A 股代码"
    side = str(args.get("side") or "").strip()
    try:
        price = float(args.get("price") or 0)
        shares = float(args.get("shares") or 0)
    except (TypeError, ValueError):
        return "price/shares 非法"
    trades = await db.get_trades(account_id)
    err = validate_trade(acc["initial_cash"], trades, side, symbol, price, shares)
    if err:
        return f"下单被拒：{err}"
    amount = price * shares
    fee = fee_for(side, amount)
    await db.add_trade(
        account_id,
        {"symbol": symbol, "name": "", "side": side, "price": price, "shares": shares, "fee": fee},
    )
    est = estimate(acc["initial_cash"], await db.get_trades(account_id))
    await db.save_snapshot(account_id, est["equity"], est["cash"], est["market_value"])
    return json.dumps(
        {
            "ok": True,
            "account_id": account_id,
            "symbol": symbol,
            "side": side,
            "price": price,
            "shares": shares,
            "fee": fee,
            "equity": est["equity"],
            "cash": est["cash"],
            "return_pct": est["return_pct"],
            "holdings": est["holdings"][:8],
            "disclaimer": "模拟盘数据不构成投资建议。",
        },
        ensure_ascii=False,
    )
async def tool_paper_overview(_args: dict[str, Any]) -> str:
    """团队模拟盘总览：账户排行（收益率）、团队汇总、各账户持仓摘要。"""
    accounts = await db.list_accounts()
    if not accounts:
        return json.dumps(
            {"empty": True, "hint": "还没有模拟账户，可用 paper_open 开户"},
            ensure_ascii=False,
        )
    enriched = []
    for acc in accounts:
        trades = await db.get_trades(acc["account_id"])
        est = estimate(acc["initial_cash"], trades)
        enriched.append(
            {
                "account_id": acc["account_id"],
                "name": acc["name"],
                "initial_cash": acc["initial_cash"],
                "trade_count": len(trades),
                "equity": est["equity"],
                "return_pct": est["return_pct"],
                "total_pnl": est["total_pnl"],
                "position_count": est["position_count"],
                "top_holdings": [h["symbol"] for h in est["holdings"][:3]],
            }
        )
    ranked = ranking(enriched)
    return json.dumps(
        {
            "ranking": ranked,
            "summary": team_summary(ranked),
            "valuation_source": "last_trade",
            "disclaimer": "模拟盘数据不构成投资建议。",
        },
        ensure_ascii=False,
    )
