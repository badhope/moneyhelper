"""付款与银行流水：付款登记、匹配/取消、CSV 导入、租户隔离。"""

from __future__ import annotations

import httpx
import pytest
from app import auth, db
from app.main import app


@pytest.fixture
async def client(temp_db):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787"
    ) as c:
        yield c


async def _user(username: str, role: str = "user") -> tuple[int, str]:
    uid = await db.user_create(username, "pw-123456", username, role)
    user = await db.user_get(uid)
    assert user is not None
    return uid, auth._make_jwt(user)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _setup_local(client) -> tuple[int, int, int]:
    """返回 (claim_id, expense_account_id, bank_account_id)，报销单已审核通过。"""
    headers: dict[str, str] = {}
    r = await client.post(
        "/api/gl/accounts",
        json={"code": "6601", "name": "差旅费", "type": "expense"},
        headers=headers,
    )
    expense = int(r.json()["account"]["id"])
    r = await client.post(
        "/api/gl/accounts",
        json={"code": "1002", "name": "银行存款", "type": "asset"},
        headers=headers,
    )
    cash = int(r.json()["account"]["id"])
    r = await client.post("/api/gl/periods", json={"year": 2026, "month": 11})
    assert r.status_code == 200, r.text
    r = await client.post(
        "/api/expenses",
        json={
            "title": "付款测试",
            "amount": 1000,
            "category": "差旅",
            "expense_account_id": expense,
            "credit_account_id": cash,
        },
    )
    claim_id = int(r.json()["claim"]["id"])
    await client.post(f"/api/expenses/{claim_id}/submit")
    r = await client.post(
        f"/api/expenses/{claim_id}/approve", json={"entry_date": "2026-11-20"}
    )
    assert r.status_code == 200, r.text
    return claim_id, expense, cash


