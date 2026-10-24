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
import re
from collections.abc import Awaitable, Callable
from typing import Any

from . import db, llm, nlparse

Emit = Callable[[dict[str, Any]], Awaitable[None]]

MARKET_WORDS = (
    "股票",
    "基金",
    "持仓",
    "仓位",
    "组合",
    "收益",
    "亏",
    "涨",
    "跌",
    "etf",
    "市值",
    "资产",
    "集中度",
    "配置",
    "自选",
    "加自选",
    "走势",
    "k线",
    "股价",
    "现价",
    "行情",
)
LEDGER_WORDS = (
    "花",
    "消费",
    "支出",
    # 「开销 / 开支 / 花费」是最常见的口语说法；此前只收「支出」，
    # 导致「这个月的开销怎么样」被判成普通闲聊、不查账本。
    "开销",
    "开支",
    "花费",
    "记账",
    "账",
    "预算",
    "订阅",
    "会员",
    "还款",
    "负债",
    "房贷",
    "信用卡",
    "现金流",
    "存",
    "省",
    "应急金",
    "储蓄",
    "收入",
    "余额",
    "工资",
)
# 目标/体检专用词：命中即按「市场+账本」全量财务路由（体检与目标进度需要完整数据）。
# 刻意不用「目标」「进度」这类宽泛词，避免「人生目标」这类非财务问法被误伤（宁缺毋滥）。
GOAL_WORDS = (
    "体检",
    "健康检查",
    "存够",
    "攒够",
    "首付",
    "买房",
    "买车",
    "还差多少",
    "建议月存",
    "攒钱",
    "存款目标",
    "攒首付",
)
# 动作指令：命中即确定性执行工具（不依赖模型）。词选窄、选动作明确，避免误伤日常问法。
ACTION_WORDS = (
    "买入",
    "买进",
    "建仓",
    "加仓",
    "卖出",
    "卖掉",
    "清仓",
    "减仓",
    "抛售",
    "晨报",
    "备份",
    "默认首页",
    "涨跌颜色",
    "颜色主题",
    "换颜色",
    "切换语言",
)
# 记忆动词：短句 + 无问号 → 对话内「记住/记得 …」直接存长期记忆（规则级，无需模型）
MEMORY_VERBS = ("记住", "记得")

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
QUESTION_MARKS = ("吗", "呢", "怎", "哪", "多少", "是不是", "?", "？")
NL_MAX_LEN = 24

# 多轮上下文：最多回看 4 轮，每条截断 400 字（控制 token 与外发体量）
HISTORY_TURNS = 4
HISTORY_ANSWER_CHARS = 400

# 长会话压缩：会话问答轮次超过阈值后，把较早轮次压缩成结构化摘要落库，
# 只在上下文里保留摘要 + 最近 K 轮完整（避免 token 无限增长，同时保住长程记忆）。
SUMMARY_TRIGGER_TURNS = 8  # 超过该轮次才触发压缩
SUMMARY_KEEP_TURNS = 4  # 压缩后仍保留的最近完整轮次（与 HISTORY_TURNS 一致）
SUMMARY_MAX_CHARS = 2000  # 摘要单条上限（落库截断与注入截断）

# 省略式追问：短句 + 指代词（「那上个月呢？」本身不含财务关键词，需承接上一轮）
FOLLOWUP_MARKS = ("那", "它", "这个", "上个月", "上月", "刚才", "刚刚", "其中", "前面")
FOLLOWUP_MAX_LEN = 12


def _has_finance_word(text: str) -> bool:
    q = text.lower()
    return any(w in q for w in MARKET_WORDS) or any(w in q for w in LEDGER_WORDS)


