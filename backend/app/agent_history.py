"""agent 的消息历史压缩：把较早的工具轮次折叠成摘要。

从 agent.py 拆出；折叠阈值仍由传入的 cfg 决定，不做模块级配置。
"""

from __future__ import annotations

from typing import Any

from . import llm
from .logging_utils import get_logger

log = get_logger(__name__)

async def _compress_history(messages: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """长会话上下文压缩（progressive disclosure）。

    当 messages 超过 8 条（含 system+user+assistant+tool），把除最近 4 条外
    的早期历史用一句话摘要替代，防 context window 溢出。
    摘要由 LiteLLM 廉价模型（如 gpt-4o-mini）快速产出。
    """
    if len(messages) <= 8:
        return messages
    # 保底逻辑：保留 system 消息 + 最近 4 轮对话，把中间部分压缩
    # 找到 system 消息数量
    system_count = sum(1 for m in messages if m.get("role") == "system")
    keep_tail = 4  # 保留最近 4 条对话（含 tool 消息）
    if len(messages) - system_count <= keep_tail + 1:
        return messages
    head = messages[: system_count + 1]  # system + 首个 user
    tail = messages[-keep_tail:]  # 最近 4 条
    middle = messages[system_count + 1 : -keep_tail]

    if not middle:
        return messages

    # 用简短提示请模型摘要早期对话
    middle_text = "\n".join(
        f"[{m.get('role', '?')}] {str(m.get('content', ''))[:200]}"
        for m in middle
    )[:2000]

    try:
        summary = await llm.stream_text_short(
            f"把下面多轮对话压缩为一句话摘要（保留关键数据和意图，≤80字）：\n{middle_text}",
            timeout=15.0,
        )
    except Exception:
        summary = None

    if not summary:
        return messages  # 压缩失败不丢数据，原样返回

    compressed = {
        "role": "system",
        "content": f"（前面对话摘要：{summary}）以下是最后的对话：",
    }
    return [*head, compressed, *tail]
