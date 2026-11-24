"""4.20.0 外部协同前置包：只读、可核对、不代提交/付款/审计。"""

from __future__ import annotations

from datetime import date

import pytest
from app import db
from app.external_packets import (
    consolidation_packet,
    payment_packet,
    tax_packet,
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
async def test_tax_packet_uses_posted_and_stays_unsubmitted(client) -> None:
    period = date.today().strftime("%Y-%m")
    day = date.today().isoformat()
    await _post(0, day, "销售收入", [("1001", 1000, 0), ("6001", 0, 1000)])
    await _post(0, day, "计提税费", [("6603", 30, 0), ("2203", 0, 30)])

    out = await tax_packet(0, period)
    assert out["period"] == period
    assert out["submission_status"] == "not_submitted"
    assert out["status"] == "blocked"
    assert out["posted_entries"] >= 2
    assert out["summary"]["income"] == 1000
    assert out["summary"]["expense"] == 30
    assert out["summary"]["profit"] == 970
    assert out["summary"]["tax_accrued"] == 30
    assert out["summary"]["debit"] == out["summary"]["credit"] == 1030
    assert out["packet_id"].startswith(f"TAX-{period.replace('-', '')}-")
    assert any(c["id"] == "filing_channel" and c["status"] == "blocked" for c in out["checks"])
    assert "不提交税局" in out["boundary"]

    resp = await client.get(f"/api/external/tax-packet?period={period}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["submission_status"] == "not_submitted"

    with pytest.raises(ValueError, match="YYYY-MM"):
        await tax_packet(0, "2026-13")


@pytest.mark.asyncio
async def test_payment_packet_is_draft_only(client) -> None:
    period = date.today().strftime("%Y-%m")
    day = date.today().isoformat()
    await db.cash_plan_save(
        0, period,
        [
            {"expected_date": day, "direction": "in", "account_code": "1001", "amount": 500, "certainty": "high"},
            {"expected_date": day, "direction": "out", "account_code": "1001", "amount": 200,
             "counterparty": "供应商", "certainty": "high"},
        ],
        opening=300, target_min=50, note="外部协同测试",
    )
    out = await payment_packet(0, period)
    assert out["status"] == "blocked"
    assert out["execution_status"] == "draft_only"
    assert out["can_execute"] is False
    assert out["count"] == 1
    assert out["total"] == 200
    assert out["total_cents"] == 20000
    assert out["instructions"][0]["counterparty"] == "供应商"
    assert any(c["id"] == "execution_channel" and c["status"] == "blocked" for c in out["checks"])
    assert "不发起支付" in out["boundary"]

    missing = await db.cash_plan_get(0, "2025-01")
    assert missing["exists"] is False
    missing_packet = await payment_packet(0, "2025-01")
    assert missing_packet["status"] == "missing"
    assert missing_packet["instructions"] == []

    resp = await client.get(f"/api/external/payment-packet?period={period}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["execution_status"] == "draft_only"


@pytest.mark.asyncio
async def test_consolidation_packet_carries_basis_and_hash(client) -> None:
    period = date.today().strftime("%Y-%m")
    day = date.today().isoformat()
    group = await db.consolidation_create_group(0, "审计包测试集团")
    await db.consolidation_add_entity(0, group["id"], tenant_id=0, ownership_pct=100, method="full")
    await _post(0, day, "合并测试销售", [("1001", 600, 0), ("6001", 0, 600)])

    out = await consolidation_packet(0, group["id"], period)
    assert out["basis"] == "management"
    assert out["audit_status"] == "not_audited"
    assert out["status"] == "blocked"
    assert out["balanced"] is True
    assert out["entities"][0]["status"] == "ok"
    assert len(out["source_hash"]) == 32
    assert any(c["id"] == "audit_basis" and c["status"] == "blocked" for c in out["checks"])
    assert "不做法定合并" in out["boundary"]

    resp = await client.get(f"/api/external/consolidation-packet?group_id={group['id']}&period={period}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["audit_status"] == "not_audited"

    with pytest.raises(ValueError):
        await consolidation_packet(0, group["id"], "2026-13")
