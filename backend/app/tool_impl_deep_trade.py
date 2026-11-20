"""深化工具·交易与单据域：下单前风控、券商持仓导入、发票解析、条件单。"""

from __future__ import annotations

import json
from typing import Any

from . import db


async def tool_pretrade_check(args: dict[str, Any]) -> str:
    """下单前风控：涨跌停/整手/T+1/集中度/日限额/重复单，全通过才放行。"""
    from .calculations import fee_for, pre_trade_check
    from .connect import quote_tencent, store

    symbol = str(args.get("symbol") or "").strip().upper()
    side = str(args.get("side") or "").lower()
    price = float(args.get("price") or 0)
    shares = float(args.get("shares") or 0)

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
    intents = await store.list_intents(limit=200)
    out = pre_trade_check(
        symbol=symbol,
        side=side,
        price=price,
        shares=shares,
        cash=cash,
        holdings=holdings,
        last_price=float(q["price"]) if q else None,
        prev_close=float(q["prev_close"]) if q and q.get("prev_close") else None,
        portfolio_value=total_value,
        position_value=round(holdings.get(symbol, 0.0) * float(q["price"]), 2) if q else 0.0,
        daily_used_amount=sum(float(i["price"]) * float(i["shares"]) for i in intents),
        daily_limit=float(settings.get("daily_limit") or 200000),
        recent_orders=[
            {
                "ts": i["created_at"],
                "symbol": i["symbol"],
                "side": i["side"],
                "price": i["price"],
                "shares": i["shares"],
            }
            for i in intents
        ],
        fee=fee_for(side, price * shares) if price > 0 and shares > 0 else 0.0,
        deviation_pct=float(settings.get("deviation_pct") or 3.0),
        concentration_pct=float(settings.get("concentration_pct") or 30.0),
    )
    return json.dumps(out, ensure_ascii=False, default=str)


async def tool_import_brokerage_holdings(args: dict[str, Any]) -> str:
    """导入券商持仓对账单：解析 CSV，可选直接合并进持仓。"""
    from .import_parsers.broker_holdings import parse_holdings

    content = str(args.get("content") or "")
    if not content.strip():
        return "需要提供券商导出的持仓 CSV 全文（content）"
    result = parse_holdings(content)
    preview = result.to_preview()
    if not args.get("apply"):
        return json.dumps({"preview": preview, "applied": 0}, ensure_ascii=False, default=str)

    applied = 0
    errors: list[str] = []
    for p in result.positions:
        try:
            await db.add_position(
                {
                    "symbol": p.symbol,
                    "name": p.name,
                    "kind": p.kind,
                    "industry": "未分类",
                    "shares": p.shares,
                    "cost": p.cost,
                    "last": p.last,
                }
            )
            applied += 1
        except Exception as exc:  # noqa: BLE001 — 单行失败不阻断整批
            errors.append(f"{p.symbol}: {exc}")
    return json.dumps(
        {"preview": preview, "applied": applied, "errors": errors}, ensure_ascii=False, default=str
    )


async def tool_parse_invoice(args: dict[str, Any]) -> str:
    """解析发票票面文本并归档：提取代码/号码/日期/金额/购销方。"""
    from .import_parsers.invoice import parse_invoice_text

    text = str(args.get("text") or "")
    if not text.strip():
        return "需要提供发票票面文本（text）"
    parsed = parse_invoice_text(text)
    record = await db.save_invoice(
        file_name=str(args.get("file_name") or "invoice-text"),
        raw=text.encode("utf-8"),
        parsed=parsed.to_dict(),
    )
    return json.dumps(
        {
            "parsed": parsed.to_dict(),
            "invoice_id": record.get("id"),
            "duplicate": record.get("duplicate"),
        },
        ensure_ascii=False,
        default=str,
    )


async def tool_market_breadth(_args: dict[str, Any]) -> str:
    """市场温度：涨跌家数、涨跌停数、情绪温度与冷热判断。"""
    from .connect import quote_tencent

    return json.dumps(await quote_tencent.market_breadth(), ensure_ascii=False, default=str)


async def tool_stock_profile(args: dict[str, Any]) -> str:
    """个股档案：价格、PE/PB、总/流通市值、换手、量比、振幅、涨跌停价。"""
    from .connect import quote_tencent

    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol:
        return "需要提供 6 位证券代码"
    out = await quote_tencent.profile(symbol)
    if out is None:
        return f"无法获取 {symbol} 的档案（可能不是 A 股/ETF，或行情源不可用）"
    return json.dumps(out, ensure_ascii=False, default=str)


async def tool_conditional_order(args: dict[str, Any]) -> str:
    """创建条件单：价格/涨跌幅触发后生成待确认意图（不直接下单）。"""
    try:
        out = await db.create_conditional(args or {})
    except ValueError as exc:
        return f"创建条件单失败：{exc}"
    return json.dumps(
        {"ok": True, "conditional": out, "hint": "系统按行情检查触发，命中后生成待确认交易意图"},
        ensure_ascii=False,
        default=str,
    )
