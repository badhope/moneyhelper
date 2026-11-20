"""监督节点：问题分类、工具面挑选与路由决策。

从 agent_graph.py 拆出；仍是 LangGraph 的一个节点，靠 AgentState/_emit 与图交互，
主文件末尾 import 触发并以同名属性保留。
"""

from __future__ import annotations

from typing import Any

from . import db, llm, mem, nlparse, service
from .agent_graph import AgentState, _emit
from .logging_utils import get_logger

log = get_logger(__name__)

async def supervisor(state: AgentState) -> dict[str, Any]:
    """意图分类 + 记账检测。LLM 分类失败/未接入一律规则兜底。"""
    q = state["question"]
    tid = state.get("thread_id")
    en_lang = state.get("lang") == "en"

    # 大额审批回执优先：「确认/取消」承接本线程最后一条 nl_pending，先于一切路由，
    # 否则「确认」会被分类成 general，审批流断在死路（原实现承诺可回复确认但无实现）。
    from .agent_pending import _pending_confirm_context

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

    # 对话内配置（添加/停用/删除角色、技能、提示词、约束、Hook）：先于记账与记忆，
    # 否则「添加技能 定投提醒：每周日检查」会被 nlparse 当成一笔支出入账。
    from .studio import commands as studio_commands

    studio_result = await studio_commands.handle_question(q, state.get("lang", "zh"))
    if studio_result is not None:
        return {
            "route": "studio_admin",
            "reason": (
                "Studio configuration command"
                if en_lang
                else "对话内修改 Agent Studio 配置"
            ),
            "mode": "deterministic",
            "result": {
                "answer": studio_result.get("answer", ""),
                "level": "L1 洞察" if not en_lang else "L1",
                "route": "studio_admin",
                "route_reason": "Studio configuration command"
                if en_lang
                else "对话内修改 Agent Studio 配置",
                "metrics": {},
                "flags": [],
                "llm": "template",
                "tools": [],
                "actions": [],
            },
        }

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
            if llm_route in ("market", "ledger", "both", "goal", "enterprise"):
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

    # 企业域分支（规则强词命中，或模型兜底判成 enterprise）：独立节点自带工具面，
    # 不参与财务管线的持仓/账本取数与风险复核（那条链路只算个人理财指标）。
    if route == "enterprise":
        return {
            "route": "enterprise",
            "reason": reason,
            "mode": "agent" if await llm.llm_available() else "deterministic",
        }

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
    if r == "enterprise":
        return "enterprise"
    if r == "studio_admin":
        return "studio_admin"
    return "finance"
