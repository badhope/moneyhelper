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

from .. import db
from ..auth import get_current_user
from ..db.tenant import current_user_id
from ..external_delivery import (
    delete_channel,
    deliver,
    list_channels,
    save_channel,
    test_channel,
)
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


class ChannelIn(BaseModel):
    label: str = ""
    config: dict[str, Any] = {}
    secret: dict[str, Any] | None = None
    enabled: bool = False


class ChannelTestIn(BaseModel):
    config: dict[str, Any] | None = None


class DeliverIn(BaseModel):
    channel_id: str = ""
    kind: str = ""
    period: str = ""
    group_id: str = ""
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
        return _bad(
            str(exc), 404 if "不存在" in str(exc) or "无权" in str(exc) else 400
        )


@router.post("/api/external/handoffs/ack")
async def handoff_ack(body: HandoffAckIn, scope: int = Depends(gl_write_scope)) -> Any:
    try:
        return await acknowledge_handoff(scope, _uid(), body.packet_id, body.note)
    except ValueError as exc:
        return _bad(
            str(exc), 404 if "不存在" in str(exc) or "无权" in str(exc) else 400
        )


@router.get("/api/external/consolidation-packet")
async def consolidation_packet(group_id: str = "", period: str = "") -> Any:
    if not group_id:
        return _bad("group_id 必填")
    try:
        return await build_consolidation_packet(_uid(), group_id, period)
    except ValueError as exc:
        return _bad(
            str(exc), 404 if "不存在" in str(exc) or "无权" in str(exc) else 400
        )


@router.get("/api/external/channels")
async def channels(scope: int = Depends(gl_read_scope)) -> Any:
    return await list_channels()


@router.put("/api/external/channels/{channel_id}")
async def channel_save(
    channel_id: str,
    body: ChannelIn,
    scope: int = Depends(gl_write_scope),
) -> Any:
    try:
        return await save_channel(channel_id, body.model_dump())
    except ValueError as exc:
        return _bad(str(exc))
    except RuntimeError as exc:
        return _bad(str(exc), 409)


@router.delete("/api/external/channels/{channel_id}")
async def channel_delete(channel_id: str, scope: int = Depends(gl_write_scope)) -> Any:
    try:
        return await delete_channel(channel_id)
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/external/channels/{channel_id}/test")
async def channel_test(
    channel_id: str,
    body: ChannelTestIn,
    scope: int = Depends(gl_write_scope),
) -> Any:
    try:
        return await test_channel(channel_id, body.model_dump())
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/external/deliver")
async def delivery_send(body: DeliverIn, scope: int = Depends(gl_write_scope)) -> Any:
    try:
        return await deliver(
            body.channel_id,
            body.kind,
            int(scope),
            _uid(),
            period=body.period,
            group_id=body.group_id,
            note=body.note,
        )
    except ValueError as exc:
        return _bad(str(exc))


@router.get("/api/external/deliveries")
async def deliveries(scope: int = Depends(gl_read_scope)) -> Any:
    return {
        "deliveries": await db.external_list_deliveries(30),
        "stats": await db.external_delivery_stats(),
    }


__all__ = ["router"]
