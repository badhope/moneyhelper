"""Agent 流式输出与时钟：最终回答的流式生成，失败退回非流式兜底。"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from .agent_errors import AgentUnavailable

Emit = Callable[[dict[str, Any]], Awaitable[None]]

def _now_ms() -> int:
    return int(time.time() * 1000)




async def _stream_final_answer(
    client: Any,
    cfg: dict[str, Any],
    messages: list[dict[str, Any]],
    tool_schemas: list[dict[str, Any]],
    emit: Emit,
    timeout: float = 120.0,
) -> str:
    """流式生成最终回答。返回完整文本；失败时退回非流式兜底。"""
    full_parts: list[str] = []
    try:
        stream = await client.chat.completions.create(
            model=cfg["model"] or "gpt-4o-mini",
            messages=messages,
            tools=tool_schemas,
            tool_choice="auto",
            temperature=0.2,
            stream=True,
            timeout=timeout,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                full_parts.append(delta)
                # 逐 token 流式推送前端
                await emit({
                    "type": "token",
                    "data": {"content": delta},
                    "node": "finalize",
                })
    except Exception:
        # 流式失败时退回非流式兜底
        try:
            resp = await client.chat.completions.create(
                model=cfg["model"] or "gpt-4o-mini",
                messages=messages,
                tools=tool_schemas,
                tool_choice="auto",
                temperature=0.2,
                stream=False,
            )
            content = (resp.choices[0].message.content or "").strip()
            if content:
                # 一次性推出去（没有逐 token 的流式，但内容完整）
                await emit({
                    "type": "token",
                    "data": {"content": content},
                    "node": "finalize",
                })
                return content
        except Exception as exc:
            raise AgentUnavailable(f"模型最终成文失败：{type(exc).__name__}") from exc
        return ""

    return "".join(full_parts).strip()
