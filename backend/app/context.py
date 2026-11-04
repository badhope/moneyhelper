# -*- coding: utf-8 -*-
"""上下文工程 —— token 精确计量 + LLM 摘要式压缩。

为什么要重写：原实现叫「摘要化」，实际是把旧消息每条截前 100 字拼起来。
那既不是摘要（丢失因果关系），又不可控（100 字对长对话几乎等于没留信息），
还会把 assistant 的结论和 user 的追问拼成互不相干的碎片。业界做法
（Claude Agent SDK 的 auto-compact、Cline 的 auto-compact、LangGraph 的
SummarizationNode）都是**用模型生成结构化摘要**，并保留最近若干轮原文。

设计（对齐业界，且能在无模型时退化）：
  1. 先按 token 预算判断是否需要压缩（tiktoken 精确计数）；
  2. 需要压缩时，把旧消息交给模型生成结构化摘要（目标/已确认事实/待办/约束）；
  3. 摘要作为 system message 插入，保留最近 N 条原文；
  4. 模型不可用/失败 → 退回确定性摘要（关键信息优先，而不是等长截断）；
  5. 压缩动作本身可观测：返回 CompactionResult 说明压缩前后 token 与是否降级。

不做的事：不在这里做检索（RAG）——对话是线性的，摘要比向量检索更贴合。
"""

from __future__ import annotations

import tiktoken

from .logging_utils import get_logger

log = get_logger(__name__)

_enc: tiktoken.Encoding | None = None

# 触发压缩的默认阈值：低于此值不值得为摘要付一次模型调用
DEFAULT_MAX_TOKENS = 6000
# 压缩后必须给「最近原文」留的条数：太少会让模型失去当前任务上下文
DEFAULT_RESERVE_RECENT = 6
# 单条消息进摘要时的最大保留长度（防某条超长把摘要 prompt 撑爆）
_PER_MSG_CLIP = 1200


def _get_enc() -> tiktoken.Encoding:
    global _enc
    if _enc is None:
        _enc = tiktoken.get_encoding("cl100k_base")
    return _enc


def count_tokens(text: str) -> int:
    """精确计算一段文本的 token 数（tiktoken，OpenAI 官方 BPE）。"""
    if not text:
        return 0
    return len(_get_enc().encode(text))


def count_messages_tokens(messages: list[dict]) -> int:
    """计算一组 messages 的总 token 数（含每条 role 的固定开销）。"""
    total = 0
    for m in messages:
        total += 4
        total += count_tokens(str(m.get("content", "")))
    return total


def _clip(text: str, limit: int = _PER_MSG_CLIP) -> str:
    s = str(text or "").strip()
    return s if len(s) <= limit else s[:limit] + "…"


def _role_label(role: str, lang: str) -> str:
    if lang == "zh":
        return {"user": "用户", "assistant": "助手", "system": "系统", "tool": "工具"}.get(role, role)
    return {"user": "User", "assistant": "Assistant", "system": "System", "tool": "Tool"}.get(role, role)


def deterministic_summary(old: list[dict], lang: str = "zh") -> str:
    """无模型时的确定性摘要：按「问题 → 结论」成对压缩，而不是等长截断。

    取舍：确定性版本**不试图总结推理过程**（做不到就别假装），
    只保留可核对的事实骨架：用户问过什么、助手给了什么结论。
    """
    zh = lang == "zh"
    user_turns: list[str] = []
    assistant_turns: list[str] = []
    for m in old:
        role = str(m.get("role") or "")
        content = _clip(m.get("content", ""), 300)
        if not content:
            continue
        if role == "user":
            user_turns.append(content)
        elif role == "assistant":
            assistant_turns.append(content)

    lines: list[str] = ["【历史对话摘要】" if zh else "【Conversation summary】"]
    if user_turns:
        lines.append("用户关心过：" if zh else "User asked about:")
        lines.extend(f"- {t}" for t in user_turns[-6:])
    if assistant_turns:
        lines.append("已给出的结论：" if zh else "Conclusions given:")
        lines.extend(f"- {t}" for t in assistant_turns[-6:])
    if not user_turns and not assistant_turns:
        lines.append("（早期消息无可提取内容）" if zh else "(no extractable content in earlier turns)")
    return "\n".join(lines)


