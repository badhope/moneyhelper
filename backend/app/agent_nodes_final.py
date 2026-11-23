"""收尾节点：把工具结果/模型回答整理成带指标、动作与待确认的最终回包。

从 agent_graph.py 拆出；仍是 LangGraph 的一个节点。
"""

from __future__ import annotations

import json
from typing import Any

from . import agent, analysis, db, quotes, service
from .agent_graph import AgentState, _emit
from .logging_utils import get_logger

log = get_logger(__name__)

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
                q,
                _emit,
                history,
                state.get("lang", "zh"),
                session_context=state.get("session_context") or "",
                deep_research=bool(state.get("deep_research")),
                llm_options=state.get("llm_options") or {},
                images=state.get("images") or [],
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
    usage: dict[str, int] = {}
    # 经 service._narrate 调用：兼容不支持 usage_out 的 stream_narrate 实现，
    # 计量缺失也不影响成文（见 service._narrate 的说明）。
    async for delta, s in service._narrate(system, user, fallback, usage):
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
            # harness：本轮 token 用量（模型真实回传；模板轮为空 dict）
            "tokens": usage,
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
