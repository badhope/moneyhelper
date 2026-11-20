"""多轮上下文：历史拼装、长会话压缩与摘要。

从 service.py 拆出；阈值常量随之搬到这里，service 通过导入继续使用同一份。
"""

from __future__ import annotations

import re
from typing import Any

from . import db, llm
from . import service as _service  # 延迟属性访问：MEMORY_VERBS 仍在 service 定义
from .logging_utils import get_logger

# 多轮上下文：最多回看 4 轮，每条截断 400 字（控制 token 与外发体量）
HISTORY_TURNS = 4
HISTORY_ANSWER_CHARS = 400
# 历史消息的 token 上限：为「本轮数据 + 工具结果 + 回答」留出空间。
HISTORY_MAX_TOKENS = 1200

# 长会话压缩：超过阈值后把较早轮次压成摘要落库
SUMMARY_TRIGGER_TURNS = 8
SUMMARY_KEEP_TURNS = 4
SUMMARY_MAX_CHARS = 2000

log = get_logger(__name__)

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
    # 最后一道 token 闸：按轮次压缩只保证「轮数」有界，不保证「token」有界
    # （单轮可能是长报告）。用 tiktoken 精确计量；超预算时优先用 LLM 生成
    # 结构化摘要（目标/事实/待办/约束），模型不可用则退回确定性摘要。
    #
    # 注意：这里会多一次模型调用，但只在「历史确实超预算」时发生；
    # 常规 4 轮对话远低于阈值，不会付这个成本。用 use_llm=False 的旧实现
    # （纯截断）曾在超长会话里丢掉关键结论，得不偿失。
    from .context import compact_messages

    res = await compact_messages(
        out, max_tokens=HISTORY_MAX_TOKENS, lang="zh", use_llm=True
    )
    if res.get("compacted"):
        log.info(
            "history.compacted strategy=%s before=%s after=%s dropped=%s",
            res.get("strategy"), res.get("before_tokens"),
            res.get("after_tokens"), res.get("dropped"),
        )
    return res["messages"]


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
            any(v in q for v in _service.MEMORY_VERBS)
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
