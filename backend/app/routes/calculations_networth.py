"""净值路由：当前净值与历史净值序列。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import db
from ..auth import get_current_user
from ..calculations import calculate_net_worth

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/api/calculations/net-worth")
async def net_worth_endpoint() -> dict[str, Any]:
    """当前净值 + 组成明细。

    净值必须与总览用同一份价格：原来这里直接读 positions[].last（快照价），
    而 /api/dashboard 用实时行情，同一屏出现「总资产 282,540」与「264,884」两个数。
    现在先取实时价（失败自动退回快照），两处口径一致。
    """
    from .. import quotes

    positions = await db.list_positions()
    debts = await db.list_debts()
    subs = await db.list_subscriptions()

    try:
        live = await quotes.live_quotes(positions)
    except Exception:  # noqa: BLE001 — 行情失败退回快照价，接口不能因此 500
        live = {}
    priced = [
        {**p, "last": float(live.get(p["symbol"], p.get("last", 0)))}
        for p in positions
    ]
    snapshot = calculate_net_worth(priced, debts=debts, subscriptions=subs)

    # 负债利率附加字段：前端负债明细展示用，键与 liability_breakdown 一致
    liability_rates = {
        (d.get("name") or "未知负债"): float(d.get("rate", 0) or 0) for d in debts
    }

    return {
        "date": snapshot.date.isoformat(),
        "total_assets": snapshot.total_assets,
        "total_liabilities": snapshot.total_liabilities,
        "net_worth": snapshot.net_worth,
        "asset_breakdown": snapshot.asset_breakdown,
        "liability_breakdown": snapshot.liability_breakdown,
        "liability_rates": liability_rates,
        "quote_source": quotes.last_source(),
    }
