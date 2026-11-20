"""路由意图判定：财务词、企业取数问法、追问承接、记账/记忆/自选识别、审批回执归类。"""

from __future__ import annotations

import re
from typing import Any  # noqa: F401

from . import db, llm
from .routing_vocab import (
    _CANCEL_REPLIES,
    _CONFIRM_REPLIES,
    ACTION_WORDS,  # noqa: F401
    DATA_QUESTION_MARKS,
    ENTERPRISE_STRONG_WORDS,
    ENTERPRISE_WEAK_WORDS,
    FOLLOWUP_MARKS,
    FOLLOWUP_MAX_LEN,
    LEDGER_WORDS,
    MARKET_WORDS,
    MEMORY_VERBS,
    NL_MAX_LEN,
    QUESTION_MARKS,
)


def _has_finance_word(text: str) -> bool:
    q = text.lower()
    return any(w in q for w in MARKET_WORDS) or any(w in q for w in LEDGER_WORDS)


def _looks_like_enterprise_data_question(text: str, strong_only: bool = False) -> bool:
    """企业域名词 + 疑问/取数句式才判为查数据。

    单命中业务名词不成立：「帮我写个报销制度」含「报销」但不该去查库；
    「报销流程怎么走」是新用户咨询流程，也要留给通用分支。两者都带疑问词，
    所以再加一层「取数意图」——问数量/状态/清单/进度，或显式「看看/查一下」。

    strong_only=True 时只看强词（不含「报销」）。路由顺序依赖这一点：
    强词判定放在账本之前（否则「总账」会被 LEDGER_WORDS 的「账」抢走），
    弱词放在账本之后（否则「我这个月报销花了多少」会被误判成查企业数据）。
    """
    q = text.lower()
    words = ENTERPRISE_STRONG_WORDS if strong_only else (
        ENTERPRISE_STRONG_WORDS + ENTERPRISE_WEAK_WORDS
    )
    # 兜底组合：明确说「公司/组织/团队」+ 人数/编制类问法，也算企业域
    # （「公司一共有多少人」没有业务名词，只靠词表会漏）。
    # 必须同时有主体词，避免「我家一共有多少人」这类个人问题被抢走。
    org_subject = any(w in q for w in ("公司", "企业", "组织", "团队", "全公司"))
    headcount = any(w in q for w in ("多少人", "几个人", "人数", "编制", "人头"))
    if org_subject and headcount:
        return True
    if not any(w in q for w in words):
        return False
    return any(m in q for m in DATA_QUESTION_MARKS)


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