async def _is_finance_followup(question: str, thread_id: str | None) -> bool:
    """判断是否为承接上一轮财务提问的省略追问。

    四重约束同时成立才改判为财务路由：短句、含指代词、本会话上一轮是财务提问、已接入模型。
    未接入模型时不改判——确定性内核只算「本月」，让它回答「上个月」是误导。
    """
    q = question.strip()
    if not thread_id or len(q) > FOLLOWUP_MAX_LEN:
        return False
    if not any(m in q for m in FOLLOWUP_MARKS):
        return False
    if not await llm.llm_available():
        return False
    runs = await db.list_runs(thread_id, 1)
    if not runs:
        return False
    prev = runs[0]
    if _has_finance_word(str(prev.get("question") or "")):
        return True
    # 词表之外：上一轮本身就是财务路由（记账/动作/分析）也算承接上下文
    return str(prev.get("route") or "") in (
        "nl_add",
        "bookkeeping",
        "record",
        "action",
        "market",
        "ledger",
        "goal",
        "both",
    )


def _looks_like_record(question: str) -> bool:
    """短句 + 无疑问词 + 能解析出金额 → 视为一句话记账指令。"""
    q = question.strip()
    if not q or len(q) > NL_MAX_LEN:
        return False
    return not any(m in q for m in QUESTION_MARKS)


# 大额审批回执短语：仅「去空白/标点后精确命中词表」才算审批回复，防止普通短聊被误判。
# 词表保持显式（不含「好/是/对」等日常用语），降低 pending 上下文中的误触面。
_CONFIRM_REPLIES = {
    "确认",
    "确认入账",
    "确认记账",
    "确定",
    "记吧",
    "入账",
    "ok",
    "yes",
    "confirm",
}
_CANCEL_REPLIES = {
    "取消",
    "不记了",
    "不用了",
    "不记账",
    "算了",
    "no",
    "cancel",
}


def _confirm_decision(text: str) -> str | None:
    """把短回复归类为大额审批回执：「confirm」/「cancel」；不匹配返回 None。"""
    t = re.sub(r"[\s。.!！~～,，、;；]+", "", (text or "").strip().lower())
    if not t or len(t) > 8:
        return None
    if t in _CONFIRM_REPLIES:
        return "confirm"
    if t in _CANCEL_REPLIES:
        return "cancel"
    return None


def _nl_segments(question: str) -> list[dict[str, Any]]:
    """一句话记账的统一切段解析口径：按标点/连词切段、逐段解析。

    _try_nl_add 入账与「大额审批」门槛判定共用本函数，保证两者看到完全相同的分段，
    避免整句解析只取到第一段金额绕过审批（如「奶茶 20，房租 6000」）。
    """
    if not _looks_like_record(question):
        return []
    parts = [p.strip() for p in re.split(r"[，,。;；、和及]", question) if p.strip()]
    return [p for p in (nlparse.parse(part) for part in parts) if p is not None]


