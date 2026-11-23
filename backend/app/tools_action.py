"""确定性动作执行：不依赖模型的卖出/晨报/备份直达路径。

从 tools.py 拆出；`run_action` 仍从 tools 门面导出（agent_nodes_action 与测试都走
`tools.run_action` 属性，补丁打到门面即生效）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import db
from .quotes import quote_now
from .tools import (
    Emit,
    _action_log,
    tool_backup_now,
    tool_set_setting,
    tool_trigger_morning_report,
)

# ---------------------------------------------------------------------------
# 确定性动作执行：不配模型也能在对话里直接执行（卖出/晨报/备份）
# ---------------------------------------------------------------------------
_ACTION_STOP = {"卖出", "卖掉", "清仓", "减仓", "抛售", "全部", "帮我", "一下", "现在", "把"}


async def _create_pending(
    tool_name: str,
    args: dict[str, Any],
    summary: str,
    lang: str,
    emit: Emit | None,
) -> str:
    """登记写类动作为待确认（token 一次性、10 分钟过期）；失败降级为直接执行（不阻塞原路径）。"""
    _action_log.info("PENDING %s args=%s summary=%r", tool_name, json.dumps(args, ensure_ascii=False), summary)
    try:
        out = await db.create_pending_action(tool_name, args, summary, lang)
    except Exception:  # noqa: BLE001 — 待确认登记失败不阻断原动作
        _action_log.exception("PENDING creation failed for %s", tool_name)
        return ""
    if emit is not None:
        await emit({"type": "pending_action", "token": out["token"], "summary": summary})
    _action_log.info("PENDING token=%s tool=%s", out["token"], tool_name)
    return out["token"]


def _match_position_by_name(q: str, positions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """名称匹配持仓：全名命中或任意两字连续命中（跳过动作/虚词/通用公司后缀），用于「清仓茅台」这类说法。

    跳过股份/有限/公司/集团等通用后缀，避免"招商银行"被含"银行"/"公司"的任意问题误匹配。"""
    GENERIC_COMPANY_SUFFIXES = {"股份", "有限", "公司", "集团", "银行", "证券", "保险", "信托", "基金"}
    for p in positions:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        if name in q:
            return p
        for i in range(len(name) - 1):
            bigram = name[i : i + 2]
            if bigram in _ACTION_STOP:
                continue
            if bigram in GENERIC_COMPANY_SUFFIXES:
                continue
            if bigram in q:
                return p
    return None


async def run_action(question: str, lang: str = "zh", *, emit: Emit | None = None) -> dict[str, Any]:
    """对话内确定性动作：卖出/清仓/减仓 → sell_position；晨报 → 生成；备份 → 加密备份。
    返回与记账回执同构的 dict（answer/level/route/…/actions），供 agent 成文与前端跳转。"""
    q = question
    en = lang != "zh"

    if any(w in q for w in ("默认首页", "涨跌颜色", "颜色主题", "换颜色", "切换语言")):
        key, value = None, None
        if "默认首页" in q:
            key = "default_tab"
            vmap = {
                "总览": "overview", "持仓": "holdings", "行情": "market",
                "记账": "ledger", "问ai": "chat", "对话": "chat", "chat": "chat",
                "健康": "health", "体检": "health", "策略": "strategy",
                "研究": "research", "报表": "statements", "复盘": "review",
                "模拟盘": "paper", "连接": "connect", "税": "tax",
                "负债": "debts", "总账": "gl", "报销": "expenses",
                "采购": "procurement", "长任务": "longtask", "银行": "bank",
            }
            for k, v in vmap.items():
                if k in q:
                    value = v
                    break
        elif any(w in q for w in ("涨跌颜色", "颜色主题", "换颜色")):
            key = "color_scheme"
            value = "us" if ("绿涨" in q or "绿色" in q or "us" in q.lower()) else "cn"
        elif "切换语言" in q or "语言" in q:
            key = "lang"
            value = "en" if ("英文" in q or "english" in q.lower() or "en" in q.lower()) else "zh"
        if key and value:
            ans = await tool_set_setting({"key": key, "value": value}, lang)
            return {
                "answer": ans,
                "level": "已执行",
                "route": "action",
                "route_reason": "Settings instruction" if en else "设置指令",
                "metrics": {},
                "flags": [],
                "llm": "tool",
                "tools_used": ["set_setting"],
                "actions": [{"tab": "settings"}],
            }
        return {
            "answer": (
                "I can change these: default home (overview/holdings/market/ledger/chat), color scheme "
                "(red-up/green-down or green-up/red-down), and language (Chinese/English). "
                'E.g. "set default home to holdings" or "green-up".'
                if en
                else "我可以帮你改这些设置：默认首页（总览/持仓/行情/记账/问AI）、涨跌颜色（红涨绿跌/绿涨红跌）、语言（中文/英文）。例如「默认首页改成持仓」「涨跌颜色改成绿涨红跌」。"
            ),
            "level": "需要补充",
            "route": "action",
            "route_reason": "Settings instruction missing parameters" if en else "设置指令参数不足",
            "metrics": {},
            "flags": [],
            "llm": "tool",
            "actions": [{"tab": "settings"}],
        }

    if any(w in q for w in ("买入", "买进", "建仓", "加仓")):
        m = re.search(r"(\d{6})", q)
        symbol = m.group(1) if m else ""
        sm = re.search(r"(\d+)\s*[股份手]", q)
        shares = int(sm.group(1)) if sm else 100
        if not symbol:
            return {
                "answer": (
                    "Buying needs a stock code, e.g. \"buy 600519 100 shares\"."
                    if en
                    else "买入需要告诉我股票代码（例如「买入 600519 100 股」）。"
                ),
                "level": "需要补充",
                "route": "action",
                "route_reason": "Buy instruction missing symbol" if en else "买入指令缺代码",
                "metrics": {},
                "flags": [],
                "llm": "tool",
                "actions": [{"tab": "holdings"}],
            }
        q_ = await quote_now(symbol)
        cost = float((q_ or {}).get("price") or 0)
        if cost <= 0:
            return {
                "answer": (
                    "Couldn't fetch the current price as cost basis — provide a cost, e.g. \"buy 600519 100 shares cost 1250\"."
                    if en
                    else "无法获取当前行情作为成本价，请补充成本价（例如「买入 600519 100 股 成本 1250」）。"
                ),
                "level": "需要补充",
                "route": "action",
                "route_reason": "Buy missing cost price" if en else "买入缺成本",
                "metrics": {},
                "flags": [],
                "llm": "tool",
                "actions": [{"tab": "holdings"}],
            }
        buy_args = {"symbol": symbol, "shares": shares, "cost": cost}
        summary = (
            f"Buy {shares:g} shares of {symbol} (cost {cost:g})"
            if en
            else f"买入 {symbol} {shares:g} 股（成本 {cost:g}）"
        )
        token = await _create_pending("record_position", buy_args, summary, lang, emit)
        return {
            "answer": (
                f"Confirm buy: {summary}? Confirm to execute; valid for 10 minutes."
                if en
                else f"确认买入 {summary}？点确认后执行，10 分钟内有效。"
            ),
            "level": "待确认",
            "route": "action",
            "route_reason": "Buy instruction" if en else "买入指令",
            "metrics": {},
            "flags": [],
            "llm": "tool",
            "tools_used": ["add_position"],
            "actions": [{"tab": "holdings"}],
            "pending_token": token,
            "pending_summary": summary,
        }

    if any(w in q for w in ("卖出", "卖掉", "清仓", "减仓", "抛售")):
        m = re.search(r"(\d{6})", q)
        symbol = m.group(1) if m else ""
        if not symbol:
            matched = _match_position_by_name(q, await db.list_positions())
            if matched:
                symbol = matched["symbol"]
        if not symbol:
            return {
                "answer": (
                    "Sell needs a code (e.g. \"sell 600519\") or a holding name (e.g. \"clear 贵州茅台\")."
                    if en
                    else "卖出需要告诉我代码（例如「卖出 600519」）或持仓名称（例如「清仓贵州茅台」）。"
                ),
                "level": "需要补充",
                "route": "action",
                "route_reason": "Action instruction missing symbol" if en else "动作指令缺代码",
                "metrics": {},
                "flags": [],
                "llm": "tool",
                "actions": [{"tab": "holdings"}],
            }
        sell_args: dict[str, Any] = {"symbol": symbol}
        # 「卖出一半/半仓/减半」= 减仓到剩余一半，不能误清仓
        if re.search(r"一半|半仓|减半", q):
            cur = next((p for p in await db.list_positions() if p["symbol"] == symbol), None)
            if cur:
                sell_args["shares"] = round(cur["shares"] / 2, 4)
        if en:
            summary = f"Sell/clear {symbol}"
            summary += f" ({sell_args['shares']:g} shares)" if "shares" in sell_args else " (all)"
        else:
            summary = (
                f"卖出/清仓 {symbol}"
                + (f"（{sell_args['shares']:g} 份）" if "shares" in sell_args else "（全部）")
            )
        token = await _create_pending("sell_position", sell_args, summary, lang, emit)
        return {
            "answer": (
                f"Confirm sell: {summary}? Confirm to execute; valid for 10 minutes."
                if en
                else f"确认卖出 {summary}？点确认后执行，10 分钟内有效。"
            ),
            "level": "待确认",
            "route": "action",
            "route_reason": "Sell/clear instruction" if en else "卖出/清仓指令",
            "metrics": {},
            "flags": [],
            "llm": "tool",
            "tools_used": ["sell_position"],
            "actions": [{"tab": "holdings"}],
            "pending_token": token,
            "pending_summary": summary,
        }

    if "晨报" in q:
        ans = await tool_trigger_morning_report({}, lang)
        return {
            "answer": ans,
            "level": "已生成",
            "route": "action",
            "route_reason": "Morning report instruction" if en else "晨报指令",
            "metrics": {},
            "flags": [],
            "llm": "tool",
            "tools_used": ["trigger_morning_report"],
            "actions": [{"tab": "overview"}],
        }

    if "备份" in q:
        out = await tool_backup_now({}, lang)
        return {
            "answer": out["answer"],
            "level": "已执行",
            "route": "action",
            "route_reason": "Backup instruction" if en else "备份指令",
            "metrics": {},
            "flags": [],
            "llm": "tool",
            "tools_used": ["backup_now"],
            "actions": [{"tab": "settings"}],
            "passphrase": out["passphrase"],
        }

    return {
        "answer": (
            "I can't run that instruction directly right now. Try: sell a holding (e.g. \"sell 600519\"), "
            'generate today\'s morning report ("generate today\'s report"), or create a backup ("back up").'
            if en
            else "这条指令我暂时还不能直接执行。你可以试试：卖出持仓（如「卖出 600519」）、生成晨报（「生成今日晨报」）或备份（「备份一下」）。"
        ),
        "level": "未识别",
        "route": "action",
        "route_reason": "Action instruction not matched" if en else "动作指令未命中",
        "metrics": {},
        "flags": [],
        "llm": "tool",
        "actions": [],
    }
