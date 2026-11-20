from __future__ import annotations

import asyncio  # noqa: F401 — 测试经 agent_graph.asyncio.to_thread 建库
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any, TypedDict

from . import (
    db,
    service,
)
from .logging_utils import get_logger

log = get_logger(__name__)

from .agent_checkpoint import (  # noqa: F401,E402 — 对外同名导出
    _acquire_exec_graph,
    _acquire_saver,
    close_checkpoints,
)
from .agent_graph_builder import _build_graph  # noqa: F401,E402 — 与 get_graph 共用

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


# 企业域节点（拆分模块）：节点、系统提示与工具挑选表都在 agent_enterprise.py
# ---------------------------------------------------------------------------
from .agent_enterprise import (  # noqa: F401,E402 — 供 _build_graph 与外部同名访问
    _ENTERPRISE_TOOL_PICK,
    ENTERPRISE_SYSTEM,
    _enterprise_deterministic,
    _pick_enterprise_tools,
    enterprise,
)
from .agent_graph_run import (  # noqa: F401,E402 — 对外同名导出
    get_graph,
    resume_action,
    run_graph,
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
