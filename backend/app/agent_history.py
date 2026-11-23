"""agent 消息历史压缩：把较早的工具轮次折叠成摘要。

真正的压缩算法在 `context.compact_messages`（token 精确计数 + 安全消息边界）。
这里只做适配，避免 agent.py 与 context.py 各维护一套互不一致的截断规则。
"""

from __future__ import annotations

from typing import Any

from . import context as _context
from .logging_utils import get_logger

log = get_logger(__name__)

async def _compress_history(
    messages: list[dict[str, Any]],
    cfg: dict[str, Any],
    *,
    max_tokens: int | None = None,
) -> list[dict[str, Any]]:
    """按 token 预算压缩消息；未超预算或压缩失败时原样返回。

    必须在工具循环内部调用：进入循环前的 messages 只有 system + 当前问题，
    根本不会超过预算；真正膨胀的是 assistant(tool_calls) / tool 结果链。
    """
    if not messages:
        return messages
    budget = max_tokens or _context.DEFAULT_MAX_TOKENS
    try:
        result = await _context.compact_messages(
            messages,
            max_tokens=budget,
            reserve_recent=8,
            use_llm=True,
        )
    except Exception as exc:  # noqa: BLE001 — 压缩失败绝不能中断问答
        log.warning("agent.context_compact failed: %s", exc)
        return messages
    if result.get("compacted"):
        log.info(
            "agent.context_compact before=%s after=%s dropped=%s strategy=%s",
            result.get("before_tokens"),
            result.get("after_tokens"),
            result.get("dropped"),
            result.get("strategy"),
        )
    return result["messages"]
