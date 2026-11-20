"""MCP 账单分类与券商通道工具。

从 mcp_server.py 拆出，import 即用 @_tool() 注册；mcp_server 末尾再导入本模块，
既触发注册也保留原有同名属性。
"""

from __future__ import annotations

from . import tools as xtools
from .logging_utils import get_logger
from .mcp_server import _tool

log = get_logger(__name__)

@_tool()
async def categorize_bills(rows: list) -> str:
    """账单智能归类：按规则引擎给交易打分类，返回命中规则与兜底比例。"""
    return await xtools.tool_categorize_bills({"rows": rows})


@_tool()
async def broker_status() -> str:
    """券商执行层状态：交易开关、dry-run、适配器可用性与缺失项。"""
    return await xtools.tool_broker_status({})


@_tool()
async def broker_preview_order(symbol: str, side: str, quantity: int, limit_price: float) -> str:
    """券商下单预检：跑全部护栏，返回放行结果与确认令牌（默认 dry-run 不下单）。"""
    return await xtools.tool_broker_preview_order(
        {"symbol": symbol, "side": side, "quantity": quantity, "limit_price": limit_price}
    )


@_tool()
async def broker_submit_order(symbol: str, side: str, quantity: int, limit_price: float,
                              confirmation_token: str = "") -> str:
    """券商报单：需预检令牌；默认 dry-run 只返回模拟结果。"""
    return await xtools.tool_broker_submit_order({
        "symbol": symbol, "side": side, "quantity": quantity,
        "limit_price": limit_price, "confirmation_token": confirmation_token,
    })


@_tool()
async def invoice_vision_status() -> str:
    """探测发票识别能力：二维码 / OCR / PDF 表格。"""
    return await xtools.tool_invoice_vision_status({})
