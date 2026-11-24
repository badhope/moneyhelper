"""外部交接留档（4.21.0）。

交接包本身不落业务表：留档只写 `audit_logs` 的哈希链，记录“谁在什么时候
把哪份包交给谁”，不改账、不新增表。线下交接由用户显式确认，状态只到
`handed_over`，永远不会出现 `submitted` 或 `paid`。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import db
from .external_packets import (
    consolidation_packet,
    payment_packet,
    tax_packet,
)

KINDS = {"tax", "payment", "consolidation"}
_MAX_NOTE = 120


def _text(value: Any, limit: int = _MAX_NOTE) -> str:
    return str(value or "").strip()[:limit]


def _packet_hash(packet: dict[str, Any]) -> str:
    """对包体做稳定摘要；`generated_at` 每次都会变，不能参与。"""
    if packet.get("source_hash"):
        return str(packet["source_hash"])
    body = {k: v for k, v in packet.items() if k != "generated_at"}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


async def _build(kind: str, tenant_id: int, user_id: int, period: str, group_id: str) -> dict[str, Any]:
    kind = _text(kind, 20).lower()
    if kind not in KINDS:
        raise ValueError("kind 必须是 tax / payment / consolidation")
    if kind == "consolidation":
        if not _text(group_id, 80):
            raise ValueError("合并包需要 group_id")
        return await consolidation_packet(user_id, group_id, period)
    if kind == "tax":
        return await tax_packet(tenant_id, period)
    return await payment_packet(tenant_id, period)


def _parse(row: dict[str, Any], tenant_id: int) -> dict[str, Any] | None:
    try:
        detail = json.loads(str(row.get("detail") or "{}"))
    except Exception:
        return None
    tenant_value = detail.get("tenant_id")
    if tenant_value is None or int(tenant_value) != int(tenant_id):
        return None
    if str(detail.get("kind") or "") not in KINDS:
        return None
    return detail


async def handoff_records(tenant_id: int, limit: int = 20) -> dict[str, Any]:
    """合并留档/确认两类审计事件，按最近活动排序。"""
    archived = await db.list_audit_logs(limit=500, action="HANDOFF")
    acks = await db.list_audit_logs(limit=500, action="HANDOFF_ACK")
    records: dict[str, dict[str, Any]] = {}
    for row in reversed(archived):
        detail = _parse(row, tenant_id)
        if not detail:
            continue
        packet_id = str(detail.get("packet_id") or "")
        if not packet_id:
            continue
        records[packet_id] = {
            "packet_id": packet_id,
            "kind": str(detail.get("kind") or ""),
            "period": str(detail.get("period") or ""),
            "group_id": str(detail.get("group_id") or ""),
            "source_hash": str(detail.get("source_hash") or ""),
            "packet_status": str(detail.get("packet_status") or ""),
            "note": str(detail.get("note") or ""),
            "archived_at": str(row.get("ts") or ""),
            "archived_by": str(row.get("actor") or ""),
            "handed_at": "",
            "handed_note": "",
            "state": "archived",
            "last_activity": str(row.get("ts") or ""),
        }
    for row in acks:
        detail = _parse(row, tenant_id)
        if not detail:
            continue
        packet_id = str(detail.get("packet_id") or "")
        record = records.get(packet_id)
        if not record:
            continue
        record["handed_at"] = str(row.get("ts") or "")
        record["handed_note"] = str(detail.get("note") or "")
        record["state"] = "handed_over"
        if record["handed_at"] > record["last_activity"]:
            record["last_activity"] = record["handed_at"]
    items = sorted(records.values(), key=lambda r: r["last_activity"], reverse=True)
    return {
        "records": items[: max(1, min(int(limit or 20), 100))],
        "total": len(items),
        "archived_count": sum(1 for r in items if r["state"] == "archived"),
        "handed_count": sum(1 for r in items if r["state"] == "handed_over"),
        "boundary": "留档与线下交接确认不是税局申报、付款回单或审计意见；仅证明资料包已生成并交给人工处理。",
    }


async def archive_handoff(
    tenant_id: int,
    user_id: int,
    kind: str,
    period: str,
    group_id: str = "",
    note: str = "",
) -> dict[str, Any]:
    """生成并留档一份交接包；同一 packet_id 幂等。"""
    packet = await _build(kind, tenant_id, user_id, period, group_id)
    packet_id = str(packet["packet_id"])
    detail = {
        "v": 1,
        "tenant_id": int(tenant_id),
        "kind": _text(kind, 20).lower(),
        "period": str(packet["period"]),
        "group_id": _text(group_id, 80),
        "packet_id": packet_id,
        "source_hash": _packet_hash(packet),
        "packet_status": str(packet.get("status") or ""),
        "note": _text(note),
    }
    existing = await handoff_records(tenant_id, limit=100)
    for record in existing["records"]:
        if record["packet_id"] == packet_id:
            return {"record": record, "created": False}
    await db.add_audit_log(
        "HANDOFF",
        "POST",
        "/api/external/handoffs",
        200,
        actor=f"user:{int(user_id)}",
        detail=json.dumps(detail, ensure_ascii=False, sort_keys=True),
    )
    record = {
        "packet_id": packet_id,
        "kind": detail["kind"],
        "period": detail["period"],
        "group_id": detail["group_id"],
        "source_hash": detail["source_hash"],
        "packet_status": detail["packet_status"],
        "note": detail["note"],
        "archived_at": "",
        "archived_by": f"user:{int(user_id)}",
        "handed_at": "",
        "handed_note": "",
        "state": "archived",
    }
    refreshed = await handoff_records(tenant_id, limit=100)
    for row in refreshed["records"]:
        if row["packet_id"] == packet_id:
            record = row
            break
    return {"record": record, "created": True}


async def acknowledge_handoff(
    tenant_id: int,
    user_id: int,
    packet_id: str,
    note: str = "",
) -> dict[str, Any]:
    """把已留档的包标记为“已线下交接”，不改包体、不改账。"""
    packet_id = _text(packet_id, 120)
    ledger = await handoff_records(tenant_id, limit=100)
    found = next((r for r in ledger["records"] if r["packet_id"] == packet_id), None)
    if found is None:
        raise ValueError("交接留档不存在")
    if found["state"] == "handed_over":
        return {"record": found, "updated": False}
    detail = {
        "v": 1,
        "tenant_id": int(tenant_id),
        "kind": found["kind"],
        "period": found["period"],
        "group_id": found["group_id"],
        "packet_id": packet_id,
        "source_hash": found["source_hash"],
        "packet_status": found["packet_status"],
        "note": _text(note),
    }
    await db.add_audit_log(
        "HANDOFF_ACK",
        "POST",
        "/api/external/handoffs/ack",
        200,
        actor=f"user:{int(user_id)}",
        detail=json.dumps(detail, ensure_ascii=False, sort_keys=True),
    )
    refreshed = await handoff_records(tenant_id, limit=100)
    row = next((r for r in refreshed["records"] if r["packet_id"] == packet_id), found)
    return {"record": row, "updated": True}


__all__ = [
    "KINDS",
    "acknowledge_handoff",
    "archive_handoff",
    "handoff_records",
]
