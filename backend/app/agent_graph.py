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
import json
import sqlite3
import time
import uuid
import weakref
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any, TypedDict

import aiosqlite
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import (
    agent,
    analysis,
    db,
    llm,
    mem,
    nlparse,
    quotes,
    service,
    tool_schemas,
    tools,
)
from .logging_utils import get_logger

log = get_logger(__name__)

Emit = Callable[[dict[str, Any]], Awaitable[None]]

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
_PENDING_DB = _CHECKPOINT_DB.with_name("agent_pending.db")
_pending_conn: sqlite3.Connection | None = None


def _pending_sql() -> sqlite3.Connection:
    global _pending_conn
    if _pending_conn is None:
        _PENDING_DB.parent.mkdir(parents=True, exist_ok=True)
        _pending_conn = sqlite3.connect(str(_PENDING_DB), check_same_thread=False)
        _pending_conn.execute("PRAGMA journal_mode=WAL")
        _pending_conn.execute(
            "CREATE TABLE IF NOT EXISTS pending("
            " token TEXT PRIMARY KEY, thread_id TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        _pending_conn.commit()
    return _pending_conn


async def _save_pending(token: str, thread_id: str) -> None:
    def _w() -> None:
        c = _pending_sql()
        # 顺手清理过期条目：pending 表此前只增不删，用户反复触发写操作但不确认时
        # 会无限增长（重启后还能被 resume 的也只是最近 30 分钟内的）。
        c.execute(
            "DELETE FROM pending WHERE created_at < ?",
            (_pending_cutoff(),),
        )
        c.execute(
            "INSERT OR REPLACE INTO pending(token, thread_id, created_at) VALUES(?,?,?)",
            (token, thread_id, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
        c.commit()

    await asyncio.to_thread(_w)


def _pending_cutoff() -> str:
    """早于此刻的 pending 记录视为过期（与审批 TTL 一致，避免陈旧 token 被恢复）。"""
    from datetime import timedelta

    return (datetime.now() - timedelta(minutes=_PENDING_APPROVAL_TTL_MINUTES)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )


async def _load_pending(token: str) -> str | None:
    def _r() -> str | None:
        row = (
            _pending_sql()
            .execute(
                "SELECT thread_id FROM pending WHERE token=? AND created_at >= ?",
                (token, _pending_cutoff()),
            )
            .fetchone()
        )
        return row[0] if row else None

    return await asyncio.to_thread(_r)


async def _delete_pending(token: str) -> None:
    def _d() -> None:
        c = _pending_sql()
        c.execute("DELETE FROM pending WHERE token=?", (token,))
        c.commit()

    await asyncio.to_thread(_d)


def _close_pending_conn() -> None:
    global _pending_conn
    if _pending_conn is not None:
        try:
            _pending_conn.close()
        except Exception:
            pass
        _pending_conn = None


async def _emit(ev: dict[str, Any]) -> None:
    e = _emit_ctx.get()
    if e is not None:
        await e(ev)


def _now_ms() -> int:
    return int(time.time() * 1000)


# 大额审批 pending 有效期：超过后「确认」不再生效（防止隔很久的误触/陈旧回复入账）
_PENDING_APPROVAL_TTL_MINUTES = 30


async def _pending_confirm_context(
    question: str, thread_id: str | None
) -> dict[str, Any] | None:
    """上一轮为 nl_pending 待确认时，把「确认/取消」短回复识别为审批回执。

    仅当该线程最后一条 run 的 route 是 nl_pending、未过 TTL 且回复命中词表才算，否则返回 None。
    （消费动作由调用方经 db.claim_pending_nl 原子完成，本函数只做识别。）
    """
    if not thread_id:
        return None
    decision = service._confirm_decision(question)
    if decision is None:
        return None
    runs = await db.list_runs(thread_id, 1)
    if not runs or runs[0].get("route") != "nl_pending":
        return None
    try:
        created = datetime.fromisoformat(str(runs[0].get("created_at") or ""))
        if datetime.now().astimezone() - created > timedelta(
            minutes=_PENDING_APPROVAL_TTL_MINUTES
        ):
            return None
    except ValueError:
        pass  # 时间戳异常不阻断（按未过期处理）
    return {"decision": decision, "question": str(runs[0].get("question") or "")}


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


async def supervisor(state: AgentState) -> dict[str, Any]:
    """意图分类 + 记账检测。LLM 分类失败/未接入一律规则兜底。"""
    q = state["question"]
    tid = state.get("thread_id")
    en_lang = state.get("lang") == "en"

    # 大额审批回执优先：「确认/取消」承接本线程最后一条 nl_pending，先于一切路由，
    # 否则「确认」会被分类成 general，审批流断在死路（原实现承诺可回复确认但无实现）。
    # claim_pending_nl 原子消费：并发/断连重试时只有一个回执能生效，防重复入账。
    pending_ctx = await _pending_confirm_context(q, tid)
    if pending_ctx:
        if pending_ctx["decision"] == "confirm":
            segments = service._nl_segments(pending_ctx["question"])
            if segments and tid and await db.claim_pending_nl(str(tid)):
                return {
                    "route": "bookkeeping",
                    "reason": "Large-amount approval: user confirmed"
                    if en_lang
                    else "大额审批：用户确认入账",
                    "parsed": segments[0],
                    "confirm": True,
                    "pending_question": pending_ctx["question"],
                }
        elif tid and await db.claim_pending_nl(str(tid)):
            return {
                "route": "nl_cancel",
                "reason": "Large-amount approval: user cancelled"
                if en_lang
                else "大额审批：用户取消",
            }
        # claim 失败（已被并发回执消费）或原句不可解析：落回常规路由，不重复入账

    # 长记忆 recall：把用户历史相关记忆注入 state，供后续节点参考
    # （纯本地 BM25 检索，零网络；技能关闭时不召回，隐私与开关口径一致）
    from . import agent_config

    long_mem_on = await agent_config.is_skill_enabled("long_memory")
    mem_hits = await mem.recall(q) if long_mem_on else []
    if mem_hits:
        log.info(
            "mem.recalled count=%s sample=%s",
            len(mem_hits),
            mem_hits[0].get("memory", "")[:60],
        )

    route, reason = service.route_question(q, state.get("lang", "zh"))
    if route == "general" and await service._is_finance_followup(q, tid):
        route = "both"
        reason = (
            "Follow-up to the previous finance question"
            if state.get("lang") == "en"
            else "承接上一轮财务提问的省略追问"
        )

    # 动作指令优先（卖出/清仓/晨报/备份）：先于记账检测，否则「卖出 600519」
    # 这类带数字的动作会被 nlparse 当成一笔支出记进账本（语义劫持）。
    if route == "action":
        return {"route": "action", "reason": reason, "mode": "deterministic"}

    # 记忆指令其次（先于记账）：「记住/记得 …」明确是记忆意图，
    # 否则「记住我下个月要交房租 5000」会被一句话记账当成支出入账。
    # 写入只由 memory 节点做一次（它负责剥离「记住」前缀、去重与技能开关回执）；
    # 路由层不再重复写，避免同一句话存两条。
    if service._looks_like_memory(q):
        reason_mem = (
            "Recognized as a memory instruction — saving to long-term memory"
            if state.get("lang") == "en"
            else "识别为记忆指令，直接存长期记忆"
        )
        return {"route": "memory", "reason": reason_mem, "mode": "deterministic"}

    # 一句话记账：短句 + 能解析出金额 → 记账 agent（规则秒回，不调模型）
    # 「自选」类指令先排除：股票代码（600519）会被 nlparse 当成金额，走 60 万大额审批（实测）
    parsed = None
    if service._looks_like_record(q) and not service._looks_like_watchlist(q):
        parsed = nlparse.parse(q)
    if parsed is not None:
        return {"route": "bookkeeping", "reason": reason, "parsed": parsed}

    if route == "general":
        # 规则未命中且模型可用：让模型兜底判一次是否其实是理财问题（如「茅台现在多少钱」）
        if await llm.llm_available():
            llm_route = await service.classify_question_llm(q, state.get("lang", "zh"))
            if llm_route in ("market", "ledger", "both", "goal"):
                route = llm_route
                reason = (
                    "Model recognized this as a finance question"
                    if en_lang
                    else "模型判定这是理财问题"
                )
            else:
                return {"route": "general", "reason": reason, "mode": "deterministic"}
        else:
            return {"route": "general", "reason": reason, "mode": "deterministic"}

    mode = "agent" if await llm.llm_available() else "deterministic"
    # goal 路由（目标/体检）需要完整财务数据：市场 + 账本都查
    routes = ["market", "ledger"] if route in ("both", "goal") else [route]

    en_st = state.get("lang") == "en"
    # 结构化计划：前端 Agent 面板/推理轨迹展示本轮将执行的 Agent 管线（label/detail 跟随语言）
    plan_steps: list[dict[str, Any]] = []
    if mode == "agent":
        plan_steps = [
            {
                "id": "supervisor",
                "label": "Understand" if en_st else "理解意图",
                "detail": reason,
            },
            {
                "id": "reason",
                "label": "Reason" if en_st else "自主分析",
                "detail": (
                    "Verify holdings/ledger/risk with tools, then compose"
                    if en_st
                    else "调用工具核对持仓/账本/风险后成文"
                ),
            },
        ]
    else:
        if "market" in routes:
            plan_steps.append(
                {
                    "id": "market",
                    "label": "View holdings" if en_st else "查看持仓",
                    "detail": "Holdings · Quotes · P&L · Concentration"
                    if en_st
                    else "持仓·行情·盈亏·集中度",
                }
            )
        if "ledger" in routes:
            plan_steps.append(
                {
                    "id": "ledger",
                    "label": "Ledger" if en_st else "核对账本",
                    "detail": "Income · Expenses · Cash · Debt"
                    if en_st
                    else "收支·结余·负债·应急金",
                }
            )
        plan_steps.append(
            {
                "id": "risk",
                "label": "Risk review" if en_st else "风险复核",
                "detail": "Concentration · Emergency fund · High-interest debt"
                if en_st
                else "集中度·应急金·高息负债",
            }
        )
        plan_steps.append(
            {
                "id": "finalize",
                "label": "Compose answer" if en_st else "整理成文",
                "detail": "Summarize conclusion & figures"
                if en_st
                else "汇总结论与数字",
            }
        )
    # Agent 行为可配置：关闭「展示执行计划」时不再发计划卡（推理轨迹/面板同步隐藏）
    _agent_plan = (await db.get_settings()).get("agent_plan", "on") != "off"
    if plan_steps and _agent_plan:
        await _emit(
            {
                "type": "plan",
                "data": {"steps": plan_steps, "mode": mode, "route": route},
            }
        )

    # 确定性模式发"理解问题"步骤；agent 模式不发（工具调用过程即说明，避免重复）
    if mode == "deterministic":
        await _emit(
            {
                "type": "step",
                "id": "supervisor",
                "label": "Understand" if en_st else "理解问题",
                "detail": f"{reason}，开始分析" if not en_st else reason,
                "phase": "done",
            }
        )
    return {"route": route, "reason": reason, "mode": mode, "routes": routes}


async def record(state: AgentState) -> dict[str, Any]:
    """记账 agent：把一句话记账指令确定性入账并回执（复用 service._try_nl_add 唯一实现）。

    大额审批：**任一分段**金额 > 5000 元时先不入账，返回 pending 状态让用户确认
    （分段口径与 _try_nl_add 入账口径共用 service._nl_segments，防止整句解析只取
    第一段金额绕过审批，如「奶茶 20，房租 6000」）。
    用户回复「确认」后由 supervisor 带 confirm=true + 原问题回到本节点，整句一起入账。
    """
    parsed = state["parsed"]
    assert parsed is not None
    confirm = state.get("confirm", False)
    src_q = state.get("pending_question") or state["question"]

    # 门槛判定按全部分段（与入账同口径）；任一段超阈值即触发审批
    segments = service._nl_segments(src_q)
    breach = (
        max(segments, key=lambda p: abs(float(p.get("amount", 0))))
        if segments
        else parsed
    )
    amount = abs(float(breach.get("amount", 0)))

    # 大额审批：任一段超阈值先确认（阈值与 MCP 侧共用 approval.threshold）
    from . import approval

    if amount > await approval.threshold() and not confirm:
        direction = "收入" if float(breach.get("amount", 0)) > 0 else "支出"
        extra = (
            f"，本句共 {len(segments)} 笔，确认后一起入账" if len(segments) > 1 else ""
        )
        lang = state.get("lang", "zh")
        # 摘要描述与 MCP 侧共用 approval.describe_transaction，保证两条路径
        # 对"这笔是什么"的说法一致；交互指引（回复确认/取消）属于 Web 形态，
        # 留在本层而不是塞进共享模块。
        summary = approval.describe_transaction(breach, lang)
        if lang == "en":
            answer = (
                f"{approval.format_approval_prompt(summary, amount, lang='en')}\n\n"
                f"Record: {summary}{extra}\n"
                f'Reply "confirm" to record, "cancel" to skip.'
            )
        else:
            answer = (
                f"{approval.format_approval_prompt(summary, amount, extra=extra.lstrip('，'), lang='zh')}\n\n"
                f"记的是：{summary}\n"
                f"回复「确认」就入账，回复「取消」就不记。"
            )
        result = {
            "answer": answer,
            "level": "待确认",
            "route": "nl_pending",
            "route_reason": f"大额{direction}审批：{amount:,.0f} 元",
            "metrics": {},
            "flags": [],
            "llm": "template",
            "tools": [],
            "actions": [],
            "pending_token": "",
            "pending_summary": f"{direction} {amount:,.0f} 元",
        }
        return {"result": result}

    result = await service._try_nl_add(
        state.get("pending_question") or state["question"],
        state["reason"],
        _emit,
        state.get("lang", "zh"),
    )
    assert result is not None
    result.setdefault("actions", [{"tab": "ledger"}])
    return {"result": result}


async def nl_cancel(state: AgentState) -> dict[str, Any]:
    """大额审批取消：不入账，仅回执说明未记账。"""
    en = state.get("lang") == "en"
    return {
        "result": {
            "answer": "OK — not recorded." if en else "好，这笔不记了。",
            "level": "已取消",
            "route": "nl_cancel",
            "route_reason": "Large-amount approval: user cancelled"
            if en
            else "大额审批：用户取消",
            "metrics": {},
            "flags": [],
            "llm": "template",
            "tools": [],
            "actions": [],
            "pending_token": "",
            "pending_summary": "",
        }
    }


async def action(state: AgentState) -> dict[str, Any]:
    """动作 agent：不配模型也能在对话里直接执行的动作指令（卖出/清仓、晨报、备份）。

    写类动作（卖出/买入）先登记待确认（pending_actions），随后用 LangGraph 原生
    interrupt() 挂起图 —— 这是 HITL 的真正暂停点。前端确认后经 resume_action()
    用 Command(resume) 恢复图：节点从 interrupt 返回，按用户决定执行/取消并落库，
    最终结果（answer）由图续跑产出。整个 HITL 生命周期都在 LangGraph 内。
    """
    result = await tools.run_action(
        state["question"], state.get("lang", "zh"), emit=_emit
    )
    en = state.get("lang") == "en"
    if result.get("pending_token"):
        token = result["pending_token"]
        # 挂起图，等待用户确认；resume 后这里返回 Command(resume) 传入的决策。
        decision = interrupt(
            {
                "token": token,
                "summary": result["pending_summary"],
                "answer": result["answer"],
            }
        )
        if isinstance(decision, dict) and decision.get("decision") == "confirm":
            # 原子抢占：抢占失败说明这条 token 已被别的请求消费（并发/重放），
            # 直接返回"已失效"，绝不重复执行写操作。
            pending = await db.claim_pending_action(token)
            if pending is None:
                result = {
                    "answer": (
                        "This action was already executed or has expired — nothing was run again."
                        if en
                        else "该操作已执行或已失效，未重复执行。"
                    ),
                    "level": "已失效",
                    "route": "action",
                    "route_reason": "Pending action already consumed" if en else "待确认动作已被消费",
                    "metrics": {},
                    "flags": [],
                    "llm": "tool",
                    "tools": [],
                }
                return {"result": result}
            impl = tools.TOOL_IMPL.get(pending["tool_name"])
            clean_args, verr = tool_schemas.validate_tool_args(pending["tool_name"], pending["args"])
            if impl is not None and clean_args is None:
                result = {
                    "answer": f"操作未执行：{verr}",
                    "level": "失败",
                    "route": "action",
                    "route_reason": "工具入参校验失败",
                    "metrics": {},
                    "flags": [],
                    "llm": "tool",
                    "tools": [],
                }
                return {"result": result}
            if impl is not None and clean_args is not None:
                pending = {**pending, "args": clean_args}
                try:
                    ans = await impl(pending["args"])
                    result = {
                        "answer": ans,
                        "level": "已执行",
                        "route": "action",
                        "route_reason": (
                            "Write action confirmed by human (LangGraph interrupt/resume)"
                            if en
                            else "写操作已人工确认（LangGraph interrupt/resume）"
                        ),
                        "metrics": {},
                        "flags": [],
                        "llm": "tool",
                        "tools": [pending["tool_name"]],
                        "actions": [{"tab": "holdings"}],
                    }
                except Exception as exc:  # noqa: BLE001 — 执行失败给可读回执
                    await db.mark_pending_action(token, "failed")
                    result = {
                        "answer": (
                            f"Execution failed: {type(exc).__name__}: {exc}"
                            if en
                            else f"执行失败：{type(exc).__name__}: {exc}"
                        ),
                        "level": "失败",
                        "route": "action",
                        "route_reason": (
                            "Write action failed" if en else "写操作执行异常"
                        ),
                        "metrics": {},
                        "flags": [],
                        "llm": "tool",
                        "tools": [pending["tool_name"]],
                    }
        else:
            await db.mark_pending_action(token, "cancelled")
            result = {
                "answer": "Cancelled — no changes were made."
                if en
                else "已取消该操作，未做任何改动。",
                "level": "已取消",
                "route": "action",
                "route_reason": "Write action cancelled" if en else "写操作已取消",
                "metrics": {},
                "flags": [],
                "llm": "tool",
                "tools": [],
            }
    return {"result": result}


async def memory(state: AgentState) -> dict[str, Any]:
    """记忆 agent：把「记住/记得 …」指令确定性写入长期记忆并回执（规则级，无需模型）。"""
    result = await service._try_save_memory(
        state["question"], _emit, state.get("lang", "zh")
    )
    assert result is not None
    return {"result": result}


async def collect_market(state: AgentState) -> dict[str, Any]:
    """市场 agent：持仓/行情/盈亏/集中度。确定性模式发步骤事件 + 工具调用事件。"""
    if "market" not in (state.get("routes") or []):
        return {}
    det = state.get("mode") == "deterministic"
    if det:
        await _emit(
            {
                "type": "step",
                "id": "market",
                "label": "View holdings" if state.get("lang") == "en" else "查看持仓",
                "detail": "Fetch holdings & quotes, compute P&L and concentration"
                if state.get("lang") == "en"
                else "拉取持仓与行情，计算盈亏与集中度",
                "phase": "start",
            }
        )
        await _emit(
            {
                "type": "tool",
                "data": {
                    "id": "market",
                    "name": "get_market_view",
                    "status": "running",
                    "node": "collect_market",
                    "ts": time.time() * 1000,
                },
            }
        )
    started = time.monotonic()
    positions = await db.list_positions()
    live = await quotes.live_quotes(positions)
    market = analysis.market_view(positions, live)
    duration_ms = int((time.monotonic() - started) * 1000)
    if det:
        en = state.get("lang") == "en"
        summary = (
            f"Market value ¥{market['total_market_value']:,.0f}, {'up' if market['total_pnl'] >= 0 else 'down'} ¥{abs(market['total_pnl']):,.0f}"
            if en
            else f"总市值 {market['total_market_value']:,.0f} 元，累计{'浮盈' if market['total_pnl'] >= 0 else '浮亏'} {abs(market['total_pnl']):,.0f} 元"
        )
        await _emit(
            {
                "type": "tool",
                "data": {
                    "name": "get_market_view",
                    "status": "done",
                    "summary": summary,
                    "duration_ms": duration_ms,
                    "node": "collect_market",
                    "ts": _now_ms(),
                },
            }
        )
        await _emit(
            {
                "type": "step",
                "id": "market",
                "label": "View holdings" if state.get("lang") == "en" else "查看持仓",
                "detail": summary,
                "phase": "done",
            }
        )
    # positions/live 写入 state 供 collect_ledger、finalize 复用（同轮只拉一次）
    return {"market": market, "positions": positions, "live": live}


async def collect_ledger(state: AgentState) -> dict[str, Any]:
    """账本 agent：收支/结余/负债/应急金。确定性模式发步骤事件 + 工具调用事件。"""
    if "ledger" not in (state.get("routes") or []):
        return {}
    det = state.get("mode") == "deterministic"
    if det:
        await _emit(
            {
                "type": "step",
                "id": "ledger",
                "label": "Ledger" if state.get("lang") == "en" else "核对账本",
                "detail": "Income · Expenses · Subscriptions · Debt · Emergency fund"
                if state.get("lang") == "en"
                else "汇总本月收支、订阅、负债与应急金",
                "phase": "start",
            }
        )
        await _emit(
            {
                "type": "tool",
                "data": {
                    "name": "get_ledger_view",
                    "status": "running",
                    "node": "collect_ledger",
                    "ts": _now_ms(),
                },
            }
        )
    started = time.monotonic()
    positions = state.get("positions")
    if positions is None:
        positions = await db.list_positions()
    live = state.get("live")
    if live is None:
        live = await quotes.live_quotes(positions)
    settings = await db.get_settings()
    ledger = analysis.ledger_view(
        await db.list_transactions(),
        await db.list_subscriptions(),
        await db.list_debts(),
        settings,
        positions,
        live,
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    if det:
        en = state.get("lang") == "en"
        summary = (
            f"Net ¥{ledger['net']:,.0f} this month, debt ¥{ledger['debt_monthly']:,.0f}/mo"
            if en
            else f"本月结余 {ledger['net']:,.0f} 元，负债月供 {ledger['debt_monthly']:,.0f} 元"
        )
        await _emit(
            {
                "type": "tool",
                "data": {
                    "name": "get_ledger_view",
                    "status": "done",
                    "summary": summary,
                    "duration_ms": duration_ms,
                    "node": "collect_ledger",
                    "ts": _now_ms(),
                },
            }
        )
        await _emit(
            {
                "type": "step",
                "id": "ledger",
                "label": "Ledger" if state.get("lang") == "en" else "核对账本",
                "detail": summary,
                "phase": "done",
            }
        )
    return {"ledger": ledger}


async def risk(state: AgentState) -> dict[str, Any]:
    """风控 agent：跑规则告警。确定性模式发步骤事件 + 工具调用事件。"""
    det = state.get("mode") == "deterministic"
    if det:
        await _emit(
            {
                "type": "tool",
                "data": {
                    "name": "get_risk_flags",
                    "status": "running",
                    "node": "risk",
                    "ts": _now_ms(),
                },
            }
        )
    started = time.monotonic()
    flags = analysis.risk_checks(
        state.get("market"), state.get("ledger"), state.get("lang", "zh")
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    if det:
        detail = (
            (
                f"Found {len(flags)} item(s) to watch: "
                + "; ".join(f["text"] for f in flags[:2])
                if flags
                else "No significant risks found"
            )
            if state.get("lang") == "en"
            else (
                f"发现 {len(flags)} 项需关注："
                + "；".join(f["text"] for f in flags[:2])
                if flags
                else "未发现明显风险项"
            )
        )
        await _emit(
            {
                "type": "tool",
                "data": {
                    "name": "get_risk_flags",
                    "status": "done",
                    "summary": detail,
                    "duration_ms": duration_ms,
                    "node": "risk",
                    "ts": _now_ms(),
                },
            }
        )
        await _emit(
            {
                "type": "step",
                "id": "risk",
                "label": "Risk review" if state.get("lang") == "en" else "风险复核",
                "detail": detail,
                "phase": "done",
            }
        )
    return {"flags": flags}


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


async def finalize(state: AgentState) -> dict[str, Any]:
    """成文 agent：有模型 → function calling 工具循环；无模型 → 模板成文（流式）。"""
    q = state["question"]
    tid = state.get("thread_id")
    routes = state.get("routes") or []
    market = state.get("market")
    ledger = state.get("ledger")
    flags = state.get("flags") or []
    # 空数据判定与旧流程一致：没有任何持仓且没有任何流水 → 引导记账（不是零值假象）
    positions = state.get("positions")
    if positions is None:
        positions = await db.list_positions()
    if state.get("mode") != "agent":
        has_data = bool(positions) or bool(
            await db.fetch_all("SELECT 1 FROM transactions LIMIT 1")
        )
    else:
        has_data = True  # agent 模式由模型自行判断数据有无
    route = state.get("route") or "both"
    reason = state.get("reason") or ""

    if state.get("mode") == "agent":
        # agent 模式：模型自主调用工具取数成文（工具数字仍来自本地确定性计算）。
        # 模型不可用/调用失败抛 AgentUnavailable → 图内降级确定性模板成文（不中断、不冒充）。
        try:
            history = await service._build_history(tid)
            result = await agent.run_agent(
                q, _emit, history, state.get("lang", "zh")
            )
            live = state.get("live")
            if live is None:
                live = await quotes.live_quotes(positions)
            m = analysis.market_view(positions, live) if "market" in routes else market
            led = (
                analysis.ledger_view(
                    await db.list_transactions(),
                    await db.list_subscriptions(),
                    await db.list_debts(),
                    await db.get_settings(),
                    positions,
                    live,
                )
                if "ledger" in routes
                else ledger
            )
            flags = analysis.risk_checks(m, led, state.get("lang", "zh"))
            level = "L2 建议" if flags else "L1 洞察"
            answer = result["answer"].strip()
            # 主动理财引导：基于确定性风控 code 给一句下一步动作（差异化「主动 Agent」）
            advice = analysis.next_step_advice(flags, True, state.get("lang", "zh"))
            if advice:
                answer = answer.rstrip() + "\n\n" + advice
            disclaimer = (
                analysis.DISCLAIMER_EN
                if state.get("lang") == "en"
                else analysis.DISCLAIMER
            )
            if disclaimer not in answer:
                answer = answer + "\n\n— " + disclaimer
            return {
                "result": {
                    "answer": answer,
                    "level": level,
                    "route": route,
                    "route_reason": reason,
                    "metrics": service._metrics_from(m, led),
                    "flags": flags,
                    "llm": "llm",
                    "tools": result.get("tools_used", []),
                    "agent_steps": result.get("steps", []),
                    # 单路由命中时另一项为 None，过滤掉避免前端拿到 null 崩溃
                    "actions": [
                        a
                        for a in (
                            {"tab": "holdings"} if "market" in routes else None,
                            {"tab": "ledger"} if "ledger" in routes else None,
                        )
                        if a
                    ],
                }
            }
        except agent.AgentUnavailable:
            log.warning("agent 工具循环不可用，图内降级确定性成文")
            # 降级到确定性模板前重新判定空数据：空库不得给「总资产 0 元」假象，
            # 应走「还没有录入」引导（与确定性模式一致，防止新用户被劝退）。
            has_data = bool(positions) or bool(
                await db.fetch_all("SELECT 1 FROM transactions LIMIT 1")
            )

    # 确定性模式：模板/模型润色成文（流式 text 事件，与旧流程一致）
    level = "L2 建议" if flags else "L1 洞察"
    # 体检意图：确定性输出五维报告（无模型也能「帮我体检」，数字仍来自本地内核）。
    # 空库同样走记账引导，不给「60 分」假象（与 template_answer 的空库保护一致）。
    wants_health = any(w in q for w in analysis.HEALTH_WORDS)
    if wants_health and has_data:
        fallback = analysis.health_report_text(
            analysis.health_check(
                market,
                ledger,
                flags,
                await db.list_goals(),
                lang=state.get("lang", "zh"),
            ),
            state.get("lang", "zh"),
        )
    elif wants_health:
        fallback = analysis.no_data_answer(state.get("lang", "zh"))
    else:
        fallback = analysis.template_answer(
            market, ledger, flags, has_data=has_data, lang=state.get("lang", "zh")
        )
    history = await service._build_history(tid)
    system = (
        "你是用户的个人理财助手。根据给定的持仓与账本数据，用简洁的中文回答用户的问题："
        "先一句话给结论，再分点列出关键数字，最后提示风险项（如有）。"
        "不要编造任何未给出的数字，不要给出具体买卖指令。"
    )
    if state.get("lang") == "en":
        system = (
            "You are the user's personal finance assistant. Based on the holdings and ledger data provided, "
            "answer the user's question concisely in English: give a one-line conclusion first, "
            "then list key numbers point by point, and finally note any risks (if any). "
            "Never invent numbers not provided, and never give specific buy/sell instructions."
        )
    if history:
        system += (
            "本次附带了同一会话的历史问答，用于理解「那上个月呢」这类省略追问："
            "历史只作上下文参考，所有数字必须以本轮给定数据为准，不得沿用历史里的数字。"
        )
    user_obj: dict[str, Any] = {
        "question": q,
        "market": market,
        "ledger": ledger,
        "flags": flags,
        "level": level,
    }
    if history:
        user_obj["history"] = history
    user = json.dumps(user_obj, ensure_ascii=False)

    await _emit(
        {
            "type": "step",
            "id": "finalize",
            "label": "Compose answer" if state.get("lang") == "en" else "整理成文",
            "detail": "Summarize conclusion & figures"
            if state.get("lang") == "en"
            else "汇总结论与数字",
            "phase": "start",
        }
    )

    chunks: list[str] = []
    src = "template"
    async for delta, s in llm.stream_narrate(system, user, fallback):
        if s == "reasoning":
            # 思考过程单列事件，不混进正文
            await _emit({"type": "thinking", "data": {"content": delta}})
            continue
        src = s
        chunks.append(delta)
        await _emit({"type": "text", "delta": delta})

    answer = "".join(chunks).strip() or fallback
    # 主动理财引导：基于确定性风控 code 给一句下一步动作（差异化「主动 Agent」）
    advice = analysis.next_step_advice(flags, has_data, state.get("lang", "zh"))
    if advice:
        answer = answer.rstrip() + "\n\n" + advice
    disclaimer = (
        analysis.DISCLAIMER_EN if state.get("lang") == "en" else analysis.DISCLAIMER
    )
    if disclaimer not in answer:
        answer = answer + "\n\n— " + disclaimer

    await _emit(
        {
            "type": "step",
            "id": "finalize",
            "label": "Compose answer" if state.get("lang") == "en" else "整理成文",
            "detail": "Done" if state.get("lang") == "en" else "已完成",
            "phase": "done",
        }
    )

    # 结构化数据卡：前端把数字渲染成对话内嵌小卡（4 宫格 / mini 环形 / 持仓预览），
    # 不再纯文字叙述。前端不认识就忽略，向后兼容。
    if has_data and ("market" in routes or "ledger" in routes):
        await _emit(
            {
                "type": "card",
                "block": {
                    "kind": "finance_snapshot",
                    "data": {
                        "route": route,
                        "market": market,
                        "ledger": ledger,
                        "flags": flags,
                    },
                },
            }
        )

    return {
        "result": {
            "answer": answer,
            "level": level,
            "route": route,
            "route_reason": reason,
            "metrics": service._metrics_from(market, ledger),
            "flags": flags,
            "llm": src,
            "tools": [],
            # 同上：过滤单路由命中时的 None 项
            "actions": [
                a
                for a in (
                    {"tab": "holdings"} if "market" in routes else None,
                    {"tab": "ledger"} if "ledger" in routes else None,
                )
                if a
            ],
        }
    }


# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------


def _supervisor_route(state: AgentState) -> str:
    r = state.get("route") or ""
    if r == "bookkeeping":
        return "record"
    if r == "nl_cancel":
        return "nl_cancel"
    if r == "memory":
        return "memory"
    if r == "action":
        return "action"
    if r == "general":
        return "general"
    return "finance"


def _build_graph() -> Any:
    g = StateGraph(AgentState)
    g.add_node("supervisor", supervisor)
    g.add_node("record", record)
    g.add_node("nl_cancel", nl_cancel)
    g.add_node("memory", memory)
    g.add_node("action", action)
    g.add_node("general", general)
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
            "action": "action",
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
    g.add_edge("general", END)
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
