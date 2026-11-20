"""LangGraph 多智能体编排图 —— 主执行路径（service.run_question 的图化替代）。

节点（每个都是独立 agent 角色，后续可独立扩展/替换）：
  supervisor     意图分类 agent：LLM 分类优先、规则兜底；一句话记账检测
  record         记账 agent：确定性入账（规则秒回，无需模型）
  general        通用 agent：不带任何财务数据出机（隐私边界不变）
  collect_market 市场 agent：持仓/行情/盈亏/集中度（确定性内核）
  collect_ledger 账本 agent：收支/结余/负债/应急金（确定性内核）
  risk           风控 agent：集中度/应急金/高息负债/DTI/储蓄率告警
  finalize       成文 agent：有模型 → function calling 工具循环；无模型 → 模板成文

设计原则：
- 图负责"编排"（谁先谁后、状态流转、条件分支），**数字仍由 analysis 确定性内核计算**；
- 模型只出现在 supervisor（分类）与 finalize（成文/工具调用），且任一失败自动降级：
  无模型 = 图照跑，所有 agent 节点走确定性实现，输出与旧流程完全一致；
- 事件契约不变（start/step/agent_step/text/final/done），SSE 协议零改动；
- 数据层是单连接 aiosqlite，节点间用顺序边（多 agent 结构在，不做跨节点并发，避免撞库）。

LangGraph 1.x 关键用法：StateGraph 状态机 + add_conditional_edges 条件路由 +
节点返回 partial update 自动合并；模型/工具调用仍是项目自有的 llm.py / tools.py
（openai 3.x 已适配），不引入 langchain-openai，避免版本耦合。
"""

from __future__ import annotations

import asyncio
import time
import uuid
import weakref
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any, TypedDict

import aiosqlite
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from . import (
    db,
    service,
)
from .logging_utils import get_logger

log = get_logger(__name__)

Emit = Callable[[dict[str, Any]], Awaitable[None]]

# HITL 挂起库路径（与 checkpoint 同目录、独立文件）。测试夹具会改这个值，
# agent_pending 每次建连时读取它，因此这里的真源不能搬走。
_PENDING_DB = db.data_dir() / "agent_pending.db"

# 节点内实时发 SSE 事件：ContextVar 按 asyncio task 隔离，并发请求互不串扰
_emit_ctx: ContextVar[Emit | None] = ContextVar("wo_emit", default=None)

# LangGraph 线程状态**磁盘持久化**：checkpoint 落 backend/data/agent_checkpoints.db，
# 与主库 wealth.db 隔离（checkpoint 存图运行态，不是账本数据）。WAL 模式支持多连接。
_CHECKPOINT_DB = db.data_dir() / "agent_checkpoints.db"

# HITL confirm 并发锁与 token 注册表最大容量：两个数据结构共用同一上限，
# 防止用户反复触发 buy/sell 永不 confirm 导致无限膨胀。
# 注意：_CONCURRENT_HITS_MAX 同时约束 _confirm_locks（main.py）与 _HITL_THREADS。
_CONCURRENT_HITS_MAX = 512
_HITL_THREADS: dict[str, dict[str, Any]] = {}

# AsyncSqliteSaver 是异步初始化、且连接绑定「创建它的那个 event loop」（aiosqlite）。
# 按事件循环缓存：生产端单 worker 单 loop 复用同一连接（写入即可持久落盘）；
# 测试里每个 loop 各持独立连接、串行访问同一文件，互不串扰，也避免跨 loop 报错。
#
# 用 WeakKeyDictionary 而不是 id(loop) 作键：id() 在对象被回收后可能被复用，
# 新 loop 拿到旧 key 就会命中已关闭的连接（症状是随机 "Event loop is closed"）。
# 弱引用键在 loop 被 GC 时自动失效，不需要手动清理。
_savers: weakref.WeakKeyDictionary[Any, AsyncSqliteSaver] = weakref.WeakKeyDictionary()
_exec_graphs: weakref.WeakKeyDictionary[Any, Any] = weakref.WeakKeyDictionary()


async def _acquire_saver() -> AsyncSqliteSaver:
    """按当前 event loop 惰性构建磁盘 AsyncSqliteSaver（WAL + setup）。"""
    loop = asyncio.get_running_loop()
    key = loop
    if key not in _savers:
        _CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(_CHECKPOINT_DB))
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        _savers[key] = saver
    return _savers[key]


async def _acquire_exec_graph() -> Any:
    """按当前 event loop 惰性编译「带磁盘 checkpoint 的执行图」（供 run_graph / resume 使用）。"""
    loop = asyncio.get_running_loop()
    key = loop
    if key not in _exec_graphs:
        saver = await _acquire_saver()
        _exec_graphs[key] = _build_graph().compile(checkpointer=saver)
    return _exec_graphs[key]


