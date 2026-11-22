"""历史与会话管理：运行记录、会话增删改、用量与分叉。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import db
from ..logging_utils import get_logger as _get_logger

log = _get_logger(__name__)

router = APIRouter()

def _compact_hit(run: dict, q: str) -> dict:
    """把一整轮问答压成侧栏能放下的一条命中：角色 + 会话名 + 关键词附近片段。"""
    needle = q.lower()
    role = "question"
    text = str(run.get("question") or "")
    idx = text.lower().find(needle)
    if idx < 0:
        role = "answer"
        text = str(run.get("answer") or "")
        idx = text.lower().find(needle)
    if idx < 0:
        idx = 0
    start = max(0, idx - 36)
    end = min(len(text), idx + len(q) + 74)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet += "…"
    return {
        "id": int(run.get("id") or 0),
        "thread_id": str(run.get("thread_id") or ""),
        "session_title": str(run.get("session_title") or ""),
        "role": role,
        "snippet": snippet,
        "created_at": str(run.get("created_at") or ""),
        "archived": bool(run.get("session_archived")),
    }


@router.get("/api/history")
async def history(
    thread_id: str | None = None,
    limit: int = 50,
    q: str = "",
    compact: bool = False,
) -> dict:
    limit = max(1, min(limit, 500))
    # 全局历史：跨会话搜索（供「全部历史」跳转定位）；指定线程则返回该会话历史
    if q.strip():
        runs = await db.search_runs(q.strip()[:200], limit)
        if compact:
            return {"results": [_compact_hit(run, q.strip()[:200]) for run in runs]}
        return {"runs": runs}
    return {"runs": await db.list_runs(thread_id, limit)}

@router.delete("/api/runs/{run_id}")
async def delete_run(run_id: int) -> dict:
    return await db.delete_run(run_id)

@router.post("/api/history/truncate")
async def truncate_history(payload: dict) -> dict:
    """从某一轮开始截断（编辑并重发）：该轮及之后全部删除。"""
    thread_id = str(payload.get("thread_id") or "").strip()
    run_id = payload.get("run_id")
    if not thread_id or run_id is None:
        return JSONResponse({"error": "缺少 thread_id 或 run_id"}, status_code=400)
    try:
        return await db.delete_runs_from(thread_id, int(run_id))
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


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

@router.post("/api/sessions/batch")
async def batch_sessions(payload: dict) -> dict:
    """批量归档/取消归档/置顶/删除；返回实际处理条数。

    逐条复用单会话逻辑，保证删除会话时 runs 与摘要一起清掉；最多 100 条，
    避免误传超大数组把请求拖成分钟级。
    """
    action = str(payload.get("action") or "").strip()
    ids = payload.get("ids") or []
    if action not in {"archive", "unarchive", "pin", "unpin", "delete"}:
        return JSONResponse({"error": "不支持的批量动作"}, status_code=400)
    if not isinstance(ids, list) or not ids:
        return JSONResponse({"error": "ids 不能为空"}, status_code=400)
    try:
        clean = [int(x) for x in ids[:100]]
    except (TypeError, ValueError):
        return JSONResponse({"error": "ids 必须是整数数组"}, status_code=400)
    done = 0
    for sid in clean:
        if action == "delete":
            await db.delete_session(sid)
        elif action == "archive":
            await db.update_session_flags(sid, archived=True, pinned=False)
        elif action == "unarchive":
            await db.update_session_flags(sid, archived=False)
        elif action == "pin":
            await db.update_session_flags(sid, pinned=True)
        else:
            await db.update_session_flags(sid, pinned=False)
        done += 1
    return {"ok": True, "done": done}


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


@router.post("/api/runs/{run_id}/feedback")
async def run_feedback(run_id: int, payload: dict) -> dict:
    """给某轮回答点赞/点踩；rating=0 撤销。只改自己的记录。"""
    try:
        rating = int((payload or {}).get("rating", 0))
    except (TypeError, ValueError):
        return JSONResponse({"error": "rating 必须是整数"}, status_code=400)
    reason = str((payload or {}).get("reason") or "").strip()
    try:
        saved = await db.save_run_feedback(int(run_id), rating, reason)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if saved is None:
        return JSONResponse({"error": "run not found"}, status_code=404)
    return {"ok": True, **saved}


@router.get("/api/feedback/summary")
async def feedback_summary() -> dict:
    """回答反馈汇总，供现有评测分区展示，不新增导航入口。"""
    return await db.feedback_summary()
