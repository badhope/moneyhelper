"""取数与风控节点：市场快照、账本汇总、风险标记。

从 agent_graph.py 拆出，供 _build_graph 使用；图谱与状态定义仍在 agent_graph。
"""

from __future__ import annotations

import time
from typing import Any

from . import analysis, db, quotes
from .agent_graph import AgentState, _emit, _now_ms
from .logging_utils import get_logger

log = get_logger(__name__)

async def collect_market(state: AgentState) -> dict[str, Any]:
    """市场 agent：持仓/行情/盈亏/集中度。确定性模式发步骤事件 + 工具调用事件。"""
    if "market" not in (state.get("routes") or []):
        return {}
    det = state.get("mode") == "deterministic"
    if det:
        await _emit(
            {
                "type": "step",
                "id": "market",
                "label": "View holdings" if state.get("lang") == "en" else "查看持仓",
                "detail": "Fetch holdings & quotes, compute P&L and concentration"
                if state.get("lang") == "en"
                else "拉取持仓与行情，计算盈亏与集中度",
                "phase": "start",
            }
        )
        await _emit(
            {
                "type": "tool",
                "data": {
                    "id": "market",
                    "name": "get_market_view",
                    "status": "running",
                    "node": "collect_market",
                    "ts": time.time() * 1000,
                },
            }
        )
    started = time.monotonic()
    positions = await db.list_positions()
    live = await quotes.live_quotes(positions)
    market = analysis.market_view(positions, live)
    duration_ms = int((time.monotonic() - started) * 1000)
    if det:
        en = state.get("lang") == "en"
        summary = (
            f"Market value ¥{market['total_market_value']:,.0f}, {'up' if market['total_pnl'] >= 0 else 'down'} ¥{abs(market['total_pnl']):,.0f}"
            if en
            else f"总市值 {market['total_market_value']:,.0f} 元，累计{'浮盈' if market['total_pnl'] >= 0 else '浮亏'} {abs(market['total_pnl']):,.0f} 元"
        )
        await _emit(
            {
                "type": "tool",
                "data": {
                    "name": "get_market_view",
                    "status": "done",
                    "summary": summary,
                    "duration_ms": duration_ms,
                    "node": "collect_market",
                    "ts": _now_ms(),
                },
            }
        )
        await _emit(
            {
                "type": "step",
                "id": "market",
                "label": "View holdings" if state.get("lang") == "en" else "查看持仓",
                "detail": summary,
                "phase": "done",
            }
        )
    # positions/live 写入 state 供 collect_ledger、finalize 复用（同轮只拉一次）
    return {"market": market, "positions": positions, "live": live}


async def collect_ledger(state: AgentState) -> dict[str, Any]:
    """账本 agent：收支/结余/负债/应急金。确定性模式发步骤事件 + 工具调用事件。"""
    if "ledger" not in (state.get("routes") or []):
        return {}
    det = state.get("mode") == "deterministic"
    if det:
        await _emit(
            {
                "type": "step",
                "id": "ledger",
                "label": "Ledger" if state.get("lang") == "en" else "核对账本",
                "detail": "Income · Expenses · Subscriptions · Debt · Emergency fund"
                if state.get("lang") == "en"
                else "汇总本月收支、订阅、负债与应急金",
                "phase": "start",
            }
        )
        await _emit(
            {
                "type": "tool",
                "data": {
                    "name": "get_ledger_view",
                    "status": "running",
                    "node": "collect_ledger",
                    "ts": _now_ms(),
                },
            }
        )
    started = time.monotonic()
    positions = state.get("positions")
    if positions is None:
        positions = await db.list_positions()
    live = state.get("live")
    if live is None:
        live = await quotes.live_quotes(positions)
    settings = await db.get_settings()
    ledger = analysis.ledger_view(
        await db.list_transactions(),
        await db.list_subscriptions(),
        await db.list_debts(),
        settings,
        positions,
        live,
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    if det:
        en = state.get("lang") == "en"
        summary = (
            f"Net ¥{ledger['net']:,.0f} this month, debt ¥{ledger['debt_monthly']:,.0f}/mo"
            if en
            else f"本月结余 {ledger['net']:,.0f} 元，负债月供 {ledger['debt_monthly']:,.0f} 元"
        )
        await _emit(
            {
                "type": "tool",
                "data": {
                    "name": "get_ledger_view",
                    "status": "done",
                    "summary": summary,
                    "duration_ms": duration_ms,
                    "node": "collect_ledger",
                    "ts": _now_ms(),
                },
            }
        )
        await _emit(
            {
                "type": "step",
                "id": "ledger",
                "label": "Ledger" if state.get("lang") == "en" else "核对账本",
                "detail": summary,
                "phase": "done",
            }
        )
    return {"ledger": ledger}


async def risk(state: AgentState) -> dict[str, Any]:
    """风控 agent：跑规则告警。确定性模式发步骤事件 + 工具调用事件。"""
    det = state.get("mode") == "deterministic"
    if det:
        await _emit(
            {
                "type": "tool",
                "data": {
                    "name": "get_risk_flags",
                    "status": "running",
                    "node": "risk",
                    "ts": _now_ms(),
                },
            }
        )
    started = time.monotonic()
    flags = analysis.risk_checks(
        state.get("market"), state.get("ledger"), state.get("lang", "zh")
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    if det:
        detail = (
            (
                f"Found {len(flags)} item(s) to watch: "
                + "; ".join(f["text"] for f in flags[:2])
                if flags
                else "No significant risks found"
            )
            if state.get("lang") == "en"
            else (
                f"发现 {len(flags)} 项需关注："
                + "；".join(f["text"] for f in flags[:2])
                if flags
                else "未发现明显风险项"
            )
        )
        await _emit(
            {
                "type": "tool",
                "data": {
                    "name": "get_risk_flags",
                    "status": "done",
                    "summary": detail,
                    "duration_ms": duration_ms,
                    "node": "risk",
                    "ts": _now_ms(),
                },
            }
        )
        await _emit(
            {
                "type": "step",
                "id": "risk",
                "label": "Risk review" if state.get("lang") == "en" else "风险复核",
                "detail": detail,
                "phase": "done",
            }
        )
    return {"flags": flags}