async def _try_nl_add(
    question: str, reason: str, emit: Emit, lang: str = "zh"
) -> dict[str, Any] | None:
    """对话内一句话记账：规则解析（无需模型）→ 入账 → 回执（含撤销路径）。

    支持一句多笔（用逗号/顿号/分号/和/及 分隔），逐段独立解析；全部可解析才入账（原子）。
    """
    parsed_all = _nl_segments(question)
    if not parsed_all:
        return None

    for parsed in parsed_all:
        await emit(
            {
                "type": "step",
                "id": "nl",
                "label": "识别记账" if lang == "zh" else "Recording",
                "detail": (
                    f"{parsed['item']} {abs(parsed['amount']):.2f} 元（{parsed['category']}）"
                    if lang == "zh"
                    else f"{parsed['item']} {abs(parsed['amount']):.2f} CNY ({parsed['category']})"
                ),
                "phase": "start",
            }
        )
    # 原子批量入账：任一条失败整体回滚（承诺"全部可解析才入账"的真实实现）
    inserted = await db.add_transactions_batch(
        [
            {
                "date": p["date"],
                "item": p["item"],
                "category": p["category"],
                "amount": p["amount"],
            }
            for p in parsed_all
        ]
    )
    # 对话路径写入后必须让仪表盘缓存失效：否则用户在同一页面问完"记一笔"
    # 切到总览仍看到旧流水（缓存 10 秒，但这 10 秒足够让人以为没记上）。
    from . import analysis as _analysis

    _analysis.invalidate_dashboard_cache()
    if lang == "zh":
        lines = [
            f"{p['date']} {p['item']} {abs(p['amount']):,.2f} 元"
            f"（{p['category']} · {'收入' if p['amount'] > 0 else '支出'}）"
            for p in parsed_all
        ]
        if len(lines) == 1:
            answer = (
                "已记一笔：" + lines[0] + "。\n\n记错了可以在「记账」页删掉这一条。"
            )
        else:
            answer = (
                "已记 "
                + str(len(lines))
                + " 笔：\n"
                + "\n".join("· " + line for line in lines)
                + "\n\n记错了可以在「记账」页删掉。"
            )
    else:
        lines = [
            f"{p['date']} {p['item']} {abs(p['amount']):,.2f} CNY"
            f" ({p['category']} · {'income' if p['amount'] > 0 else 'expense'})"
            for p in parsed_all
        ]
        if len(lines) == 1:
            answer = (
                "Recorded: "
                + lines[0]
                + ".\n\nMade a mistake? Delete it on the Ledger page."
            )
        else:
            answer = (
                "Recorded "
                + str(len(lines))
                + " entries:\n"
                + "\n".join("· " + line for line in lines)
                + "\n\nDelete on the Ledger page if wrong."
            )
    for p in parsed_all:
        await emit(
            {
                "type": "step",
                "id": "nl",
                "label": "已入账",
                "detail": f"{p['category']} {abs(p['amount']):,.2f} 元",
                "phase": "done",
            }
        )
    return {
        "answer": answer,
        "level": "已记账",
        "route": "nl_add",
        "route_reason": (
            f"识别为一句话记账：{reason}"
            if lang == "zh"
            else f"Recognized as one-sentence bookkeeping: {reason}"
        ),
        "metrics": {},
        "flags": [],
        "llm": "template",
        "tx_id": inserted[0]["id"],
    }


def route_question(question: str, lang: str = "zh") -> tuple[str, str]:
    """规则分类（不调模型）：命中目标/体检词 → goal（全量财务路由），命中投资词 → market，
    命中收支词 → ledger，都命中 → both，都不命中 → general。

    宁缺毋滥：不确定是否问财务时一律 general，绝不做「猜测式财务综合分析」。
    reason 为推理轨迹展示文本（route_reason），前端「小满的理解」直接亮给用户看，
    因此用用户能听懂的理财心智语言，而非「命中关键词」的技术说明（差异化「懂钱」）。
    按 lang 本地化。
    """
    en = lang != "zh"
    q = question.lower()
    hit_a = [w for w in ACTION_WORDS if w in q]
    if hit_a:
        if en:
            return "action", "A quick action you asked for — I'll run it directly"
        return "action", f"你想让我直接做的操作（{hit_a[0]}）"
    hit_g = [w for w in GOAL_WORDS if w in q]
    if hit_g:
        if en:
            return (
                "goal",
                "You want a financial health check or to see how a goal is tracking",
            )
        return "goal", f"你想看看财务体检 / 目标进度（{hit_g[0]}）"
    hit_m = [w for w in MARKET_WORDS if w in q]
    hit_l = [w for w in LEDGER_WORDS if w in q]
    if hit_m and hit_l:
        if en:
            return (
                "both",
                "You want both your holdings and your money flows in one picture",
            )
        return "both", f"你想同时看持仓和收支（{hit_m[0]} / {hit_l[0]}）"
    if hit_m:
        if en:
            return (
                "market",
                "You want the current state of your holdings and market quotes",
            )
        return "market", f"你想看持仓盈亏和行情（{hit_m[0]}）"
    if hit_l:
        if en:
            return "ledger", "You want to see income, spending and debt"
        return "ledger", f"你想看这个月的收支和负债（{hit_l[0]}）"
    if en:
        return "general", "Not a finance question — answering in general"
    return "general", "这句不是理财问题，按通用问答回复"


def _looks_like_memory(question: str) -> bool:
    """短句 + 记忆动词 + 无疑问词 → 视为「记住/记得 …」记忆指令。

    与一句话记账同一套保守判定：疑问句（「你还记得吗」）绝不当记忆指令。
    """
    q = question.strip()
    if not q or len(q) > NL_MAX_LEN:
        return False
    if any(m in q for m in QUESTION_MARKS):
        return False
    return any(v in q for v in MEMORY_VERBS)


