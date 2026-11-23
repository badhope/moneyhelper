"""会话项目卡：固定资料、项目指令、项目记忆（只作用于当前 thread）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from .. import db
from ..auth import get_current_user

router = APIRouter(prefix="/api/threads", dependencies=[Depends(get_current_user)])
projects_router = APIRouter(prefix="/api/chat-projects", dependencies=[Depends(get_current_user)])


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
        kwargs: dict[str, Any] = {
            "instructions": payload.get("instructions"),
            "attachment_ids": payload.get("attachment_ids"),
            "memories": payload.get("memories"),
        }
        # 只有显式带 project_id 才切换作用域；老客户端不带时保留原来的项目绑定。
        if "project_id" in payload:
            kwargs["project_id"] = payload.get("project_id")
        return await db.save_thread_context(_tid(thread_id), **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{thread_id}/context")
async def clear_context(thread_id: str) -> dict[str, Any]:
    try:
        return await db.save_thread_context(_tid(thread_id), instructions="", attachment_ids=[], memories=[])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@projects_router.get("")
async def list_projects() -> dict[str, Any]:
    return {"projects": await db.list_chat_projects()}


@projects_router.get("/{project_id}")
async def read_project(project_id: int) -> dict[str, Any]:
    project = await db.get_chat_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@projects_router.post("")
async def create_project(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return await db.save_chat_project(
            name=payload.get("name"),
            instructions=payload.get("instructions"),
            attachment_ids=payload.get("attachment_ids"),
            memories=payload.get("memories"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@projects_router.put("/{project_id}")
async def update_project(project_id: int, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return await db.save_chat_project(
            project_id=project_id,
            name=payload.get("name"),
            instructions=payload.get("instructions"),
            attachment_ids=payload.get("attachment_ids"),
            memories=payload.get("memories"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@projects_router.delete("/{project_id}")
async def remove_project(project_id: int) -> dict[str, Any]:
    out = await db.delete_chat_project(project_id)
    if not out.get("deleted"):
        raise HTTPException(status_code=404, detail="项目不存在")
    return out