async def close_checkpoints() -> None:
    """关闭并清空当前进程持有的磁盘 checkpoint 连接（供测试 teardown / 优雅停机复用）。

    生产端单 worker 单 loop 常驻连接无需调用；测试端每个 loop 各开一个连接，
    测试结束前由 conftest 调用本函数释放 aiosqlite worker 线程，避免 loop 关闭后挂住进程。
    """
    _exec_graphs.clear()
    for saver in list(_savers.values()):
        try:
            await saver.conn.close()
        except Exception:
            pass
    _savers.clear()
    _close_pending_conn()


# ---------------------------------------------------------------------------
# token → thread_id 磁盘持久化：让「进程重启后也能恢复 HITL 挂起操作」。
# 与 checkpoint 分文件（agent_pending.db），独立于 LangGraph 管理的 checkpoint 库。
# ---------------------------------------------------------------------------














async def _emit(ev: dict[str, Any]) -> None:
    e = _emit_ctx.get()
    if e is not None:
        await e(ev)


def _now_ms() -> int:
    return int(time.time() * 1000)


# 大额审批 pending 有效期：超过后「确认」不再生效（防止隔很久的误触/陈旧回复入账）




class AgentState(TypedDict, total=False):
    question: str
    thread_id: str | None
    lang: str  # 界面语言：zh | en（回答与确定性兜底文案跟随）
    route: str
    reason: str
    mode: str  # agent | deterministic
    routes: list[str]
    market: dict[str, Any] | None
    ledger: dict[str, Any] | None
    flags: list[dict[str, Any]]
    has_data: bool
    parsed: dict[str, Any] | None
    confirm: bool  # 大额审批：用户回复「确认」后带 True 重走 record
    pending_question: str | None  # 大额审批确认时携带的原问题（「确认」本身没有金额）
    result: dict[str, Any]
    # collect_market 写入、collect_ledger / finalize 复用：避免同一轮持仓+行情被重复拉取
    positions: list[dict[str, Any]] | None
    live: dict[str, float] | None


# ---------------------------------------------------------------------------
# 节点实现
# ---------------------------------------------------------------------------




# 写入/动作节点已拆到 agent_nodes_action.py，见文件末尾导入。



# 取数/风控节点已拆到 agent_nodes_collect.py，见文件末尾导入。



async def general(state: AgentState) -> dict[str, Any]:
    """通用 agent：复用既有通用路径（带同会话记忆、不带财务数据）。"""
    result = await service._run_general(
        state["question"],
        state["reason"],
        _emit,
        state.get("thread_id"),
        state.get("lang", "zh"),
    )
    return {"result": result}


# 企业域 agent 说明书：与财务分支同一套「先取数再成文」纪律，但数据域不同。
# 企业域节点已拆到 agent_enterprise.py，见本文件顶部的导入。





# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------




def _build_graph() -> Any:
    g = StateGraph(AgentState)
    g.add_node("supervisor", supervisor)
    g.add_node("record", record)
    g.add_node("nl_cancel", nl_cancel)
    g.add_node("memory", memory)
    g.add_node("action", action)
    g.add_node("studio_admin", studio_admin)
    g.add_node("general", general)
    g.add_node("enterprise", enterprise)
    g.add_node("collect_market", collect_market)
    g.add_node("collect_ledger", collect_ledger)
    g.add_node("risk", risk)
    g.add_node("finalize", finalize)

    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        _supervisor_route,
        {
            "record": "record",
            "nl_cancel": "nl_cancel",
            "memory": "memory",
            "general": "general",
            "enterprise": "enterprise",
            "action": "action",
            "studio_admin": "studio_admin",
            "finance": "collect_market",
        },
    )
    # 多智能体管线：市场 agent → 账本 agent → 风控 agent → 成文 agent
    # （顺序边：单连接 aiosqlite 不支持跨节点并发读写，结构并行、执行串行）
    g.add_edge("collect_market", "collect_ledger")
    g.add_edge("collect_ledger", "risk")
    g.add_edge("risk", "finalize")
    g.add_edge("record", END)
    g.add_edge("nl_cancel", END)
    g.add_edge("memory", END)
    g.add_edge("action", END)
    g.add_edge("studio_admin", END)
    g.add_edge("general", END)
    g.add_edge("enterprise", END)
    g.add_edge("finalize", END)
    # 仅声明图结构，不在此编译：结构图（get_graph）挂 MemorySaver，执行图
    # （_acquire_exec_graph）挂磁盘 AsyncSqliteSaver，两者共享同一节点/路由定义。
    return g


