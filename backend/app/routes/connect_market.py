"""公开行情：基金净值/历史、涨跌榜、指数快照。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..connect import marketdata
from ._responses import bad as _bad

router = APIRouter(dependencies=[Depends(get_current_user)])

# 公开行情
# ---------------------------------------------------------------------------


@router.get("/api/connect/fund/nav")
async def fund_nav(codes: str = "") -> dict[str, Any]:
    return await marketdata.fund_nav([c for c in codes.replace("，", ",").split(",") if c.strip()])


@router.get("/api/connect/fund/history")
async def fund_history(code: str, limit: int = 60) -> Any:
    out = await marketdata.fund_history(code, limit)
    if out is None:
        return _bad(f"无法获取基金 {code} 的历史净值", 404)
    return out


@router.get("/api/connect/movers")
async def movers(kind: str = "gainers", limit: int = 20) -> dict[str, Any]:
    return await marketdata.market_movers(kind, limit)


@router.get("/api/connect/indices")
async def indices() -> dict[str, Any]:
    """四大指数快照（新浪源；东财 push2 在部分网络下不可达时的稳定替代）。"""
    return await marketdata.index_snapshot()


# ---------------------------------------------------------------------------
