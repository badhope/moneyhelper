"""Studio Hook 入口：pre_tool 拦截与 post_answer 审计。

配置异常时放行/静默——Hook 失败不阻断正常工具与回答，安全默认由内置 Hook 保证。
"""

from __future__ import annotations

from typing import Any


async def studio_pre_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Studio pre_tool Hook 的统一入口（配置异常时放行，安全默认由内置 Hook 保证）。"""
    try:
        from .studio import store as studio_store

        return await studio_store.run_pre_tool(name, args)
    except Exception:  # noqa: BLE001 — Hook 失败不阻断正常工具
        return {"blocked": False, "reason": "", "events": []}


async def studio_post_answer(answer: str) -> list[dict[str, Any]]:
    """Studio post_answer Hook：只做审计/告警，不修改回答内容。"""
    try:
        from .studio import store as studio_store

        return await studio_store.run_post_answer(answer)
    except Exception:  # noqa: BLE001
        return []
