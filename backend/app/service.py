"""问答服务：把用户的提问跑成一份可复核的财务回答。

唯一执行路径是 LangGraph 多智能体编排图（app/agent_graph.py）：
  supervisor（分类 agent）→ 记账 / 通用 / 市场+账本+风控 / 成文 agent 节点，
  图负责编排与状态流转，数字仍由 analysis 确定性内核计算；
  成文节点内捕获 agent 工具循环失败并降级确定性模板（图内降级，无旧双轨）。
  本模块只保留图各节点复用的纯函数（路由/历史/通用/记账解析/指标）。

事件契约（SSE，由 main.py 转发给前端）：
  {"type":"start","question":...}
  {"type":"step","id":"market","label":"查看持仓","detail":"...","phase":"start|done"}
  {"type":"agent_step","name":"get_market_view","args":{...},"summary":"..."}  # agent 模式
  {"type":"text","delta":"..."}          # 成文增量（LLM 流式 或 模板一次给出）
  {"type":"final","answer":...,"level":...,"route":...,"metrics":{...},"flags":[...],"llm":"llm|template"}
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from . import db, llm  # noqa: F401 — 测试通过 service.db 注入 spy
from .logging_utils import get_logger

log = get_logger(__name__)

Emit = Callable[[dict[str, Any]], Awaitable[None]]


GENERAL_SYSTEM = (
    "你是一个通用 AI 助手，同时具备个人理财工具的能力。"
    "普通问题（写作、翻译、编程、闲聊等）直接正常回答；"
    "遇到与用户财务相关的问题，如实说明你还没有该问题的数据，"
    "并提示可以在应用里记账或添加持仓后再问。不要编造任何数字。"
)
GENERAL_FALLBACK = (
    "当前没有接入模型，自由问答需要先到「设置 → AI 回答」配置模型端点。"
    "不过记账和确定性分析我离线就能做：去「记账」一句话记一笔，"
    "或问我持仓、收支、负债与风险。"
)

# 疑问/讨论式句式黑名单：命中则不当记账指令，避免把「花了3000怎么办」写进账本




# 历史/摘要已拆到 service_history.py，见文件末尾导入。



GENERAL_SYSTEM_EN = (
    "You are a general-purpose AI assistant with personal-finance tooling. "
    "Answer ordinary questions (writing, translation, coding, small talk, etc.) directly; "
    "when a question relates to the user's finances, honestly say you don't have that data yet "
    "and suggest recording transactions or adding holdings in the app first. Never invent numbers."
)
GENERAL_FALLBACK_EN = (
    "No model is connected right now — free-form chat needs a model endpoint in Settings → AI answers. "
    "But bookkeeping and deterministic analysis work offline: record a transaction in Ledger with one sentence, "
    "or ask about holdings, income & expenses, debt and risk."
)


async def _narrate(system: str, user: str, fallback: str, usage: dict[str, int]):
    """调用 llm.stream_narrate，兼容不支持 usage_out 的实现（测试桩/第三方替换）。

    harness 需要把每轮 token 落库，但 stream_narrate 是可替换点：旧桩函数
    只接受三个位置参数。这里先按新签名调用，遇到 TypeError 再退回旧签名，
    计量缺失不影响回答——宁可少一个数字，也不能让整轮对话失败。
    """
    try:
        stream = llm.stream_narrate(system, user, fallback, usage_out=usage)
    except TypeError:
        stream = llm.stream_narrate(system, user, fallback)
    async for item in stream:
        yield item


async def _run_general(
    question: str,
    reason: str,
    emit: Emit,
    thread_id: str | None = None,
    lang: str = "zh",
) -> dict[str, Any]:
    """默认路径：通用 agent。

    - 带同会话的通用上下文（它得记得上文，否则不叫 agent）
    - 不注入也不外发任何财务数据；财务轮次的历史同样不出机
    - 不套财务分级（level 留空）、不拼财务免责声明
    - 已接入模型 → 走通用 Agent 内核（web_search / get_now 通用工具，领域无关），
      这体现「先 Agent、后财务」：通用问答本身就是一个真 Agent，而非裸 LLM。
    - 模型不可用/工具循环失败 → 降级内置模板回答。
    """
    history = await _build_history(thread_id, only_route="general")

    from . import agent as agent_mod

    if await llm.llm_available():
        try:
            result = await agent_mod.run_agent(
                question,
                emit,
                history,
                lang,
                system=agent_mod.GENERAL_SYSTEM,
                tools_list=agent_mod.GENERAL_TOOLS,
                impl_map=agent_mod.GENERAL_IMPL,
                inject_memories=False,
            )
            result.update(
                {
                    "level": "",
                    "route": "general",
                    "route_reason": reason,
                    "metrics": {},
                    "flags": [],
                }
            )
            return result
        except agent_mod.AgentUnavailable:
            # 模型已接入但本次工具循环失败（限流/网络波动/不收敛）：如实说明，绝不冒充「未接入模型」。
            if lang == "zh":
                fallback = (
                    "抱歉，这次没能联网答成：模型/联网服务暂时不可用（可能限流或网络波动）。"
                    "请稍后再试，或到「设置 → AI 回答」确认模型端点配置正确。"
                )
            else:
                fallback = (
                    "Sorry, I couldn't answer via the web this time — the model/web service is "
                    "temporarily unavailable (rate limit or network). Please try again shortly, "
                    "or check the model endpoint in Settings → AI answers."
                )
            return {
                "answer": fallback,
                "level": "",
                "route": "general",
                "route_reason": reason,
                "metrics": {},
                "flags": [],
                "llm": "template",
            }

    user_obj: dict[str, Any] = {"question": question}
    if history:
        user_obj["history"] = history
    user = json.dumps(user_obj, ensure_ascii=False)

    system = GENERAL_SYSTEM if lang == "zh" else GENERAL_SYSTEM_EN
    fallback = GENERAL_FALLBACK if lang == "zh" else GENERAL_FALLBACK_EN
    chunks: list[str] = []
    src = "template"
    usage: dict[str, int] = {}
    async for delta, s in _narrate(system, user, fallback, usage):
        if s == "reasoning":
            # 思考过程单列事件，不混进正文（否则答案里会冒出推理草稿）
            await emit({"type": "thinking", "data": {"content": delta}})
            continue
        src = s
        chunks.append(delta)
        await emit({"type": "text", "delta": delta})

    return {
        "answer": "".join(chunks).strip() or fallback,
        "level": "",
        "route": "general",
        "route_reason": reason,
        "metrics": {},
        "flags": [],
        "llm": src,
        "tokens": usage,
    }


def _metrics_from(
    market: dict[str, Any] | None, ledger: dict[str, Any] | None
) -> dict[str, float]:
    metrics: dict[str, float] = {}
    if market:
        metrics.update(
            {
                "total_market_value": market["total_market_value"],
                "total_pnl": market["total_pnl"],
                "total_pnl_pct": market["total_pnl_pct"],
            }
        )
    if ledger:
        metrics.update(
            {
                "net": ledger["net"],
                "savings_rate": ledger["savings_rate"],
                "debt_monthly": ledger["debt_monthly"],
                "dti_pct": ledger["dti_pct"],
            }
        )
    return metrics


async def run_question(
    question: str, emit: Emit, thread_id: str | None = None, lang: str = "zh"
) -> dict[str, Any]:
    """执行一轮问答，返回最终元信息（由调用方负责归档与转发 final 事件）。

    主路径：LangGraph 多智能体图（agent_graph.run_graph）。
    图内已内置降级：模型不可用/工具循环失败 → 确定性模板成文（图内降级，无旧双轨），
    输出与事件契约与 agent 模式同构，服务不中断、不冒充模型结果。
    lang：界面语言（zh/en），回答与确定性兜底文案跟随。
    """
    await emit({"type": "start", "question": question})
    from .agent_graph import run_graph

    return await run_graph(question, emit, thread_id, lang)

from .service_history import (  # noqa: F401,E402 — 对外同名导出与 run_question 使用
    HISTORY_ANSWER_CHARS,
    HISTORY_MAX_TOKENS,
    HISTORY_TURNS,
    SUMMARY_KEEP_TURNS,
    SUMMARY_MAX_CHARS,
    SUMMARY_TRIGGER_TURNS,
    _build_history,
    _heuristic_summary,
    _heuristic_summary_with_prev,
    _split_sentences,
    _summarize_exchanges,
    ensure_session_summary,
)

# ---------------------------------------------------------------------------
# 路由域（拆分模块）：词表、意图判定、NL 记账入口
# ---------------------------------------------------------------------------
from .service_routing import (  # noqa: F401,E402 — 对外同名导出
    _CANCEL_REPLIES,
    _CONFIRM_REPLIES,
    ACTION_WORDS,
    DATA_QUESTION_MARKS,
    ENTERPRISE_STRONG_WORDS,
    ENTERPRISE_WEAK_WORDS,
    FOLLOWUP_MARKS,
    FOLLOWUP_MAX_LEN,
    GOAL_WORDS,
    LEDGER_WORDS,
    MARKET_WORDS,
    MEMORY_VERBS,
    NL_MAX_LEN,
    QUESTION_MARKS,
    _confirm_decision,
    _has_finance_word,
    _is_finance_followup,
    _looks_like_enterprise_data_question,
    _looks_like_memory,
    _looks_like_record,
    _looks_like_watchlist,
    _nl_segments,
    _try_nl_add,
    _try_save_memory,
    classify_question_llm,
    route_question,
)