def _looks_like_watchlist(question: str) -> bool:
    """含「自选」字样（加自选 / 移除自选 / 看自选）→ 归持仓-行情域，绝不进记账解析。

    「把 600519 加入自选」里的 6 位代码会被 nlparse 当成金额（实测 600519 → 走 60 万大额审批），
    必须在记账检测之前拦截。
    """
    return "自选" in question


async def classify_question_llm(question: str, lang: str = "zh") -> str | None:
    """规则未命中时的模型兜底分类：market / ledger / both / goal / general。

    只管「是否理财问题及其域」，宁缺毋滥；模型不可用 / 输出非法一律返回 None（调用方保持 general）。
    """
    system = (
        '你是意图分类器。只输出 JSON：{"route": "market|ledger|both|goal|general"}。'
        "market=股票/基金/持仓/行情/走势/某个标的价格；ledger=收支/记账/预算/负债；"
        "both=同时涉及持仓与收支；goal=财务体检/储蓄目标进度；general=其它（写作/闲聊/编程等）。"
    )
    out = await llm.json_complete(system, question, timeout=12.0)
    if not isinstance(out, dict):
        return None
    route = str(out.get("route") or "").strip().lower()
    return route if route in ("market", "ledger", "both", "goal", "general") else None


async def _try_save_memory(
    question: str, emit: Emit, lang: str = "zh"
) -> dict[str, Any] | None:
    """对话内记忆指令：规则提取内容 → 存长期记忆 → 回执（无需模型）。

    提取「记住/记得」之后的内容；提取不到有效内容（如单独一个「记住」）返回 None。
    技能「长期记忆」在设置中关闭时：不写入，并明确回执（不静默、不冒充已记住）。
    """
    if not _looks_like_memory(question):
        return None
    from . import agent_config

    if not await agent_config.is_skill_enabled("long_memory"):
        return {
            "answer": (
                "长期记忆已在「设置 → Agent 与技能」中关闭，这条我没有记。"
                "需要我记住的话，打开开关后再告诉我一次。"
                if lang == "zh"
                else "Long-term memory is turned off in Settings → Agents & skills, so I didn't save this. "
                "Turn it on and tell me again if you want me to remember it."
            ),
            "level": "",
            "route": "memory",
            "route_reason": (
                "识别为记忆指令，但「长期记忆」技能已关闭"
                if lang == "zh"
                else "Memory instruction, but the long-term memory skill is disabled"
            ),
            "metrics": {},
            "flags": [],
            "llm": "template",
            "memory_deduped": False,
        }
    content = re.sub(
        rf"^(?:帮我|请|麻烦|要|我想)*?(?:{'|'.join(MEMORY_VERBS)})[:：]?",
        "",
        question.strip(),
    ).strip("，。！、 ")
    if len(content) < 2:
        return None

    out = await db.add_memory(content)
    await emit(
        {
            "type": "step",
            "id": "memory",
            "label": "已记住" if lang == "zh" else "Remembered",
            "detail": content[:30] + ("…" if len(content) > 30 else ""),
            "phase": "done",
        }
    )
    if lang == "zh":
        answer = (
            f"好，我记住了：{content}。\n\n"
            "以后涉及相关问题时我会参考它；可在「设置 → 长期记忆」查看或删除。"
        )
        route_reason = "识别为「记住/记得 …」记忆指令，直接存长期记忆"
    else:
        answer = (
            f"Got it — I've remembered: {content}.\n\n"
            "I'll reference it for related questions; view or delete it in Settings → Long-term memory."
        )
        route_reason = (
            "Recognized as a memory instruction — saved directly to long-term memory"
        )
    return {
        "answer": answer,
        "level": "已记住",
        "route": "memory",
        "route_reason": route_reason,
        "metrics": {},
        "flags": [],
        "llm": "template",
        "memory_deduped": out.get("deduped", False),
    }


