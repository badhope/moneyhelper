"""团队模拟盘 · 账户域：开户/删除/详情/下单/净值快照。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..auth import get_current_user
from ..calculations.paper import (
    build_equity_curve,
    estimate,
    fee_for,
    ranking,
    team_summary,
    validate_trade,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/api/paper/accounts")
async def paper_accounts() -> dict[str, Any]:
    """团队账户列表：开户信息 + 估值 + 排行 + 团队摘要。"""
    accounts = await db.list_accounts()
    enriched: list[dict[str, Any]] = []
    for acc in accounts:
        trades = await db.get_trades(acc["account_id"])
        est = estimate(acc["initial_cash"], trades)
        enriched.append(
            {
                "account_id": acc["account_id"],
                "name": acc["name"],
                "initial_cash": acc["initial_cash"],
                "created_at": acc["created_at"],
                "trade_count": len(trades),
                **est,
            }
        )
    ranked = ranking(enriched)
    return {
        "items": ranked,
        "summary": team_summary(ranked),
        "valuation_source": "last_trade",
    }


@router.post("/api/paper/accounts")
async def paper_open(payload: dict[str, Any]) -> dict[str, Any]:
    """开户：name + initial_cash。"""
    try:
        acc = await db.open_account(
            str(payload.get("name") or "模拟账户"),
            float(payload.get("initial_cash") or 100000),
        )
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"account": acc}


@router.delete("/api/paper/accounts/{aid}")
async def paper_delete(aid: str) -> dict[str, Any]:
    """删除账户（含交易与快照）。"""
    ok = await db.delete_account(aid)
    if not ok:
        raise HTTPException(status_code=404, detail="账户不存在")
    return {"deleted": aid}


@router.get("/api/paper/accounts/{aid}")
async def paper_detail(aid: str) -> dict[str, Any]:
    """账户详情：估值 + 净值曲线 + 交易记录。"""
    acc = await db.get_account(aid)
    if not acc:
        raise HTTPException(status_code=404, detail="账户不存在")
    trades = await db.get_trades(aid)
    est = estimate(acc["initial_cash"], trades)
    # 补今日快照（估值变化后）
    await db.save_snapshot(aid, est["equity"], est["cash"], est["market_value"])
    snaps = await db.list_snapshots(aid)
    curve = build_equity_curve(snaps, acc["initial_cash"])
    return {
        "account": {
            "account_id": acc["account_id"],
            "name": acc["name"],
            "initial_cash": acc["initial_cash"],
            "created_at": acc["created_at"],
            "trade_count": len(trades),
            **est,
        },
        "curve": curve,
        "trades": list(reversed(trades))[:60],  # 最新在前，最多 60 条
    }


@router.post("/api/paper/accounts/{aid}/trades")
async def paper_trade(aid: str, payload: dict[str, Any]) -> dict[str, Any]:
    """下单：symbol + side(buy/sell) + price + shares（+name 可选）。"""
    acc = await db.get_account(aid)
    if not acc:
        raise HTTPException(status_code=404, detail="账户不存在")

    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol.isdigit() or len(symbol) != 6:
        raise HTTPException(status_code=400, detail="symbol must be a 6-digit A-share code")
    side = str(payload.get("side") or "").strip()
    try:
        price = float(payload.get("price") or 0)
        shares = float(payload.get("shares") or 0)
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail="price/shares 非法") from e

    amount = price * shares
    fee = fee_for(side, amount)

    # 读-校验-写必须在同一把写锁内完成：否则两个并发买入都能通过现金校验，
    # 落库后现金为负、交易流水与估值不一致（排行榜/净值曲线全部失真）。
    # 事件溯源模型的正确用法是「持锁重放→校验→插入」，而不是先读后判。
    from ..db._core import get_write_lock

    async with get_write_lock():
        trades = await db.get_trades(aid)
        err = validate_trade(acc["initial_cash"], trades, side, symbol, price, shares)
        if err:
            raise HTTPException(status_code=400, detail=err)
        trade = await db.add_trade(
            aid,
            {
                "symbol": symbol,
                "name": str(payload.get("name") or ""),
                "side": side,
                "price": price,
                "shares": shares,
                "fee": fee,
            },
        )
        est = estimate(acc["initial_cash"], await db.get_trades(aid))
        await db.save_snapshot(aid, est["equity"], est["cash"], est["market_value"])
    return {"trade": trade, "estimate": est}


@router.post("/api/paper/accounts/{aid}/snapshot")
async def paper_snapshot(aid: str) -> dict[str, Any]:
    """手动存档净值快照（幂等：同日覆盖）。"""
    acc = await db.get_account(aid)
    if not acc:
        raise HTTPException(status_code=404, detail="账户不存在")
    trades = await db.get_trades(aid)
    est = estimate(acc["initial_cash"], trades)
    await db.save_snapshot(aid, est["equity"], est["cash"], est["market_value"])
    return {"snapshotted": True, "equity": est["equity"]}


# ---------------------------------------------------------------------------
# 回测 → 模拟盘桥接（样本外验证闭环）
# ---------------------------------------------------------------------------
