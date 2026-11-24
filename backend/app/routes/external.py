"""外部协同前置包 API（4.20.0）。

三个接口都只读：
- `/api/external/tax-packet`：税务申报核对包；
- `/api/external/payment-packet`：付款指令草稿包；
- `/api/external/consolidation-packet`：管理口径合并审计包。

不提交税局、不发起付款、不出具法定合并意见。需要外部资质的最后一步仍由
用户或持牌机构人工完成。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..db.tenant import current_user_id
from ..external_packets import (
    consolidation_packet as build_consolidation_packet,
)
from ..external_packets import (
    payment_packet as build_payment_packet,
)
from ..external_packets import (
    tax_packet as build_tax_packet,
)
from ._responses import bad as _bad
from .gl import gl_read_scope

router = APIRouter(dependencies=[Depends(get_current_user)])


def _uid() -> int:
    return int(current_user_id())


@router.get("/api/external/tax-packet")
async def tax_packet(period: str = "", scope: int = Depends(gl_read_scope)) -> Any:
    try:
        return await build_tax_packet(scope, period)
    except ValueError as exc:
        return _bad(str(exc))


@router.get("/api/external/payment-packet")
async def payment_packet(period: str = "", scope: int = Depends(gl_read_scope)) -> Any:
    try:
        return await build_payment_packet(scope, period)
    except ValueError as exc:
        return _bad(str(exc))


@router.get("/api/external/consolidation-packet")
async def consolidation_packet(group_id: str = "", period: str = "") -> Any:
    if not group_id:
        return _bad("group_id 必填")
    try:
        return await build_consolidation_packet(_uid(), group_id, period)
    except ValueError as exc:
        return _bad(str(exc), 404 if "不存在" in str(exc) or "无权" in str(exc) else 400)


__all__ = ["router"]
