"""Agent 轮次辅助：重复调用守卫、终答收束与轮次用尽后的兜底成文。

从 agent.py 拆出（`run_agent` 仍是单一边编排循环，此处只承接自包含小件）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .agent_errors import AgentUnavailable
from .agent_stream import Emit
from .agent_studio import studio_post_answer


def _wrapup_budget() -> float:
    """收尾成文预算：跟着 LLM_TIMEOUT 缩放，夹在 [20, 90] 秒。"""
    from .llm_client import llm_timeout

    return max(20.0, min(90.0, llm_timeout() / 3))


class RepeatGuard:
    """同工具 + 同参数连续重复守卫：返回该调用的连续次数，达上限即叫停。"""

    def __init__(self, max_repeat: int = 3) -> None:
        self.max_repeat = max_repeat
        self._key: tuple[str, str] | None = None
        self._count = 0

    def hit(self, name: str, args: dict[str, Any]) -> int:
        key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False, default=str))
        if key == self._key:
            self._count += 1
        else:
            self._key, self._count = key, 1
        return self._count

    def exhausted(self, count: int) -> bool:
        return count >= self.max_repeat


async def final_answer_result(
    client: Any,
    cfg: dict[str, Any],
    messages: list[dict[str, Any]],
    tool_schemas: Any,
    emit: Emit,
    *,
    steps: list[dict[str, Any]],
    used_tools: list[str],
    tool_counts: dict[str, int],
) -> dict[str, Any]:
    """模型不再调工具时：流式出终答并收口 Studio Hook，返回统一结果结构。"""
    from . import (
        agent as _facade,  # 门面取流式实现：测试替换 `agent._stream_final_answer` 生效
    )

    # 终答必须关掉工具面：否则部分模型会把「再搜一次」写成正文里的 XML
    # <tool_call>…</tool_call>，前端直接展示成乱码（联网搜索开启时实测出现）。
    full_answer = await _facade._stream_final_answer(  # noqa: SLF001
        client, cfg, messages, None, emit
    )
    if not full_answer:
        raise AgentUnavailable("模型未产出回答")
    await studio_post_answer(full_answer)
    return {
        "answer": full_answer,
        "steps": steps,
        "tools_used": used_tools,
        "tool_counts": tool_counts,
        "llm": "llm",
    }


async def wrap_up_answer(
    client: Any,
    cfg: dict[str, Any],
    messages: list[dict[str, Any]],
    emit: Emit,
    *,
    steps: list[dict[str, Any]],
    max_turns: int,
) -> dict[str, Any]:
    """工具轮次用尽：再给一次「禁止调工具」的收尾请求，失败则抛降级。"""
    wrap_up = [
        *messages,
        {
            "role": "system",
            "content": "工具调用轮次已用尽。请基于上面已经拿到的工具结果直接回答，不要再请求调用工具；"
            "如果信息不足，就说明缺少什么。",
        },
    ]
    # 收尾预算：云端 60s 超时下仍是 20s（用户已经等了一会儿，再挂两分钟不如
    # 立刻给确定性模板）；本机慢模型把 LLM_TIMEOUT 调到 240s，20s 根本不够生成
    # 一段收尾话，实测直接变成"模型未产出回答"。所以按总超时的 1/3 缩放。
    budget = _wrapup_budget()
    from . import agent as _facade  # 同上：门面取，保证测试替换生效

    try:
        final = await asyncio.wait_for(
            _facade._stream_final_answer(  # noqa: SLF001
                client, cfg, wrap_up, None, emit, timeout=budget
            ),
            timeout=budget + 5.0,
        )
    except (Exception, asyncio.TimeoutError):  # noqa: BLE001 — 收尾失败走调用方降级
        final = ""
    if final:
        return {
            "answer": final,
            "steps": steps,
            "tools_used": sorted({s["name"] for s in steps}),
            "llm": "llm",
        }
    raise AgentUnavailable(f"工具循环超过 {max_turns} 轮未收敛")
