"""持仓路由：增删改、同名合并、追加累加（成本加权）。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import analysis, db
from ..quotes import invalidate_quotes_cache

router = APIRouter()

@router.post("/api/positions")
async def create_position(payload: dict) -> dict:
    try:
        out = await db.add_position(payload or {})
    except Exception as exc:  # noqa: BLE001 — 坏输入回 400
        return JSONResponse({"error": str(exc)}, status_code=400)
    await invalidate_quotes_cache()
    analysis.invalidate_dashboard_cache()
    return out


@router.delete("/api/positions/{symbol}")
async def remove_position(symbol: str) -> dict:
    out = await db.delete_position(symbol)
    await invalidate_quotes_cache()
    analysis.invalidate_dashboard_cache()
    return out


@router.put("/api/positions/{symbol}")
async def update_position(symbol: str, payload: dict) -> dict:
    try:
        out = await db.update_position(payload or {}, symbol)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    await invalidate_quotes_cache()
    analysis.invalidate_dashboard_cache()
    return out


@router.post("/api/positions/merge")
async def merge_positions(payload: dict) -> dict:
    name = str((payload or {}).get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name 必填：要合并的持仓名称"}, status_code=400)
    try:
        out = await db.merge_positions_by_name(name)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    await invalidate_quotes_cache()
    analysis.invalidate_dashboard_cache()
    return out


@router.post("/api/positions/{symbol}/append")
async def append_position(symbol: str, payload: dict) -> dict:
    """追加持仓：已有 symbol 则股数累加、成本加权平均（不覆盖），用于「合并」语义。"""
    from .. import tools as _tools

    p = payload or {}
    async with _tools._position_write_lock:
        # 加权平均成本的唯一实现在 db.append_position（REST 与 MCP 共用），
        # 这里只负责「不存在就 404」这个 REST 特有的语义。
        try:
            out = await db.append_position(
                symbol,
                float(p.get("shares") or 0),
                float(p.get("cost") or 0),
                float(p.get("last")) if p.get("last") is not None else None,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if out is None:
            return JSONResponse(
                {"error": f"持仓 {symbol} 不存在，请先添加"}, status_code=404
            )
        await invalidate_quotes_cache()
        analysis.invalidate_dashboard_cache()
        return {**out, "appended": True, "new_shares": out["shares"]}
