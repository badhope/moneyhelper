"""财务目标路由：目标 CRUD + 进度计算。"""

from __future__ import annotations

from fastapi import APIRouter

from .. import analysis, db
from . import _crud as crud

router = APIRouter()


@router.get("/api/goals")
async def goals_list() -> dict:
    return {"goals": analysis.goal_progress(await db.list_goals())}


@router.post("/api/goals")
async def create_goal(payload: dict) -> dict:
    return await crud.create_entity(
        payload, add=db.add_goal, action="create_goal", entity_type="goal"
    )


@router.put("/api/goals/{name}")
async def update_goal(name: str, payload: dict) -> dict:
    return await crud.update_entity(
        name, payload, table="goals", update=db.update_goal, action="update_goal", entity_type="goal"
    )


@router.delete("/api/goals/{name}")
async def remove_goal(name: str) -> dict:
    return await crud.delete_entity(
        name, table="goals", delete=db.delete_goal, action="delete_goal", entity_type="goal"
    )
