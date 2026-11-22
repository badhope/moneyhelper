"""agent 的工具面：只读白名单、通用技能包、轮次上限与工具结果摘要。

从 agent.py 拆出。「模型能执行什么」由这里的白名单唯一决定，集中一处便于审计。
"""

from __future__ import annotations

import json
from typing import Any

from . import tool_policy as _policy
from . import tools
from .logging_utils import get_logger

log = get_logger(__name__)

WRITE_EXCLUDED = {
    n for n in tools.TOOL_IMPL
    if _policy.resolve(n) != _policy.READ
}

READ_TOOLS = [
    t for t in tools.TOOLS
    if _policy.resolve(t["function"]["name"]) == _policy.READ
]

ALLOWED_IMPL = {
    n: tools.TOOL_IMPL[n]
    for n in {t["function"]["name"] for t in READ_TOOLS}
    if n in tools.TOOL_IMPL
}

GENERAL_TOOLS: list[dict[str, Any]] = tools.GENERAL_TOOLS

GENERAL_IMPL: dict[str, Any] = tools.GENERAL_IMPL

MAX_TURNS = 5

def _tool_summary(name: str, result_text: str) -> str:
    """给前端的工具结果摘要（简短、可读）。"""
    try:
        data = json.loads(result_text)
    except Exception:  # noqa: BLE001
        return result_text[:80]
    if name == "get_market_view":
        if not isinstance(data, dict):
            return result_text[:80]
        return f"总市值 {data.get('total_market_value', 0):,} 元，累计盈亏 {data.get('total_pnl', 0):,} 元"
    if name == "get_ledger_view":
        if not isinstance(data, dict):
            return result_text[:80]
        return f"{data.get('month', '')} 收入 {data.get('income', 0):,}、支出 {data.get('expense', 0):,}、结余 {data.get('net', 0):,}"
    if name == "get_risk_flags":
        if not isinstance(data, dict):
            return result_text[:80]
        return f"发现 {data.get('count', 0)} 项需关注"
    if name == "get_financial_identity":
        if not isinstance(data, dict):
            return result_text[:80]
        return f"身份证 {data.get('fingerprint', '')}，净资产 {data.get('financials', {}).get('net_worth', 0):,}"
    if name == "get_monthly_review":
        if not isinstance(data, dict):
            return result_text[:80]
        return f"{data.get('month', '')} 结余 {data.get('cashflow', {}).get('net', 0):,}，动作 {len(data.get('actions', []))} 条"
    if name == "get_budget":
        if not isinstance(data, dict):
            return result_text[:80]
        return f"{data.get('month', '')} 支出 {data.get('total_spent', 0):,} / 预算 {data.get('total_budget', 0):,}"
    if name == "get_trend":
        n = len(data) if isinstance(data, list) else 0
        return f"已取近 {n} 个月趋势"
    if name == "record_transaction":
        if not isinstance(data, dict):
            return result_text[:80]
        return f"已入账：{data.get('item', '')} {data.get('amount', 0):,} 元（{data.get('category', '')}）"
    if name == "get_kline":
        if not isinstance(data, dict):
            return result_text[:80]
        n = len(data.get("points", [])) if isinstance(data, dict) else 0
        return f"已取 {data.get('symbol', '')} {n} 个K线点"
    if name == "get_goals":
        if isinstance(data, dict) and data.get("empty"):
            return "暂无财务目标"
        if isinstance(data, list):
            parts = [f"{g.get('name', '')} {g.get('pct', 0)}%" for g in data[:3]]
            return "目标进度：" + "、".join(parts)
        return result_text[:80]
    if name == "get_user_memory":
        if isinstance(data, dict) and data.get("empty"):
            return "暂无长期记忆"
        if isinstance(data, list):
            return f"共 {len(data)} 条记忆"
        return result_text[:80]
    if name == "save_user_memory":
        return "已记住" if data.get("ok") else "记忆未保存"
    if name == "get_health_check":
        return f"体检综合评分 {data.get('score', 0)} 分，{data.get('summary', '')}"
    return result_text[:80]