async def _build_history(
    thread_id: str | None, only_route: str | None = None
) -> list[dict[str, str]]:
    """取本会话最近若干轮问答（时间正序），让助手记得上文。

    only_route="general" 时只取同为通用的轮次：通用 agent 也有对话记忆，
    但财务轮次的内容绝不出机（隐私边界，见 test_general_chat_never_carries_finance_history）。
    未接入模型时直接返回空，避免无意义的 DB 查询。

    长会话压缩：会话轮次超过 SUMMARY_TRIGGER_TURNS 时，先读出已压缩的
    会话摘要（注入为 system 消息），再拼上最近 SUMMARY_KEEP_TURNS 轮完整
    问答（两者都以时间正序排列）——长程上下文保住了，token 又不随轮次膨胀。
    """
    if not thread_id or not await llm.llm_available():
        return []
    summary = await db.get_conversation_summary(thread_id)
    runs = await db.list_runs(thread_id, HISTORY_TURNS)
    if only_route:
        runs = [r for r in runs if (r.get("route") or "") == only_route]
    # 通用分支不注入财务摘要，也不外发财务轮次（隐私边界不变）
    if only_route and summary and summary.get("source") == "llm":
        summary = None
    out: list[dict[str, str]] = []
    if summary and summary.get("summary"):
        out.append(
            {
                "role": "system",
                "content": "本会话较早轮次的浓缩摘要（帮助理解长期上下文，数字一律以本轮数据/工具结果为准）：\n"
                + str(summary["summary"])[:SUMMARY_MAX_CHARS],
            }
        )
    for r in reversed(runs):  # list_runs 是倒序（最新在前），翻成时间正序
        q = str(r.get("question") or "").strip()
        a = str(r.get("answer") or "").strip()
        if q:
            out.append({"role": "user", "content": q[:HISTORY_ANSWER_CHARS]})
        if a:
            out.append({"role": "assistant", "content": a[:HISTORY_ANSWER_CHARS]})
    return out


# ---------------------------------------------------------------------------
# 长会话压缩（异步，SSE 交付后后台跑）：把较早轮次折叠成结构化摘要落库
# ---------------------------------------------------------------------------


def _heuristic_summary(exchanges: list[dict[str, Any]]) -> str:
    """无模型时的启发式摘要：从历史问答里提取关键句子（事实/数字/偏好）。

    从每条旧问答里抽取「含数字 / 含记忆动词 / 问句较短」的用户问题与回答要点，
    拼成一行式要点。不保证语义完整，但能保住「聊过什么、记过什么」的大纲。
    """
    facts: list[str] = []
    for ex in exchanges:
        q = str(ex.get("question") or "").strip()
        a = str(ex.get("answer") or "").strip()
        if not q:
            continue
        # 记忆指令 / 明确结论：整条问题值得留
        if (
            any(v in q for v in MEMORY_VERBS)
            or any(w in q for w in ("体检", "结论", "建议", "记住"))
        ) and len(q) <= 40:
            facts.append(q)
        # 含数字的陈述句（金额/比例/日期）→ 抽出关键片段
        for seg in _split_sentences(a):
            if any(ch.isdigit() for ch in seg) and len(seg) <= 60:
                facts.append(seg.strip("。，！、 "))
                break
    if not facts:
        facts = [
            str(e.get("question") or "").strip()
            for e in exchanges[:3]
            if str(e.get("question") or "").strip()
        ]
    return "；".join(dict.fromkeys(f for f in facts if f))[:SUMMARY_MAX_CHARS]


def _split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"[。；\n]", text) if s.strip()]


