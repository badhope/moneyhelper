"""撤回路由：单条 / 批量 / 可撤回面板 / 按快照 id 通用撤回。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import db

router = APIRouter()

async def _resolve_usable_snapshot(entity: str, entity_id: str):
    """查最近一条 active（未被撤回）快照；没有 raises LookupError。主流程按实体类型传入对应主键值。"""
    rows = await db.list_undo_records(entity=entity, entity_id=str(entity_id), limit=1)
    if not rows:
        raise LookupError(f"no active undo snapshot for {entity}/{entity_id}")
    return rows[0]


VALID_BATCH_UNDO_ENTITIES = ("transactions", "positions", "debts", "subscriptions")


ENTITY_TO_KIND = {
    "transactions": ("transaction",),
    "positions": ("position",),
    "debts": ("debt",),
    "subscriptions": ("subscription",),
}


@router.post("/api/transactions/{tx_id}/undo")
async def undo_transaction(tx_id: int) -> dict:
    try:
        snap = await _resolve_usable_snapshot("transaction", str(tx_id))
    except LookupError:
        return JSONResponse({"error": f"流水 {tx_id} 无可撤回快照"}, status_code=404)
    res = await db._undo_apply(snap["id"])
    return {"ok": True, **res}


@router.post("/api/positions/{symbol}/undo")
async def undo_position(symbol: str) -> dict:
    try:
        snap = await _resolve_usable_snapshot("position", symbol)
    except LookupError:
        return JSONResponse({"error": f"持仓 {symbol} 无可撤回快照"}, status_code=404)
    res = await db._undo_apply(snap["id"])
    return {"ok": True, **res}


@router.post("/api/{entity:path}/batch-undo")
async def batch_undo(entity: str, payload: dict) -> dict:
    entity = (entity or "").strip().lower()
    if entity not in VALID_BATCH_UNDO_ENTITIES:
        return JSONResponse(
            {"error": f"不支持撤回的实体：{entity}，可选：{VALID_BATCH_UNDO_ENTITIES}"},
            status_code=400,
        )
    kind = ENTITY_TO_KIND[entity][0]
    ids = (payload or {}).get("ids")
    if not isinstance(ids, list) or not ids:
        return JSONResponse({"error": "body.ids 需为非空列表"}, status_code=400)

    # 第一步：先全部校验快照可用性（避免部分成功部分失败）
    snapshots: list[tuple[str, int]] = []  # (sid, undo_record_id)
    not_found: list[str] = []
    for raw_id in ids:
        sid = str(raw_id)
        try:
            snap = await _resolve_usable_snapshot(kind, sid)
            snapshots.append((sid, snap["id"]))
        except LookupError:
            not_found.append(sid)

    # 任一快照不可用 → 全不撤回（保持原子语义）
    if not_found:
        return JSONResponse(
            {"error": "部分快照不存在或已被撤回", "not_found": not_found},
            status_code=404,
        )

    # 第二步：逐个执行（所有快照已确认可用）
    results: list[dict] = []
    for sid, undo_id in snapshots:
        res = await db._undo_apply(undo_id)
        results.append({"id": sid, "ok": True, "consumed_at": res["consumed_at"]})
    return {
        "ok": True,
        "succeeded": results,
        "not_found": [],
        "attempted": len(ids),
    }


@router.get("/api/undoables")
async def undoables(limit: int = 8) -> dict:
    """最近 N 条可撤回快照（CommandPalette 撤销面板用）。
    返回格式对齐 {entity, entity_id, snapshot_label, created_at}，便于前端直接渲染。"""
    rows = await db.list_undo_records(
        limit=max(1, min(int(limit), 20)), include_consumed=False
    )
    items: list[dict[str, Any]] = []
    for r in rows:
        label = _undo_snapshot_label(r)
        items.append(
            {
                "id": r["id"],
                "entity": r["entity"],
                "entity_id": r["entity_id"],
                "label": label,
                "created_at": r["created_at"],
            }
        )
    return {"items": items}


@router.post("/api/undo/{record_id}")
async def undo_by_id(record_id: int) -> dict:
    """通用撤销端点：按 undo_records.id 直接撤回（前端撤销列表首选，无需关心实体类型）。"""
    try:
        res = await db._undo_apply(int(record_id))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"ok": True, **res}


def _undo_snapshot_label(r: dict[str, Any]) -> str:
    """把 undo_records 一行翻译为人类可读的一行描述（用于 CommandPalette 展示）。"""
    entity = r["entity"]
    eid = r["entity_id"]
    reason = (r.get("reason") or "").strip()
    before = (r.get("before_json") or "").strip()
    verb = "删除" if before in ("", "{}") else "修改"
    name_map = {
        "transaction": "流水",
        "position": "持仓",
        "debt": "负债",
        "subscription": "订阅",
        "goal": "目标",
    }
    base = f"{name_map.get(entity, entity)} {verb}（{eid}）"
    return f"{base} · {reason}" if reason else base
