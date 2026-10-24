"""财务目标路由：目标 CRUD + 进度计算。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import analysis, db
from ..provenance import record_provenance

router = APIRouter()


@router.get("/api/goals")
async def goals_list() -> dict:
    return {"goals": analysis.goal_progress(await db.list_goals())}


@router.post("/api/goals")
async def create_goal(payload: dict) -> dict:
    name = str((payload or {}).get("name", "")).strip()
    try:
        out = await db.add_goal(payload or {})
    except Exception as exc:  # noqa: BLE001 — 坏输入回 400
        return JSONResponse({"error": str(exc)}, status_code=400)
    await record_provenance(
        action="create_goal",
        entity_type="goal",
        entity_id=name,
        before=None,
        after=payload or {},
        source="api",
    )
    analysis.invalidate_dashboard_cache()
    return out


@router.put("/api/goals/{name}")
async def update_goal(name: str, payload: dict) -> dict:
    before_row = await db.fetch_one("SELECT * FROM goals WHERE name = ?", (name,))
    before = dict(before_row) if before_row else None
    try:
        out = await db.update_goal(name, payload or {})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    after_row = await db.fetch_one("SELECT * FROM goals WHERE name = ?", (name,))
    after = dict(after_row) if after_row else None
    await record_provenance(
        action="update_goal",
        entity_type="goal",
        entity_id=name,
        before=before,
        after=after,
        source="api",
    )
    analysis.invalidate_dashboard_cache()
    return out


@router.delete("/api/goals/{name}")
async def remove_goal(name: str) -> dict:
    before_row = await db.fetch_one("SELECT * FROM goals WHERE name = ?", (name,))
    before = dict(before_row) if before_row else None
    result = await db.delete_goal(name)
    await record_provenance(
        action="delete_goal",
        entity_type="goal",
        entity_id=name,
        before=before,
        after=None,
        source="api",
    )
    analysis.invalidate_dashboard_cache()
    return result
