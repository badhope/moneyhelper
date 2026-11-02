"""家庭共享仪表板：整体汇总。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db

router = APIRouter()


@router.get("/api/family/summary")
async def family_summary() -> dict:
    """家庭整体汇总：总收入 / 总支出 / 各成员占比 / 未结清借贷 / top 分类"""
    return await db.family_summary()


# ---------------------------------------------------------------------------
# 家庭议会（M6.4）：提案 → 投票 → 多数决
# ---------------------------------------------------------------------------


class MotionCreate(BaseModel):
    title: str
    amount: float = 0.0
    category: str = ""
    note: str = ""
    proposer_id: int | None = None


class VoteCast(BaseModel):
    member_id: int
    vote: str
    note: str = ""


@router.post("/api/family/motions")
async def create_motion(payload: MotionCreate) -> dict:
    try:
        return await db.create_motion(
            payload.title,
            amount=payload.amount,
            category=payload.category,
            note=payload.note,
            proposer_id=payload.proposer_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/family/motions")
async def list_motions(status: str = "") -> dict:
    return {"items": await db.list_motions(status)}


@router.get("/api/family/motions/{motion_id}")
async def get_motion(motion_id: str) -> dict:
    out = await db.get_motion(motion_id)
    if not out:
        raise HTTPException(404, "提案不存在")
    return out


@router.post("/api/family/motions/{motion_id}/votes")
async def vote(motion_id: str, payload: VoteCast) -> dict:
    try:
        return await db.cast_vote(motion_id, payload.member_id, payload.vote, payload.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/family/motions/{motion_id}/withdraw")
async def withdraw(motion_id: str) -> dict:
    try:
        return await db.withdraw_motion(motion_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
