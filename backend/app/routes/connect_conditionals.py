"""连接中心·条件单：创建、取消、删除与批量评估。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..auth import get_current_user
from ..connect import quote_tencent, store
from ._responses import bad as _bad

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.get("/api/connect/conditionals")
async def list_conditionals(status: str = "") -> dict[str, Any]:
    return {"items": await db.list_conditionals(status)}


@router.post("/api/connect/conditionals")
async def create_conditional(payload: dict[str, Any]) -> Any:
    try:
        return await db.create_conditional(payload or {})
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/connect/conditionals/{cid}/cancel")
async def cancel_conditional(cid: str) -> Any:
    try:
        return await db.update_conditional_status(cid, "cancelled")
    except ValueError as exc:
        return _bad(str(exc), 404)


@router.delete("/api/connect/conditionals/{cid}")
async def delete_conditional(cid: str) -> dict[str, Any]:
    ok = await db.delete_conditional(cid)
    if not ok:
        raise HTTPException(404, "条件单不存在")
    return {"deleted": cid}


@router.post("/api/connect/conditionals/evaluate")
async def evaluate_conditionals() -> dict[str, Any]:
    """检查所有观察中的条件单：命中则生成待确认交易意图（不直接下单）。"""
    watching = await db.list_conditionals("watching")
    if not watching:
        return {"checked": 0, "triggered": [], "message": "没有观察中的条件单"}
    symbols = sorted({str(c["symbol"]) for c in watching})
    quotes = await quote_tencent.quotes_batch(symbols)
    triggered = []
    for c in watching:
        q = quotes.get(str(c["symbol"]).upper())
        if not q:
            continue
        price = float(q["price"])
        prev = float(q.get("prev_close") or 0)
        change_pct = (price / prev - 1) * 100 if prev > 0 else 0.0
        tv = float(c["trigger_value"])
        ttype = str(c["trigger_type"])
        hit = (
            (ttype == "price_below" and price <= tv)
            or (ttype == "price_above" and price >= tv)
            or (ttype == "pct_change_below" and change_pct <= tv)
            or (ttype == "pct_change_above" and change_pct >= tv)
        )
        if not hit:
            continue
        intent = await store.create_intent(
            {
                "symbol": c["symbol"],
                "name": c["name"],
                "side": c["side"],
                "price": c["price"],
                "shares": c["shares"],
                "mode": c["mode"],
                "note": f"条件单触发（{ttype} {tv}，当前 {price}）",
            }
        )
        updated = await db.update_conditional_status(c["id"], "triggered")
        triggered.append({"conditional": updated, "intent": intent, "market_price": price})
    return {"checked": len(watching), "triggered": triggered, "quotes_available": len(quotes)}




# ---------------------------------------------------------------------------
# v4.6：发票图片（二维码 + OCR）/ PDF 对账单 / 账单归类规则
# ---------------------------------------------------------------------------


