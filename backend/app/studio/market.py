"""市场目录：内置可一键安装的开源 skill / agent / MCP 预设。

目录本身离线可用（随仓库分发）；「安装」只把对应条目写入本地配置，
不联网、不执行第三方代码。远程安装（URL）单独走 API，失败会明确报错。
"""

from __future__ import annotations

import copy
from typing import Any

MARKET_ITEMS: tuple[dict[str, Any], ...] = (
)


def catalog() -> list[dict[str, Any]]:
    return [copy.deepcopy(item) for item in MARKET_ITEMS]


def find(item_id: str) -> dict[str, Any] | None:
    for item in MARKET_ITEMS:
        if item["id"] == item_id:
            return copy.deepcopy(item)
    return None


def categories() -> list[str]:
    seen: list[str] = []
    for item in MARKET_ITEMS:
        if item["category"] not in seen:
            seen.append(item["category"])
    return seen

from .market_items_agents import ITEMS as _AGENTS  # noqa: E402
from .market_items_extras import ITEMS as _EXTRAS  # noqa: E402
from .market_items_mcp import ITEMS as _MCP  # noqa: E402
from .market_items_skills import ITEMS as _SKILLS  # noqa: E402 — 纯数据模块

# 顺序与原单文件一致：技能 → 角色/规则 → MCP → 规则/提示词/Hook
MARKET_ITEMS: tuple[dict[str, Any], ...] = (*_SKILLS, *_AGENTS, *_MCP, *_EXTRAS)

