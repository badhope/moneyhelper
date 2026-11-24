"""外部协同前置包 API（4.20.0 / 交接留档 4.21.0）。

三个只读包：
- `/api/external/tax-packet`：税务申报核对包；
- `/api/external/payment-packet`：付款指令草稿包；
- `/api/external/consolidation-packet`：管理口径合并审计包。

两个交接动作（4.21.0）：
- `/api/external/handoffs`：台账 / 生成并留档；
- `/api/external/handoffs/ack`：确认已线下交接。

不提交税局、不发起付款、不出具法定合并意见。需要外部资质的最后一步仍由
用户或持牌机构人工完成。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import get_current_user
from ..db.tenant import current_user_id
from ..external_handoffs import (
    acknowledge_handoff,
    archive_handoff,
    handoff_records,
)
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
from .gl import gl_read_scope, gl_write_scope

router = APIRouter(dependencies=[Depends(get_current_user)])


class HandoffIn(BaseModel):
    kind: str = ""
    period: str = ""
    group_id: str = ""
    note: str = ""


class HandoffAckIn(BaseModel):
    packet_id: str = ""
    note: str = ""


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


@router.get("/api/external/handoffs")
async def handoffs(limit: int = 20, scope: int = Depends(gl_read_scope)) -> Any:
    return await handoff_records(scope, limit)


@router.post("/api/external/handoffs")
async def archive(body: HandoffIn, scope: int = Depends(gl_write_scope)) -> Any:
    try:
        return await archive_handoff(
            scope, _uid(), body.kind, body.period, body.group_id, body.note
        )
    except ValueError as exc:
        return _bad(str(exc), 404 if "不存在" in str(exc) or "无权" in str(exc) else 400)


@router.post("/api/external/handoffs/ack")
async def handoff_ack(body: HandoffAckIn, scope: int = Depends(gl_write_scope)) -> Any:
    try:
        return await acknowledge_handoff(scope, _uid(), body.packet_id, body.note)
    except ValueError as exc:
        return _bad(str(exc), 404 if "不存在" in str(exc) or "无权" in str(exc) else 400)


@router.get("/api/external/consolidation-packet")
async def consolidation_packet(group_id: str = "", period: str = "") -> Any:
    if not group_id:
        return _bad("group_id 必填")
    try:
        return await build_consolidation_packet(_uid(), group_id, period)
    except ValueError as exc:
        return _bad(str(exc), 404 if "不存在" in str(exc) or "无权" in str(exc) else 400)


__all__ = ["router"]
