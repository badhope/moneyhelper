"""一句话记账与记忆写入：切段解析、原子入账、长期记忆回执。"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from . import db, nlparse
from .routing_intent import _looks_like_memory, _looks_like_record
from .routing_vocab import MEMORY_VERBS

Emit = Callable[[dict[str, Any]], Awaitable[None]]

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
