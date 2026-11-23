"""会话项目卡：固定资料、项目指令、项目记忆（只作用于当前 thread）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from .. import db
from ..auth import get_current_user

router = APIRouter(prefix="/api/threads", dependencies=[Depends(get_current_user)])


def _tid(thread_id: str) -> str:
    tid = (thread_id or "").strip()
    if not tid or len(tid) > 128:
        raise HTTPException(status_code=400, detail="thread_id invalid")
    return tid


@router.get("/{thread_id}/context")
async def read_context(thread_id: str) -> dict[str, Any]:
    return await db.get_thread_context(_tid(thread_id))


@router.put("/{thread_id}/context")
async def write_context(thread_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return await db.save_thread_context(
            _tid(thread_id),
            instructions=payload.get("instructions"),
            attachment_ids=payload.get("attachment_ids"),
            memories=payload.get("memories"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{thread_id}/context")
async def clear_context(thread_id: str) -> dict[str, Any]:
    try:
        return await db.save_thread_context(_tid(thread_id), instructions="", attachment_ids=[], memories=[])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