async def test_local_payment_bank_match_and_summary(client) -> None:
    claim_id, _expense, cash = await _setup_local(client)
    r = await client.post(
        "/api/payments",
        json={"claim_id": claim_id, "bank_account_id": cash},
    )
    assert r.status_code == 200, r.text
    payment = r.json()["payment"]
    assert payment["payment_no"].startswith("PAY-202611-")
    assert payment["amount"] == 1000.0

    r = await client.post(
        "/api/bank/transactions",
        json={
            "bank_account_id": cash,
            "txn_date": "2026-11-21",
            "direction": "out",
            "amount": 1000,
            "counterparty": "员工",
            "memo": "差旅报销",
        },
    )
    assert r.status_code == 200, r.text
    txn_id = int(r.json()["transaction"]["id"])

    r = await client.post(
        f"/api/bank/transactions/{txn_id}/match",
        json={"payment_id": payment["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["transaction"]["status"] == "matched"

    summary = (await client.get("/api/bank/summary")).json()
    assert summary["payments_count"] == 1
    assert summary["matched_count"] == 1
    assert summary["unmatched_count"] == 0
    assert summary["balanced"] is True

    r = await client.post(f"/api/bank/transactions/{txn_id}/unmatch")
    assert r.status_code == 200, r.text
    assert r.json()["transaction"]["status"] == "unmatched"
    assert (await client.get("/api/bank/summary")).json()["unmatched_count"] == 1


async def test_payment_duplicate_and_match_mismatch(client) -> None:
    claim_id, _expense, cash = await _setup_local(client)
    r = await client.post(
        "/api/payments", json={"claim_id": claim_id, "bank_account_id": cash}
    )
    assert r.status_code == 200
    r = await client.post(
        "/api/payments", json={"claim_id": claim_id, "bank_account_id": cash}
    )
    assert r.status_code == 400
    assert "已经登记" in r.text

    r = await client.post(
        "/api/bank/transactions",
        json={
            "bank_account_id": cash,
            "txn_date": "2026-11-21",
            "direction": "out",
            "amount": 999,
        },
    )
    txn_id = int(r.json()["transaction"]["id"])
    payment_id = (await client.get("/api/payments")).json()["payments"][0]["id"]
    r = await client.post(
        f"/api/bank/transactions/{txn_id}/match",
        json={"payment_id": payment_id},
    )
    assert r.status_code == 400
    assert "金额" in r.text


async def test_bank_csv_import(client) -> None:
    _claim, _expense, cash = await _setup_local(client)
    csv_text = (
        "date,amount,direction,counterparty,memo,ref\n"
        "2026-11-20,-1000,out,供应商,付款,P001\n"
        "2026-11-21,500,in,客户,收款,R001\n"
    )
    r = await client.post(
        "/api/bank/import",
        json={"bank_account_id": cash, "csv": csv_text},
    )
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 2
    rows = (await client.get("/api/bank/transactions")).json()["transactions"]
    assert len(rows) == 2
    assert {x["direction"] for x in rows} == {"in", "out"}
    summary = (await client.get("/api/bank/summary")).json()
    assert summary["bank_out_total"] == 1000.0
    assert summary["bank_in_total"] == 500.0
    assert summary["unmatched_count"] == 2


async def test_cross_tenant_payment_access_denied(client) -> None:
    uid_a, token_a = await _user("bank-a")
    _, token_b = await _user("bank-b")
    r = await client.post(
        "/api/gl/accounts",
        json={"code": "1002", "name": "银行存款", "type": "asset"},
        headers=_headers(token_a),
    )
    cash = int(r.json()["account"]["id"])
    r = await client.get(
        f"/api/payments?tenant_id={uid_a}", headers=_headers(token_b)
    )
    assert r.status_code == 403
    r = await client.get(
        f"/api/bank/summary?tenant_id={uid_a}", headers=_headers(token_b)
    )
    assert r.status_code == 403

    # A 自己能访问（空列表）
    r = await client.get(f"/api/payments?tenant_id={uid_a}", headers=_headers(token_a))
    assert r.status_code == 200
    assert r.json()["payments"] == []
    assert cash > 0


async def test_reconciliation_close_success_and_repeat_blocked(client) -> None:
    _claim, _expense, cash = await _setup_local(client)
    period_id = (await client.get("/api/gl/periods")).json()["periods"][0]["id"]
    r = await client.post(
        "/api/bank/reconciliations",
        json={
            "bank_account_id": cash,
            "period_id": period_id,
            "statement_balance": 0,
        },
    )
    assert r.status_code == 200, r.text
    recon = r.json()["reconciliation"]
    assert recon["difference"] == 0
    r = await client.post(f"/api/bank/reconciliations/{recon['id']}/close")
    assert r.status_code == 200, r.text
    assert r.json()["reconciliation"]["status"] == "closed"

    r = await client.post(
        "/api/bank/reconciliations",
        json={
            "bank_account_id": cash,
            "period_id": period_id,
            "statement_balance": 0,
        },
    )
    assert r.status_code == 400
    assert "已签核" in r.text


async def test_reconciliation_blocks_difference_and_unmatched(client) -> None:
    r = await client.post(
        "/api/gl/accounts",
        json={"code": "1003", "name": "对账账户", "type": "asset"},
    )
    account = int(r.json()["account"]["id"])
    r = await client.post("/api/gl/periods", json={"year": 2026, "month": 12})
    period_id = int(r.json()["period"]["id"])

    r = await client.post(
        "/api/bank/reconciliations",
        json={
            "bank_account_id": account,
            "period_id": period_id,
            "statement_balance": 100,
        },
    )
    recon = r.json()["reconciliation"]
    assert recon["difference"] == 100.0
    r = await client.post(f"/api/bank/reconciliations/{recon['id']}/close")
    assert r.status_code == 400
    assert "差额" in r.text

    r = await client.post(
        "/api/bank/transactions",
        json={
            "bank_account_id": account,
            "txn_date": "2026-12-05",
            "direction": "out",
            "amount": 50,
        },
    )
    assert r.status_code == 200
    r = await client.post(
        "/api/bank/reconciliations",
        json={
            "bank_account_id": account,
            "period_id": period_id,
            "statement_balance": 0,
        },
    )
    recon = r.json()["reconciliation"]
    assert recon["difference"] == 0
    r = await client.post(f"/api/bank/reconciliations/{recon['id']}/close")
    assert r.status_code == 400
    assert "未匹配" in r.text


async def test_payment_bank_reconciliation_backup_roundtrip(client) -> None:
    claim_id, _expense, cash = await _setup_local(client)
    r = await client.post(
        "/api/payments", json={"claim_id": claim_id, "bank_account_id": cash}
    )
    payment = r.json()["payment"]
    r = await client.post(
        "/api/bank/transactions",
        json={
            "bank_account_id": cash,
            "txn_date": "2026-11-21",
            "direction": "out",
            "amount": 1000,
        },
    )
    txn_id = int(r.json()["transaction"]["id"])
    await client.post(
        f"/api/bank/transactions/{txn_id}/match",
        json={"payment_id": payment["id"]},
    )
    period_id = (await client.get("/api/gl/periods")).json()["periods"][0]["id"]
    await client.post(
        "/api/bank/reconciliations",
        json={
            "bank_account_id": cash,
            "period_id": period_id,
            "statement_balance": 0,
        },
    )

    data = await db.export_data()
    assert len(data["payments"]) == 1
    assert len(data["bank_transactions"]) == 1
    assert len(data["bank_reconciliations"]) == 1
    counts = await db.import_backup(data)
    assert counts["payments"] == 1
    assert counts["bank_transactions"] == 1
    assert counts["bank_reconciliations"] == 1

    pay = (await db.payment_list(0))[0]
    restored_claim = await db.expense_get_claim(0, int(pay["claim_id"]))
    assert restored_claim is not None
    assert restored_claim["status"] == "approved"
    rows = await db.bank_list(0)
    assert len(rows) == 1
    assert rows[0]["status"] == "matched"
    assert rows[0]["payment_id"] == pay["id"]
    recons = await db.reconciliation_list(0)
    assert len(recons) == 1
    assert recons[0]["bank_account_id"] == pay["bank_account_id"]
