"""连接中心·行情与风控：市场温度、个股档案/分时/K 线备源、预交易风控与再平衡。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from .. import db
from ..auth import get_current_user
from ..calculations import (
    daily_order_amount,
    fee_for,
    pre_trade_check,
    rebalance_orders,
)
from ..connect import quote_tencent, store
from ._responses import bad as _bad

router = APIRouter(dependencies=[Depends(get_current_user)])



@router.get("/api/connect/market/breadth")
async def market_breadth() -> dict[str, Any]:
    """市场温度：涨跌家数、涨跌停数、情绪温度 0-100。"""
    return await quote_tencent.market_breadth()


@router.get("/api/connect/stock/{symbol}/profile")
async def stock_profile(symbol: str) -> Any:
    """个股档案：价格 + PE/PB + 市值 + 换手/量比/振幅。"""
    out = await quote_tencent.profile(symbol)
    if out is None:
        return _bad(f"无法获取 {symbol} 的档案（可能不是 A 股/ETF，或行情源不可用）", 404)
    return out


@router.get("/api/connect/stock/{symbol}/minute")
async def stock_minute(symbol: str) -> Any:
    """当日分时走势。"""
    out = await quote_tencent.minute(symbol)
    if out is None:
        return _bad(f"无法获取 {symbol} 的分时数据", 404)
    return out


@router.get("/api/connect/kline")
async def connect_kline(symbol: str, period: str = "daily", limit: int = 120) -> Any:
    """K 线（腾讯前复权，作为东财 push2his 的备源）。"""
    out = await quote_tencent.kline(symbol, period, limit)
    if out is None:
        return _bad(f"无法获取 {symbol} 的 K 线", 404)
    return out


# ---------------------------------------------------------------------------
# 预交易风控
# ---------------------------------------------------------------------------


@router.get("/api/connect/risk/settings")
async def risk_settings() -> dict[str, Any]:
    return await db.get_risk_settings()


@router.put("/api/connect/risk/settings")
async def save_risk_settings(payload: dict[str, Any]) -> Any:
    try:
        return await db.save_risk_settings(payload or {})
    except ValueError as exc:
        return _bad(str(exc))


async def _today_bought(symbol: str) -> float:
    """当日模拟盘买入股数（T+1 判定）：扫所有模拟账户当日买单。"""
    today_str = datetime.now().astimezone().strftime("%Y-%m-%d")
    total = 0.0
    for acc in await db.list_accounts():
        for t in await db.get_trades(acc["account_id"]):
            if (
                str(t.get("date", ""))[:10] == today_str
                and t.get("side") == "buy"
                and str(t.get("symbol", "")).upper() == symbol
            ):
                total += float(t.get("shares") or 0)
    return total


@router.post("/api/connect/risk/check")
async def risk_check(payload: dict[str, Any]) -> Any:
    """下单前风控检查：涨跌停 / 整手 / T+1 / 集中度 / 日限额 / 重复单。

    让「AI 想下单」这件事在执行前经过确定性闸门，而不是模型说买就买。
    """
    payload = payload or {}
    symbol = str(payload.get("symbol") or "").strip().upper()
    side = str(payload.get("side") or "").strip().lower()
    try:
        price = float(payload.get("price") or 0)
        shares = float(payload.get("shares") or 0)
    except (TypeError, ValueError):
        return _bad("价格与股数必须是数字")

    settings = await db.get_risk_settings()
    positions = await db.list_positions()
    holdings = {
        str(p["symbol"]).upper(): float(p["shares"])
        for p in positions
        if p.get("kind") != "现金"
    }
    total_value = sum(float(p.get("shares", 0)) * float(p.get("last", 0)) for p in positions)
    cash = sum(
        float(p.get("shares", 0)) * float(p.get("last", 0))
        for p in positions
        if p.get("kind") == "现金"
    )

    q = await quote_tencent.quote(symbol)
    last_price = float(q["price"]) if q else None
    prev_close = float(q["prev_close"]) if q and q.get("prev_close") else None
    position_value = 0.0
    if last_price:
        position_value = round(holdings.get(symbol, 0.0) * last_price, 2)

    intents = await store.list_intents(limit=200)
    used = daily_order_amount(
        [{"ts": i["created_at"], "price": i["price"], "shares": i["shares"]} for i in intents]
    )
    recent = [
        {
            "ts": i["created_at"],
            "symbol": i["symbol"],
            "side": i["side"],
            "price": i["price"],
            "shares": i["shares"],
        }
        for i in intents
    ]
    fee_est = fee_for(side, price * shares) if (price > 0 and shares > 0) else 0.0

    check = pre_trade_check(
        symbol=symbol,
        side=side,
        price=price,
        shares=shares,
        cash=cash,
        holdings=holdings,
        last_price=last_price,
        prev_close=prev_close,
        today_bought=await _today_bought(symbol),
        portfolio_value=total_value,
        position_value=position_value,
        daily_used_amount=used,
        daily_limit=float(settings.get("daily_limit") or 200000),
        recent_orders=recent,
        fee=fee_est,
        deviation_pct=float(settings.get("deviation_pct") or 3.0),
        concentration_pct=float(settings.get("concentration_pct") or 30.0),
    )
    check["quote"] = {"price": last_price, "prev_close": prev_close, "name": (q or {}).get("name", "")}
    check["available_cash"] = round(cash, 2)
    check["portfolio_value"] = round(total_value, 2)
    check["daily_used"] = used
    return check


@router.post("/api/connect/rebalance/orders")
async def rebalance_orders_api(payload: dict[str, Any]) -> Any:
    """把再平衡清单转成可执行委托（整手取整、先卖后买、资金不足列出缺口）。"""
    items = (payload or {}).get("items")
    if not isinstance(items, list) or not items:
        from ..calculations import compute_rebalance

        targets = await db.list_allocation_targets()
        if not targets:
            return _bad("未提供调仓清单，且尚未设置目标配置", 400)
        positions = await db.list_positions()
        prices = {str(p["symbol"]): float(p.get("last") or 0) for p in positions}
        holdings = [
            {
                "symbol": str(p["symbol"]),
                "name": str(p.get("name") or ""),
                "shares": float(p.get("shares") or 0),
                "last": float(p.get("last") or 0),
            }
            for p in positions
        ]
        plan = compute_rebalance(holdings, targets, prices)
        items = plan.get("items", [])
    return rebalance_orders(
        plan_items=items,
        available_cash=float((payload or {}).get("available_cash") or 0),
        min_order_amount=float((payload or {}).get("min_order_amount") or 1000),
    )


# ---------------------------------------------------------------------------
# 券商持仓对账导入
# ---------------------------------------------------------------------------


