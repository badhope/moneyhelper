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
        return await _non_stream_answer(client, cfg, messages, tool_schemas, emit, strict=True)

    text = "".join(full_parts).strip()
    if text:
        return text
    # 本机小模型偶发"流式一个 token 都不吐、非流式却有完整回答"：直接抛
    # AgentUnavailable 会让用户看到"模型未产出回答"，其实模型答得出来。
    return await _non_stream_answer(client, cfg, messages, tool_schemas, emit, strict=False)


async def _non_stream_answer(
    client: Any,
    cfg: dict[str, Any],
    messages: list[dict[str, Any]],
    tool_schemas: list[dict[str, Any]],
    emit: Emit,
    *,
    strict: bool,
) -> str:
    """非流式兜底成文；strict=False 表示"流式已空"，失败也只需返回空串。"""
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
    except Exception as exc:
        if strict:
            raise AgentUnavailable(f"模型最终成文失败：{type(exc).__name__}") from exc
        return ""
    if content:
        # 一次性推出去（没有逐 token 的流式，但内容完整）
        await emit({
            "type": "token",
            "data": {"content": content},
            "node": "finalize",
        })
    return content
