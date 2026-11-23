"""图运行与 HITL 恢复：编译/缓存图、跑一轮 astream、按 token 恢复挂起写操作。

所有共享状态（emit ContextVar、HITL 注册表、图构建器）经门面动态取，
测试替换 `agent_graph.*` 仍然生效。
"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from . import agent_graph as _facade
from .agent_checkpoint import _acquire_exec_graph
from .agent_graph import _CONCURRENT_HITS_MAX, AgentState, Emit
from .agent_pending import _delete_pending, _load_pending, _save_pending
from .logging_utils import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------




_graph: Any | None = None


def get_graph() -> Any:
    """同步结构图（进程内 MemorySaver 编译）：仅用于图结构检查 / 测试，不参与运行。"""
    global _graph
    if _graph is None:
        _graph = _facade._build_graph().compile(checkpointer=MemorySaver())
    return _graph


async def run_graph(
    question: str,
    emit: Emit,
    thread_id: str | None = None,
    lang: str = "zh",
    *,
    session_context: str = "",
    deep_research: bool = False,
    llm_options: dict[str, Any] | None = None,
    images: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """跑一轮图，返回最终结果（供 service.run_question 使用）。

    用 LangGraph 原生 astream 流式执行（stream_mode=[updates,values]），并给每个线程挂
    独立 thread_id 的磁盘 AsyncSqliteSaver checkpoint（落盘 agent_checkpoints.db）。
    动作节点触发 interrupt() 时图挂起等人工确认：
    由 resume_action() 用 Command(resume) 恢复后，节点执行/取消并产出最终结果。
    图失败（节点异常/模型调用异常等）抛异常，由调用方降级确定性路径。
    """
    ctx_token = _facade._emit_ctx.set(emit)
    try:
        await _facade._emit({"type": "agent", "data": {"status": "running", "ts": _facade._now_ms()}})
        state: AgentState = {
            "question": question,
            "thread_id": thread_id,
            "lang": lang,
            "session_context": session_context,
            "deep_research": deep_research,
            "llm_options": llm_options or {},
            "images": images or [],
        }
        # 每次提问独立线程：SqliteSaver 里 thread_id 唯一，避免会话状态串扰；状态落盘可跨运行保留。
        config = {"configurable": {"thread_id": f"run-{uuid.uuid4().hex}"}}
        final_state: dict[str, Any] | None = None
        interrupted: Any | None = None
        async for mode, chunk in (await _acquire_exec_graph()).astream(
            state, config=config, stream_mode=["updates", "values"]
        ):
            if mode == "values" and isinstance(chunk, dict):
                final_state = chunk
            elif mode == "updates" and isinstance(chunk, dict):
                for k, v in chunk.items():
                    if k == "__interrupt__" and v:
                        interrupted = v[0]

        if interrupted is not None:
            payload = getattr(interrupted, "value", None) or interrupted
            token = str(payload.get("token", ""))
            if token:
                # 记录挂起线程 config，供 /api/confirm 用 Command(resume) 恢复图；
                # token→thread_id 一并落盘，进程重启后仍可按 token 恢复（磁盘持久化 HITL）。
                if len(_facade._HITL_THREADS) >= _CONCURRENT_HITS_MAX:
                    # 淘汰最老条目（用户反复触发 buy/sell 永不 confirm 时防无限膨胀）
                    oldest = next(iter(_facade._HITL_THREADS))
                    _facade._HITL_THREADS.pop(oldest, None)
                _facade._HITL_THREADS[token] = config
                await _save_pending(token, config["configurable"]["thread_id"])
                log.info(
                    "run_graph: interrupt registered token=%s threads=%d",
                    token[:12],
                    len(_facade._HITL_THREADS),
                )
            result: dict[str, Any] = {
                "answer": payload.get(
                    "answer", "Awaiting confirmation" if lang == "en" else "需要确认"
                ),
                "level": "待确认",
                "route": "action",
                "route_reason": (
                    "Write action needs manual confirmation (LangGraph interrupt)"
                    if lang == "en"
                    else "写操作需人工确认（LangGraph interrupt）"
                ),
                "metrics": {},
                "flags": [],
                "llm": "tool",
                "tools": [],
                "pending_token": token,
                "pending_summary": payload.get("summary", ""),
            }
        elif final_state is not None:
            result = final_state.get("result")
        else:
            result = None
        if not isinstance(result, dict) or "answer" not in result:
            raise RuntimeError("图执行未产出 result")
        await _facade._emit({"type": "agent", "data": {"status": "done", "ts": _facade._now_ms()}})
        return result
    finally:
        _facade._emit_ctx.reset(ctx_token)


async def resume_action(token: str, decision: str) -> dict[str, Any] | None:
    """恢复被 interrupt 挂起的写操作图（LangGraph 原生 HITL resume）。

    用 Command(resume) 让 action 节点从 interrupt 挂起点继续：按 decision
    执行（confirm → 落库；cancel → 取消），并读取图续跑的最终 result。
    config 优先查进程内注册表；进程重启后注册表为空，则回退从磁盘
    agent_pending.db 按 token 读回 thread_id（配合落盘的 checkpoint 恢复挂起操作）。
    既无内存也无磁盘记录（过期/已消费/非 interrupt 路径）返回 None，由调用方降级。
    """
    config = _facade._HITL_THREADS.get(token)
    if config is None:
        tid = await _load_pending(token)
        if tid:
            config = {"configurable": {"thread_id": tid}}
    log.info(
        "resume_action: token=%s found=%s threads=%d",
        token[:12],
        config is not None,
        len(_facade._HITL_THREADS),
    )
    if config is None:
        return None
    final_state: dict[str, Any] | None = None
    try:
        async for mode, chunk in (await _acquire_exec_graph()).astream(
            Command(resume={"decision": decision}),
            config=config,
            stream_mode=["values"],
        ):
            if mode == "values" and isinstance(chunk, dict):
                final_state = chunk
    finally:
        _facade._HITL_THREADS.pop(token, None)
        await _delete_pending(token)
    result = final_state.get("result") if final_state else None
    if isinstance(result, dict) and "answer" in result:
        return result
    return None

# ---------------------------------------------------------------------------
