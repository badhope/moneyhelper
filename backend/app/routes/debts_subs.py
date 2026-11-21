"""负债与订阅路由：CRUD 操作（db 层 undo 快照由调用方经由 undo endpoint 触发）。"""

from __future__ import annotations

from fastapi import APIRouter

from .. import db
from . import _crud as crud

router = APIRouter()


# ---------------------------------------------------------------------------
# 负债
# ---------------------------------------------------------------------------


@router.post("/api/debts")
async def create_debt(payload: dict) -> dict:
    return await crud.create_entity(
        payload, add=db.add_debt, action="create_debt", entity_type="debt"
    )


@router.delete("/api/debts/{name}")
async def remove_debt(name: str) -> dict:
    return await crud.delete_entity(
        name, table="debts", delete=db.delete_debt, action="delete_debt", entity_type="debt"
    )


# ---------------------------------------------------------------------------
# 订阅
# ---------------------------------------------------------------------------


@router.get("/api/subscriptions")
async def subscriptions_list() -> dict:
    """订阅列表（供前端总览页卡片使用）。"""
    items = await db.list_subscriptions()
    return {"subscriptions": items}


@router.post("/api/subscriptions")
async def create_subscription(payload: dict) -> dict:
    return await crud.create_entity(
        payload, add=db.add_subscription, action="create_subscription", entity_type="subscription"
    )


@router.delete("/api/subscriptions/{name}")
async def remove_subscription(name: str) -> dict:
    return await crud.delete_entity(
        name,
        table="subscriptions",
        delete=db.delete_subscription,
        action="delete_subscription",
        entity_type="subscription",
    )