_graph: Any | None = None


def get_graph() -> Any:
    """同步结构图（进程内 MemorySaver 编译）：仅用于图结构检查 / 测试，不参与运行。"""
    global _graph
    if _graph is None:
        _graph = _build_graph().compile(checkpointer=MemorySaver())
    return _graph


async def run_graph(
    question: str, emit: Emit, thread_id: str | None = None, lang: str = "zh"
) -> dict[str, Any]:
    """跑一轮图，返回最终结果（供 service.run_question 使用）。

    用 LangGraph 原生 astream 流式执行（stream_mode=[updates,values]），并给每个线程挂
    独立 thread_id 的磁盘 AsyncSqliteSaver checkpoint（落盘 agent_checkpoints.db）。
    动作节点触发 interrupt() 时图挂起等人工确认：
    由 resume_action() 用 Command(resume) 恢复后，节点执行/取消并产出最终结果。
    图失败（节点异常/模型调用异常等）抛异常，由调用方降级确定性路径。
    """
    ctx_token = _emit_ctx.set(emit)
    try:
        await _emit({"type": "agent", "data": {"status": "running", "ts": _now_ms()}})
        state: AgentState = {"question": question, "thread_id": thread_id, "lang": lang}
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
                if len(_HITL_THREADS) >= _CONCURRENT_HITS_MAX:
                    # 淘汰最老条目（用户反复触发 buy/sell 永不 confirm 时防无限膨胀）
                    oldest = next(iter(_HITL_THREADS))
                    _HITL_THREADS.pop(oldest, None)
                _HITL_THREADS[token] = config
                await _save_pending(token, config["configurable"]["thread_id"])
                log.info(
                    "run_graph: interrupt registered token=%s threads=%d",
                    token[:12],
                    len(_HITL_THREADS),
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
        await _emit({"type": "agent", "data": {"status": "done", "ts": _now_ms()}})
        return result
    finally:
        _emit_ctx.reset(ctx_token)


async def resume_action(token: str, decision: str) -> dict[str, Any] | None:
    """恢复被 interrupt 挂起的写操作图（LangGraph 原生 HITL resume）。

    用 Command(resume) 让 action 节点从 interrupt 挂起点继续：按 decision
    执行（confirm → 落库；cancel → 取消），并读取图续跑的最终 result。
    config 优先查进程内注册表；进程重启后注册表为空，则回退从磁盘
    agent_pending.db 按 token 读回 thread_id（配合落盘的 checkpoint 恢复挂起操作）。
    既无内存也无磁盘记录（过期/已消费/非 interrupt 路径）返回 None，由调用方降级。
    """
    config = _HITL_THREADS.get(token)
    if config is None:
        tid = await _load_pending(token)
        if tid:
            config = {"configurable": {"thread_id": tid}}
    log.info(
        "resume_action: token=%s found=%s threads=%d",
        token[:12],
        config is not None,
        len(_HITL_THREADS),
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
        _HITL_THREADS.pop(token, None)
        await _delete_pending(token)
    result = final_state.get("result") if final_state else None
    if isinstance(result, dict) and "answer" in result:
        return result
    return None

# ---------------------------------------------------------------------------
# 企业域节点（拆分模块）：节点、系统提示与工具挑选表都在 agent_enterprise.py
# ---------------------------------------------------------------------------
from .agent_enterprise import (  # noqa: F401,E402 — 供 _build_graph 与外部同名访问
    _ENTERPRISE_TOOL_PICK,
    ENTERPRISE_SYSTEM,
    _enterprise_deterministic,
    _pick_enterprise_tools,
    enterprise,
)
from .agent_nodes_action import (  # noqa: F401,E402 — 供 _build_graph 与外部同名访问
    action,
    memory,
    nl_cancel,
    record,
    studio_admin,
)
from .agent_nodes_collect import collect_ledger, collect_market, risk  # noqa: F401,E402
from .agent_nodes_final import finalize  # noqa: F401,E402

# ---------------------------------------------------------------------------
# 监督/收尾节点与 HITL 挂起存储已拆到独立模块；import 触发并以同名属性保留
# ---------------------------------------------------------------------------
from .agent_nodes_super import (  # noqa: F401,E402
    _supervisor_route,
    supervisor,
)
from .agent_pending import (  # noqa: F401,E402
    _PENDING_APPROVAL_TTL_MINUTES,
    _close_pending_conn,
    _delete_pending,
    _load_pending,
    _pending_confirm_context,
    _pending_conn,
    _pending_cutoff,
    _pending_sql,
    _save_pending,
)
