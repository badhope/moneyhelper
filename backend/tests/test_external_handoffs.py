"""4.21.0 交接留档：复用审计哈希链，不新增表、不伪装已提交。"""

from __future__ import annotations

from datetime import date

import pytest
from app import db
from app.external_handoffs import (
    acknowledge_handoff,
    archive_handoff,
    handoff_records,
)


async def _post(tenant_id: int, day: str, desc: str, lines: list[tuple[str, float, float]]) -> None:
    await db.gl_bootstrap(tenant_id, ref_date=day)
    accounts = {a["code"]: a for a in await db.gl_list_accounts(tenant_id)}
    entry = await db.gl_create_entry(
        tenant_id, day, desc,
        [
            {"account_id": accounts[code]["id"], "debit": debit, "credit": credit}
            for code, debit, credit in lines
        ],
    )
    await db.gl_post_entry(tenant_id, entry["id"])


@pytest.mark.asyncio
async def test_tax_handoff_archive_is_idempotent_audit_record(client) -> None:
    period = date.today().strftime("%Y-%m")
    day = date.today().isoformat()
    await _post(0, day, "留档销售", [("1001", 800, 0), ("6001", 0, 800)])

    first = await archive_handoff(0, 0, "tax", period, note="交给代账")
    assert first["created"] is True
    assert first["record"]["state"] == "archived"
    assert first["record"]["packet_id"].startswith("TAX-")
    assert len(first["record"]["source_hash"]) == 32
    assert first["record"]["note"] == "交给代账"

    again = await archive_handoff(0, 0, "tax", period)
    assert again["created"] is False
    assert again["record"]["packet_id"] == first["record"]["packet_id"]

    handoff_rows = await db.list_audit_logs(limit=50, action="HANDOFF")
    assert len(handoff_rows) == 1
    ledger = await handoff_records(0)
    assert ledger["total"] == 1
    assert ledger["archived_count"] == 1
    assert ledger["handed_count"] == 0
    assert "不是税局申报" in ledger["boundary"]
    verified = await db.verify_audit_chain()
    assert verified["ok"] is True

    resp = await client.post(
        "/api/external/handoffs",
        json={"kind": "tax", "period": period, "note": "接口留档"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] is False


@pytest.mark.asyncio
async def test_ack_marks_handed_over_but_never_submitted(client) -> None:
    period = date.today().strftime("%Y-%m")
    day = date.today().isoformat()
    await db.cash_plan_save(
        0, period,
        [{"expected_date": day, "direction": "out", "account_code": "1001", "amount": 120,
          "counterparty": "供应商", "certainty": "high"}],
        opening=500, target_min=100, note="留档付款",
    )
    archived = await archive_handoff(0, 0, "payment", period)
    packet_id = archived["record"]["packet_id"]

    acked = await acknowledge_handoff(0, 0, packet_id, "已由出纳线下处理")
    assert acked["updated"] is True
    assert acked["record"]["state"] == "handed_over"
    assert acked["record"]["handed_note"] == "已由出纳线下处理"
    assert acked["record"]["handed_at"]

    again = await acknowledge_handoff(0, 0, packet_id, "重复确认")
    assert again["updated"] is False
    ack_rows = await db.list_audit_logs(limit=50, action="HANDOFF_ACK")
    assert len(ack_rows) == 1

    ledger = await handoff_records(0)
    assert ledger["handed_count"] == 1
    assert ledger["records"][0]["state"] == "handed_over"
    assert not any(
        word in str(ledger["records"][0]).lower()
        for word in ("submitted", "paid", "audited")
    )

    resp = await client.post(
        "/api/external/handoffs/ack",
        json={"packet_id": packet_id, "note": "接口确认"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] is False

    resp = await client.get("/api/external/handoffs")
    assert resp.status_code == 200, resp.text
    assert resp.json()["handed_count"] == 1


@pytest.mark.asyncio
async def test_consolidation_handoff_requires_group_and_keeps_hash(client) -> None:
    period = date.today().strftime("%Y-%m")
    day = date.today().isoformat()
    group = await db.consolidation_create_group(0, "交接测试集团")
    await db.consolidation_add_entity(0, group["id"], tenant_id=0, ownership_pct=100, method="full")
    await _post(0, day, "合并留档销售", [("1001", 300, 0), ("6001", 0, 300)])

    archived = await archive_handoff(0, 0, "consolidation", period, group_id=group["id"])
    assert archived["created"] is True
    assert archived["record"]["kind"] == "consolidation"
    assert len(archived["record"]["source_hash"]) == 32
    assert archived["record"]["packet_status"] == "blocked"

    with pytest.raises(ValueError, match="group_id"):
        await archive_handoff(0, 0, "consolidation", period)
    with pytest.raises(ValueError, match="kind"):
        await archive_handoff(0, 0, "unknown", period)

    resp = await client.post(
        "/api/external/handoffs",
        json={"kind": "consolidation", "period": period, "group_id": group["id"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["record"]["source_hash"] == archived["record"]["source_hash"]
