"""历史与会话管理：运行记录、会话增删改、用量与分叉。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import db
from ..logging_utils import get_logger as _get_logger

log = _get_logger(__name__)

router = APIRouter()

@router.get("/api/history")
async def history(thread_id: str | None = None, limit: int = 50, q: str = "") -> dict:
    limit = max(1, min(limit, 500))
    # 全局历史：跨会话搜索（供「全部历史」跳转定位）；指定线程则返回该会话历史
    if q.strip():
        return {"runs": await db.search_runs(q.strip(), limit)}
    return {"runs": await db.list_runs(thread_id, limit)}

@router.delete("/api/runs/{run_id}")
async def delete_run(run_id: int) -> dict:
    return await db.delete_run(run_id)

@router.post("/api/history/clear")
async def clear_history() -> dict:
    return await db.clear_history()

@router.get("/api/sessions")
async def sessions() -> dict:
    return {"sessions": await db.list_sessions()}

@router.post("/api/sessions")
async def create_session(payload: dict | None = None) -> dict:
    title = str((payload or {}).get("title") or "新会话").strip()
    return await db.create_session(title=title)

@router.patch("/api/sessions/{session_id}")
async def update_session(session_id: int, payload: dict) -> dict:
    """改标题 / 置顶 / 归档；只传其中一个也能单独生效。"""
    if "title" in payload:
        title = str(payload.get("title") or "").strip()
        if not title:
            return JSONResponse({"error": "标题不能为空"}, status_code=400)
        await db.rename_session(session_id, title)
    pinned = payload.get("pinned")
    archived = payload.get("archived")
    if pinned is not None or archived is not None:
        await db.update_session_flags(
            session_id,
            pinned=bool(pinned) if pinned is not None else None,
            archived=bool(archived) if archived is not None else None,
        )
    return {"ok": True}

@router.post("/api/sessions/{session_id}/migrate")
async def migrate_session_runs(session_id: int, request: Request) -> dict:
    """把乐观新建窗口内挂在临时线程下的 runs 迁入真实会话。"""
    from_tid = request.query_params.get("from", "").strip()
    if not from_tid:
        return JSONResponse({"error": "from required"}, status_code=400)
    real_tid = await db.session_thread_id(session_id)
    if not real_tid:
        return JSONResponse({"error": "session not found"}, status_code=404)
    moved = await db.move_runs(from_tid, real_tid)
    return {"ok": True, "moved": moved}

@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: int) -> dict:
    return await db.delete_session(session_id)

@router.get("/api/sessions/{session_id}/usage")
async def session_usage_endpoint(session_id: int) -> dict:
    """会话 token 计量（前端上下文仪表数据源）。"""
    tid = await db.session_thread_id(session_id)
    if not tid:
        return JSONResponse({"error": "session not found"}, status_code=404)
    return await db.session_usage(tid)

@router.get("/api/sessions/by-thread/{thread_id}/usage")
async def session_usage_by_thread(thread_id: str) -> dict:
    """按 thread_id 取会话 token 计量。

    对话页手里只有 thread_id（会话可能尚未在 sessions 表落行），因此提供
    按线程直查的入口；未知线程返回零值而不是 404——「还没有用量」是正常状态。
    """
    return await db.session_usage(thread_id)

@router.post("/api/sessions/{session_id}/fork")
async def fork_session_endpoint(session_id: int, payload: dict) -> dict:
    """从某条问答分叉出新会话（opencode 式 branch）：复制该轮及之前的全部历史。"""
    run_id = int(payload.get("run_id") or 0)
    if run_id <= 0:
        return JSONResponse({"error": "run_id required"}, status_code=400)
    tid = await db.session_thread_id(session_id)
    if not tid:
        return JSONResponse({"error": "session not found"}, status_code=404)
    forked = await db.fork_session(tid, run_id)
    if not forked:
        return JSONResponse({"error": "run not in session"}, status_code=404)
    return forked
