"""报销单闭环：草稿→提交→审核→凭证草稿，含自审阻断与跨租户隔离。"""

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


async def _ledger_setup(client, token: str | None) -> tuple[int, int, int]:
    headers = _headers(token) if token else {}
    r = await client.post(
        "/api/gl/accounts",
        json={"code": "6601", "name": "差旅费", "type": "expense"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    expense = r.json()["account"]["id"]
    r = await client.post(
        "/api/gl/accounts",
        json={"code": "1002", "name": "银行存款", "type": "asset"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    cash = r.json()["account"]["id"]
    r = await client.post(
        "/api/gl/periods", json={"year": 2026, "month": 11}, headers=headers
    )
    assert r.status_code == 200, r.text
    return expense, cash, r.json()["period"]["id"]


async def _claim(client, token: str | None, expense: int, cash: int, title: str) -> int:
    r = await client.post(
        "/api/expenses",
        json={
            "title": title,
            "amount": 1000,
            "category": "差旅",
            "expense_account_id": expense,
            "credit_account_id": cash,
            "invoice_ref": "INV-001",
            "attachment_name": "trip.pdf",
        },
        headers=_headers(token) if token else {},
    )
    assert r.status_code == 200, r.text
    return int(r.json()["claim"]["id"])


async def test_local_claim_approve_generates_balanced_voucher(client) -> None:
    expense, cash, period_id = await _ledger_setup(client, None)
    claim_id = await _claim(client, None, expense, cash, "本机差旅报销")

    r = await client.post(f"/api/expenses/{claim_id}/submit")
    assert r.status_code == 200, r.text
    assert r.json()["claim"]["status"] == "submitted"

    r = await client.post(
        f"/api/expenses/{claim_id}/approve",
        json={"entry_date": "2026-11-20"},
    )
    assert r.status_code == 200, r.text
    claim = r.json()["claim"]
    assert claim["status"] == "approved"
    assert claim["gl_entry_id"]
    assert claim["gl_status"] == "draft"

    r = await client.get(f"/api/gl/entries/{claim['gl_entry_id']}")
    assert r.status_code == 200
    entry = r.json()
    assert entry["status"] == "draft"
    assert entry["debit"] == 1000.0 and entry["credit"] == 1000.0
    assert len(entry["lines"]) == 2

    # 会计确认后过账，试算表平衡
    r = await client.post(f"/api/gl/entries/{claim['gl_entry_id']}/post")
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/gl/trial-balance?period_id={period_id}")
    assert r.status_code == 200
    assert r.json()["balanced"] is True


async def test_enterprise_self_approval_blocked_and_cross_tenant_denied(client) -> None:
    uid_a, token_a = await _user("exp-a")
    uid_b, token_b = await _user("exp-b")
    expense, cash, _period = await _ledger_setup(client, token_a)
    claim_id = await _claim(client, token_a, expense, cash, "A 的差旅")
    r = await client.post(
        f"/api/expenses/{claim_id}/submit", headers=_headers(token_a)
    )
    assert r.status_code == 200

    # A 不能审批自己的单
    r = await client.post(
        f"/api/expenses/{claim_id}/approve", headers=_headers(token_a)
    )
    assert r.status_code == 400
    assert "不能审批自己" in r.text

    # B 不是 A 租户成员：显式 tenant_id 也不能越权
    r = await client.post(
        f"/api/expenses/{claim_id}/approve?tenant_id={uid_a}",
        headers=_headers(token_b),
    )
    assert r.status_code == 403

    # 把 B 加入 A 的租户作为审批人
    conn = await db._conn()
    await conn.execute(
        "INSERT INTO org_memberships(tenant_id,user_id,role,status,created_at)"
        " VALUES(?,?,'approver','active','2026-11-01')",
        (uid_a, uid_b),
    )
    await conn.commit()

    r = await client.post(
        f"/api/expenses/{claim_id}/approve?tenant_id={uid_a}",
        json={"entry_date": "2026-11-21"},
        headers=_headers(token_b),
    )
    assert r.status_code == 200, r.text
    claim = r.json()["claim"]
    assert claim["status"] == "approved"
    assert claim["approved_by"] == uid_b
    assert claim["gl_entry_id"]

    # 重复审核被拒
    r = await client.post(
        f"/api/expenses/{claim_id}/approve?tenant_id={uid_a}",
        headers=_headers(token_b),
    )
    assert r.status_code == 400


async def test_reject_claim_and_no_voucher(client) -> None:
    uid_a, token_a = await _user("exp-reject-a")
    uid_b, token_b = await _user("exp-reject-b")
    expense, cash, _period = await _ledger_setup(client, token_a)
    claim_id = await _claim(client, token_a, expense, cash, "待驳回")
    await client.post(f"/api/expenses/{claim_id}/submit", headers=_headers(token_a))

    conn = await db._conn()
    await conn.execute(
        "INSERT INTO org_memberships(tenant_id,user_id,role,status,created_at)"
        " VALUES(?,?,'approver','active','2026-11-01')",
        (uid_a, uid_b),
    )
    await conn.commit()

    r = await client.post(
        f"/api/expenses/{claim_id}/reject?tenant_id={uid_a}",
        json={"reason": "缺少发票"},
        headers=_headers(token_b),
    )
    assert r.status_code == 200, r.text
    claim = r.json()["claim"]
    assert claim["status"] == "rejected"
    assert claim["rejected_reason"] == "缺少发票"
    assert claim["gl_entry_id"] is None


async def test_approval_requires_open_period(client) -> None:
    uid, token = await _user("exp-noperiod")
    uid_b, token_b = await _user("exp-noperiod-b")
    expense = await db.gl_create_account(uid, "6601", "差旅费", "expense")
    cash = await db.gl_create_account(uid, "1002", "银行存款", "asset")
    claim_id = await _claim(client, token, expense["id"], cash["id"], "无期间")
    await client.post(f"/api/expenses/{claim_id}/submit", headers=_headers(token))

    conn = await db._conn()
    await conn.execute(
        "INSERT INTO org_memberships(tenant_id,user_id,role,status,created_at)"
        " VALUES(?,?,'approver','active','2026-11-01')",
        (uid, uid_b),
    )
    await conn.commit()

    r = await client.post(
        f"/api/expenses/{claim_id}/approve?tenant_id={uid}",
        headers=_headers(token_b),
    )
    assert r.status_code == 400
    assert "期间" in r.text


async def test_expense_backup_roundtrip(client) -> None:
    expense, cash, _period = await _ledger_setup(client, None)
    claim_id = await _claim(client, None, expense, cash, "备份报销")
    await client.post(f"/api/expenses/{claim_id}/submit")
    r = await client.post(
        f"/api/expenses/{claim_id}/approve", json={"entry_date": "2026-11-20"}
    )
    assert r.status_code == 200
    old_entry_id = r.json()["claim"]["gl_entry_id"]

    data = await db.export_data()
    assert len(data["expense_claims"]) == 1
    counts = await db.import_backup(data)
    assert counts["expense_claims"] == 1
    assert counts["gl_entries"] == 1

    claims = await db.expense_list_claims(0)
    assert len(claims) == 1
    restored = claims[0]
    assert restored["status"] == "approved"
    assert restored["gl_entry_id"] != old_entry_id
    entry = await db.gl_get_entry(0, int(restored["gl_entry_id"]))
    assert entry is not None
    assert entry["status"] == "draft"
