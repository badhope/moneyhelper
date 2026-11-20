"""MCP resources：定时产出、调度状态与系统提示。

import 时 @mcp.resource() 即注册，依赖 mcp_server 里的 mcp 实例（末尾 import 触发）。
"""

from __future__ import annotations

from typing import Any

try:  # fastmcp 会解析函数签名，注解里的 Context 必须在运行时可见
    from fastmcp import Context
except Exception:  # pragma: no cover — fastmcp 不可用时 MCP 已整体关闭
    Context = Any  # type: ignore[misc,assignment]

import json

from . import db
from .mcp_server import mcp


@mcp.resource("moneyhelper://scheduled-outputs")
async def scheduled_outputs_resource() -> str:
    """最近的定时产出（晨报 + 技能触发），供 MCP 客户端主动拉取。

    为什么用 resource 而不是 Tasks：MCP 的 Tasks（长任务推送）在 mcp 1.30 仍属
    experimental，fastmcp 2.x 未透传，落地要绕开框架直接用 lowlevel server。
    而"客户端能拿到定时产出"这个真实需求，用 resource 拉取即可满足——
    客户端按自己的节奏刷新，服务端由既有 APScheduler 负责生成。
    """
    rows = await db.list_scheduled_runs(10)

    items = [
        {
            "thread_id": r.get("thread_id"),
            "question": r.get("question"),
            "answer": r.get("answer"),
            "level": r.get("level"),
            "created_at": r.get("created_at"),
        }
        for r in rows
    ]
    return json.dumps(
        {"count": len(items), "items": items},
        ensure_ascii=False,
        indent=1,
    )

@mcp.resource("moneyhelper://scheduler-status")
async def scheduler_status_resource() -> str:
    """定时任务状态（晨报开关、下次运行时间、上次错误）。"""
    from . import scheduler

    return json.dumps(scheduler.status(), ensure_ascii=False, indent=1)

@mcp.resource("moneyhelper://system-prompt")
def system_prompt_resource() -> str:
    """Moneyhelper 系统提示词：描述工具集和 Agent 行为规则。"""
    return (
        "你是 Moneyhelper(moneyhelper)财务 Agent，通过 MCP 工具访问用户的本地财务数据。\n"
        "规则：\n"
        "1. 需要数字时必须调用工具获取，绝不编造\n"
        "2. 先给一句话结论，再列关键数字，最后风险项\n"
        "3. 不给具体买卖指令\n"
        "4. 工具失败时如实说明\n"
        "5. 涉及用户背景先查 get_user_memory"
    )