async def llm_summary(old: list[dict], lang: str = "zh") -> str | None:
    """用模型生成结构化摘要；模型不可用或失败返回 None（由调用方降级）。

    摘要 prompt 刻意要求四类信息：目标、已确认事实、未完成事项、约束。
    这是 Claude SDK / Cline 的 compact prompt 的核心结构——只保留
    「继续对话所必需」的东西，而不是复述全文。
    """
    try:
        from . import llm
    except Exception:  # noqa: BLE001 — 模型层缺失，直接降级
        return None

    zh = lang == "zh"
    transcript = "\n".join(
        f"{_role_label(str(m.get('role') or ''), lang)}: {_clip(m.get('content', ''))}"
        for m in old
        if str(m.get("content") or "").strip()
    )
    if not transcript:
        return None

    # 复用项目已有的单次完成接口（stream_text_short），不再自造 llm.complete。
    requirement = (
        "必须保留：1) 用户的目标与偏好；2) 已确认的事实与关键数字（含单位）；"
        "3) 尚未完成的待办；4) 任何约束或禁忌。不要复述寒暄，不要编造未出现的事实。"
        "用要点列表，总长不超过 300 字。"
        if zh
        else "Keep: 1) user goals and preferences; 2) confirmed facts and key numbers with units; "
        "3) open todos; 4) constraints. No small talk, no invention. Bullets, under 200 words."
    )
    prompt = requirement + chr(10) + chr(10) + "--- transcript ---" + chr(10) + transcript
    try:
        out = await llm.stream_text_short(prompt, timeout=25.0)
    except Exception as e:  # noqa: BLE001 — 摘要失败不能影响主流程
        log.warning("context.llm_summary failed: %s", e)
        return None
    text = str(out or "").strip()
    return text or None


class CompactionResult(dict):
    """压缩结果（dict 子类便于直接进事件流，同时带属性访问）。"""

    @property
    def messages(self) -> list[dict]:
        return self["messages"]


async def compact_messages(
    messages: list[dict],
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    reserve_recent: int = DEFAULT_RESERVE_RECENT,
    lang: str = "zh",
    use_llm: bool = True,
) -> CompactionResult:
    """按 token 预算压缩对话历史，返回新 messages 与压缩元信息。

    返回的 dict 结构（可序列化，直接进 SSE 事件）：
      messages      —— 压缩后的消息列表
      compacted     —— 是否真的压缩了
      before_tokens / after_tokens
      dropped       —— 被折叠的原始消息条数
      strategy      —— "llm" | "deterministic" | "none"
    """
    before = count_messages_tokens(messages)
    if before <= max_tokens:
        return CompactionResult(
            messages=messages, compacted=False, before_tokens=before,
            after_tokens=before, dropped=0, strategy="none",
        )

    system_msgs = [m for m in messages if m.get("role") == "system"]
    other = [m for m in messages if m.get("role") != "system"]
    if len(other) <= reserve_recent:
        # 条数不多但单条很长：原样返回（避免把当前上下文切碎）
        return CompactionResult(
            messages=messages, compacted=False, before_tokens=before,
            after_tokens=before, dropped=0, strategy="none",
        )

    old, kept = other[:-reserve_recent], other[-reserve_recent:]

    summary: str | None = None
    strategy = "deterministic"
    if use_llm:
        summary = await llm_summary(old, lang)
        if summary:
            strategy = "llm"
    if not summary:
        summary = deterministic_summary(old, lang)

    compacted_msgs = [
        *system_msgs,
        {"role": "system", "content": summary},
        *kept,
    ]
    after = count_messages_tokens(compacted_msgs)
    log.info(
        "context.compact strategy=%s before=%s after=%s dropped=%s",
        strategy, before, after, len(old),
    )
    return CompactionResult(
        messages=compacted_msgs,
        compacted=True,
        before_tokens=before,
        after_tokens=after,
        dropped=len(old),
        strategy=strategy,
        summary=summary,
    )


def trim_messages(
    messages: list[dict],
    max_tokens: int = DEFAULT_MAX_TOKENS,
    reserve_recent: int = DEFAULT_RESERVE_RECENT,
) -> list[dict]:
    """同步裁剪（保留旧签名给不依赖模型的调用方）。

    仅做确定性摘要，不调用模型——需要模型摘要请用 async compact_messages。
    """
    total = count_messages_tokens(messages)
    if total <= max_tokens:
        return messages
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other = [m for m in messages if m.get("role") != "system"]
    if len(other) <= reserve_recent:
        return messages
    old, kept = other[:-reserve_recent], other[-reserve_recent:]
    return [*system_msgs, {"role": "system", "content": deterministic_summary(old)}, *kept]
