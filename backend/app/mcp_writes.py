"""MCP 写操作工具：记账、持仓、长期记忆与设置。

从 mcp_server.py 拆出，注册机制不变——本模块在 import 时用 @_tool() 装饰即完成
注册；mcp_server 末尾 `from .mcp_writes import ...` 触发并保留同名属性，
测试与外部仍可通过 mcp_server._confirm_write 访问。
"""

from __future__ import annotations

from typing import Any

try:  # fastmcp 会解析函数签名，注解里的 Context 必须在运行时可见
    from fastmcp import Context
except Exception:  # pragma: no cover — fastmcp 不可用时 MCP 已整体关闭
    Context = Any  # type: ignore[misc,assignment]

from . import db
from . import tools as xtools
from .logging_utils import get_logger
from .mcp_server import _tool

log = get_logger(__name__)

async def _confirm_write(ctx: Any, summary: str, amount: float) -> bool:
    """向客户端请求大额写操作确认；返回 True 表示用户同意。

    非大额直接返回 True（不打扰用户）；客户端不支持 elicitation 时返回 False
    （fail-closed）。
    """
    from . import approval

    if not await approval.needs_approval(amount):
        return True
    if ctx is None:
        log.warning("mcp.approval_no_context: 大额写操作缺少 Context，拒绝执行")
        return False

    from fastmcp.server.elicitation import (
        AcceptedElicitation,
        CancelledElicitation,
        DeclinedElicitation,
    )

    try:
        result = await ctx.elicit(approval.format_approval_prompt(summary, amount))
    except Exception as exc:  # noqa: BLE001 — 客户端不支持 elicitation 等
        log.warning("mcp.approval_failed: %s — 拒绝执行写操作", exc)
        return False

    if isinstance(result, AcceptedElicitation):
        return True
    if isinstance(result, (DeclinedElicitation, CancelledElicitation)):
        return False
    return False


# ---------------------------------------------------------------------------
# 记账 / 记忆工具
# ---------------------------------------------------------------------------


@_tool()
async def record_transaction(text: str, ctx: Context | None = None) -> str:
    """一句话记账：把用户的记账指令（如「昨天打车 32」「工资 8000 已到账」）解析并写入账本。
    金额超过审批阈值时会先请用户确认。"""
    from . import nlparse

    parsed = nlparse.parse(text) or await nlparse.parse_with_ai(text)
    if parsed is None:
        # 交给底层实现给出统一的解析失败提示
        return await xtools.tool_record_transaction({"text": text})
    from . import approval

    summary = approval.describe_transaction(parsed)
    if not await _confirm_write(ctx, summary, float(parsed.get("amount", 0))):
        return "已取消：用户未确认这笔大额记账，账本未改动。"
    return await xtools.tool_record_transaction({"text": text})


@_tool()
async def record_position(symbol: str, shares: float, cost: float, last: float = 0,
                          name: str = "", kind: str = "股票", industry: str = "其他",
                          buy_date: str = "", ctx: Context | None = None) -> str:
    """记录一笔买入持仓。symbol=代码(6位), shares=份额, cost=成本价, last=现价(自动获取可省略)。
    买入金额超过审批阈值时会先请用户确认。"""
    amount = float(shares or 0) * float(cost or 0)
    summary = f"买入 {name or symbol} {shares:g} 份 × {cost:g} 元"
    if not await _confirm_write(ctx, summary, amount):
        return "已取消：用户未确认这笔大额买入，持仓未改动。"
    return await xtools.tool_record_position({
        "symbol": symbol, "shares": shares, "cost": cost, "last": last,
        "name": name, "kind": kind, "industry": industry, "buy_date": buy_date,
    })


@_tool()
async def sell_position(symbol: str, shares: float = 0, ctx: Context | None = None) -> str:
    """卖出/减仓持仓。symbol=代码, shares=份额(省略=全部清仓)。
    卖出金额超过审批阈值时会先请用户确认。"""
    # 卖出金额 = 份额 × 现价；现价取不到时按 0 处理（不触发审批，但底层会拒绝无现价卖出）
    try:
        from .quotes import quote_now

        q = await quote_now(symbol)
        price = float((q or {}).get("price") or 0)
    except Exception:  # noqa: BLE001 — 行情不可用不影响审批判定的降级
        price = 0.0

    # 清仓（shares=0）此前直接算成 0 元，永远不会触发审批——而清仓恰恰是
    # 金额最大、最不可逆的操作。这里用持仓市值兜底：现价缺失时退回成本价。
    effective_shares = float(shares or 0)
    if not effective_shares:
        try:
            rows = await db.list_positions()
        except Exception:  # noqa: BLE001
            rows = []
        pos = next((p for p in rows if p.get("symbol") == symbol), None)
        if pos:
            effective_shares = float(pos.get("shares") or 0)
            if price <= 0:
                price = float(pos.get("last") or pos.get("cost") or 0)
    amount = effective_shares * price
    summary = f"卖出 {symbol} {shares:g} 份" if shares else f"清仓 {symbol}"
    if not await _confirm_write(ctx, summary, amount):
        return "已取消：用户未确认这笔大额卖出，持仓未改动。"
    return await xtools.tool_sell_position({"symbol": symbol, "shares": shares})


@_tool()
async def save_user_memory(content: str) -> str:
    """记住一条用户的长期信息（如「明年计划买房」「每月收入 2 万」）。"""
    return await xtools.tool_save_user_memory({"content": content})


@_tool()
async def get_user_memory(query: str = "", kind: str = "") -> str:
    """查询用户长期记忆。query 关键词检索，kind 类型过滤(fact/preference/goal_related)。"""
    return await xtools.tool_get_user_memory({"query": query, "kind": kind})


@_tool()
async def get_lessons() -> str:
    """查询经验库：之前工具调用的踩坑记录（避免重复犯同样的错误）。"""
    return await xtools.tool_get_lessons({})


@_tool()
async def set_setting(key: str, value: str, lang: str = "zh") -> str:
    """修改应用偏好。key 如 color_scheme/default_tab/lang/compact_numbers 等；
    详细可用键与取值见工具描述。AI 接入配置（ai_base_url/ai_api_key/ai_model）
    一律拒绝，需到设置页修改。"""
    return await xtools.tool_set_setting({"key": key, "value": value}, lang=lang)
