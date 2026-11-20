"""再平衡转委托：卖出先腾资金、买入整手取整、不足额明确告知。"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from .pretrade_limits import A_SHARE_LOT


def daily_order_amount(orders: list[dict[str, Any]], today: date | None = None) -> float:
    """统计当日已委托金额（用于限额）。orders 需含 ts 与 price/shares。"""
    target = today or datetime.now().astimezone().date()
    total = 0.0
    for o in orders:
        try:
            ts = o.get("ts")
            when = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
        except (TypeError, ValueError):
            continue
        if when.date() != target:
            continue
        total += float(o.get("price") or 0) * float(o.get("shares") or 0)
    return round(total, 2)


def rebalance_orders(
    *,
    plan_items: list[dict[str, Any]],
    available_cash: float,
    min_order_amount: float = 1_000.0,
    lot: int = A_SHARE_LOT,
) -> dict[str, Any]:
    """把再平衡清单转成可执行委托：整手取整、按金额排序、资金不足时给出缺口。

    plan_items: [{symbol, name, action(buy/sell/hold), amount, price}]（来自 compute_rebalance）
    先卖后买：卖出腾出的资金可用于买入（A 股 T+1 下当日卖出资金可用，这里按"可用"处理）。
    """
    sells: list[dict[str, Any]] = []
    buys: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in plan_items:
        action = str(item.get("action") or "").lower()
        price = float(item.get("price") or 0)
        amount = abs(float(item.get("amount") or 0))
        symbol = str(item.get("symbol") or "")
        name = str(item.get("name") or "")
        if action not in ("buy", "sell") or price <= 0 or amount < min_order_amount:
            continue
        if action == "buy":
            # 买入必须整手：不足一手无法成交，要明确告知而不是静默丢弃
            shares = math.floor(amount / price / lot) * lot
            if shares <= 0:
                need = round(price * lot, 2)
                skipped.append(
                    {
                        "symbol": symbol,
                        "name": name,
                        "side": "buy",
                        "price": round(price, 4),
                        "shares": 0,
                        "amount": round(amount, 2),
                        "reason": f"不足一手（1 手 {lot} 股需 {need:,.2f}，计划仅 {amount:,.2f}）",
                    }
                )
                continue
        else:
            # 卖出可零股，但股数必须是整数（A 股最小交易单位 1 股）
            shares = float(math.floor(amount / price))
            if shares <= 0:
                skipped.append(
                    {
                        "symbol": symbol,
                        "name": name,
                        "side": "sell",
                        "price": round(price, 4),
                        "shares": 0,
                        "amount": round(amount, 2),
                        "reason": "计划金额不足 1 股",
                    }
                )
                continue
        order = {
            "symbol": symbol,
            "name": name,
            "side": action,
            "price": round(price, 4),
            "shares": shares,
            "amount": round(price * shares, 2),
        }
        (sells if action == "sell" else buys).append(order)

    sells.sort(key=lambda x: x["amount"], reverse=True)
    buys.sort(key=lambda x: x["amount"], reverse=True)

    cash = available_cash + sum(o["amount"] for o in sells)
    funded: list[dict[str, Any]] = []
    for order in buys:
        if order["amount"] <= cash + 1e-9:
            cash = round(cash - order["amount"], 2)
            funded.append(order)
        else:
            skipped.append({**order, "reason": f"资金不足（需 {order['amount']:,.2f}，可用 {cash:,.2f}）"})

    return {
        "sells": sells,
        "buys": funded,
        "skipped": skipped,
        "orders": sells + funded,
        "cash_after": round(cash, 2),
        "note": "买入按整手取整；卖出按金额折算可零股；实盘需在券商页面逐笔确认。",
    }