async def ensure_session_summary(thread_id: str) -> dict[str, Any] | None:
    """问答落库后调用：若会话轮次超阈值，把较早轮次压缩成摘要落库。

    - 未触发阈值 → 直接返回 None（不做任何写入）。
    - 未接入模型 → 用启发式规则兜底（LLM 可用时优先用模型精炼）。
    - covered_to 记录「已纳入摘要的最新 runs.id」：增量续写，避免每轮全量重算。
    """
    if not thread_id:
        return None
    try:
        # 需取该会话全量轮次判断是否超阈值；不能用 list_runs(…, 0)（SQL LIMIT 0 返回空）
        all_runs = await db.fetch_all(
            "SELECT id, question, answer, route FROM runs WHERE thread_id=? ORDER BY id",
            (thread_id,),
        )
    except Exception:  # noqa: BLE001 — 摘要失败不影响主流程
        return None
    if len(all_runs) <= SUMMARY_TRIGGER_TURNS:
        return None
    # 时间正序；保留最近 K 轮完整，更早轮次纳入摘要
    # 保留最近 K 轮完整；更早轮次纳入摘要
    cover_until_id = (
        all_runs[-SUMMARY_KEEP_TURNS]["id"]
        if len(all_runs) > SUMMARY_KEEP_TURNS
        else all_runs[-1]["id"]
    )
    to_cover = [r for r in all_runs if r["id"] < cover_until_id]
    if not to_cover:
        return None
    prev = await db.get_conversation_summary(thread_id)
    prev_covered = int((prev or {}).get("covered_to") or 0)
    new_exchanges = [r for r in to_cover if r["id"] > prev_covered]
    if not new_exchanges and prev and prev.get("summary"):
        return {"ok": True, "reused": True, "covered_to": prev_covered}

    try:
        summary, source = await _summarize_exchanges(prev, new_exchanges)
    except Exception:  # noqa: BLE001 — 摘要生成失败退化为启发式
        summary, source = _heuristic_summary_with_prev(prev, new_exchanges), "heuristic"
    await db.set_conversation_summary(thread_id, summary, source, cover_until_id)
    return {"ok": True, "source": source, "covered_to": cover_until_id}


async def _summarize_exchanges(
    prev: dict[str, Any] | None, new_exchanges: list[dict[str, Any]]
) -> tuple[str, str]:
    """用 LLM 把（已有摘要 + 新轮次）压缩成一条结构化摘要；失败抛异常由调用方兜底。"""
    if not await llm.llm_available():
        raise RuntimeError("no llm")
    block: list[str] = []
    if prev and prev.get("summary"):
        block.append("【既有摘要】\n" + str(prev["summary"]))
    if new_exchanges:
        block.append("【新增问答】")
        for r in new_exchanges:
            q = str(r.get("question") or "").strip()
            a = str(r.get("answer") or "").strip()
            block.append(f"问：{q}")
            if a:
                block.append(f"答：{a[:200]}")
    sys = (
        "你是长会话压缩器。把用户与理财助手的对话压缩成一段简体中文结构化摘要，"
        "保留：①用户的身份/偏好/财务事实（金额、标的、目标、日期）；②本会话讨论过的"
        "关键问题与结论；③用户让助手记住的内容。要求：不编造、不含口头语、不超过 400 字、"
        "用要点式（每行一条），只输出摘要本身。"
    )
    data = await llm.json_complete(
        sys, "请压缩以下会话：\n\n" + "\n".join(block), timeout=15.0
    )
    text = data.get("summary") if isinstance(data, dict) else None
    if isinstance(text, str) and text.strip():
        return text.strip()[:SUMMARY_MAX_CHARS], "llm"
    # json 里没有 summary 字段时，退化为让模型直接输出文本（兼容不返回 JSON 的端点）
    text = await llm.stream_text_short(
        "请压缩以下会话，只输出一段不超过 400 字的中文摘要：\n\n" + "\n".join(block)
    )
    if text:
        return text[:SUMMARY_MAX_CHARS], "llm"
    raise RuntimeError("summary empty")


def _heuristic_summary_with_prev(
    prev: dict[str, Any] | None, new_exchanges: list[dict[str, Any]]
) -> str:
    """启发式摘要（含既有摘要续写）：已有部分 + 新增部分各提取要点后合并。"""
    parts: list[str] = []
    if prev and prev.get("summary"):
        parts.append(str(prev["summary"]))
    extra = _heuristic_summary(new_exchanges)
    if extra:
        parts.append(extra)
    return "；".join(p for p in parts if p)[:SUMMARY_MAX_CHARS]


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
    async for delta, s in llm.stream_narrate(system, user, fallback):
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
