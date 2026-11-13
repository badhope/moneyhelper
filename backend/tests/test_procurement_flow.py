"""采购/应付最小闭环（切片 8）：供应商 → 采购单 → 应付 → 付款 → 银行匹配。

同时覆盖：状态机门禁、角色权限、跨租户隔离、备份恢复 ID 重映射。
"""

from __future__ import annotations

import sqlite3

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


async def _accounts(
    client, headers: dict[str, str] | None = None
) -> tuple[int, int, int]:
    """返回 (expense, payable, bank)，并开 2026-11 期间。"""
    h = headers or {}
    r = await client.post(
        "/api/gl/accounts",
        json={"code": "6601", "name": "采购费用", "type": "expense"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    expense = int(r.json()["account"]["id"])
    r = await client.post(
        "/api/gl/accounts",
        json={"code": "2202", "name": "应付账款", "type": "liability"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    payable = int(r.json()["account"]["id"])
    r = await client.post(
        "/api/gl/accounts",
        json={"code": "1002", "name": "银行存款", "type": "asset"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    bank = int(r.json()["account"]["id"])
    r = await client.post("/api/gl/periods", json={"year": 2026, "month": 11}, headers=h)
    assert r.status_code == 200, r.text
    return expense, payable, bank


async def _vendor(client, headers: dict[str, str] | None = None) -> int:
    r = await client.post(
        "/api/procurement/vendors",
        json={"code": "V001", "name": "测试供应商", "tax_no": "91310000X"},
        headers=headers or {},
    )
    assert r.status_code == 200, r.text
    return int(r.json()["vendor"]["id"])


async def _approved_po(client, vendor_id: int, headers: dict[str, str] | None = None) -> int:
    h = headers or {}
    r = await client.post(
        "/api/procurement/orders",
        json={
            "vendor_id": vendor_id,
            "order_date": "2026-11-05",
            "expected_date": "2026-11-15",
            "amount": 5000,
            "description": "办公用品",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    po_id = int(r.json()["order"]["id"])
    r = await client.post(f"/api/procurement/orders/{po_id}/submit", headers=h)
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/procurement/orders/{po_id}/approve", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["order"]["status"] == "approved"
    return po_id


async def _approved_payable(
    client,
    vendor_id: int,
    po_id: int,
    expense: int,
    payable: int,
    headers: dict[str, str] | None = None,
) -> int:
    h = headers or {}
    r = await client.post(
        "/api/procurement/payables",
        json={
            "vendor_id": vendor_id,
            "po_id": po_id,
            "invoice_no": "INV-2026-001",
            "invoice_date": "2026-11-10",
            "due_date": "2026-12-10",
            "amount": 5000,
            "tax": 300,
            "expense_account_id": expense,
            "payable_account_id": payable,
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    payable_id = int(r.json()["payable"]["id"])
    r = await client.post(
        f"/api/procurement/payables/{payable_id}/submit", headers=h
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/procurement/payables/{payable_id}/approve", headers=h
    )
    assert r.status_code == 200, r.text
    return payable_id


async def test_local_procurement_to_payment_and_bank_match(client) -> None:
    expense, payable_account, bank = await _accounts(client)
    vendor = await _vendor(client)
    po = await _approved_po(client, vendor)
    payable_id = await _approved_payable(
        client, vendor, po, expense, payable_account
    )

    r = await client.get("/api/procurement/payables")
    assert r.status_code == 200
    row = r.json()["payables"][0]
    assert row["id"] == payable_id
    assert row["status"] == "approved"
    assert row["po_no"].startswith("PO-202611-")
    assert row["vendor_name"] == "测试供应商"
    assert row["gl_status"] == "draft"

    r = await client.get(f"/api/gl/entries/{row['gl_entry_id']}")
    assert r.status_code == 200
    entry = r.json()
    assert entry["status"] == "draft"
    assert entry["debit"] == 5000.0 and entry["credit"] == 5000.0
    debit_line = next(x for x in entry["lines"] if x["debit"] > 0)
    credit_line = next(x for x in entry["lines"] if x["credit"] > 0)
    assert debit_line["account_id"] == expense
    assert credit_line["account_id"] == payable_account

    r = await client.post(
        f"/api/procurement/payables/{payable_id}/pay",
        json={"bank_account_id": bank, "note": "首款"},
    )
    assert r.status_code == 200, r.text
    paid = r.json()["payable"]
    assert paid["status"] == "paid"
    assert paid["payment_no"].startswith("PAY-202611-")

    # 付款列表能认出这是应付付款，而不是报销付款
    payments = (await client.get("/api/payments")).json()["payments"]
    assert len(payments) == 1
    payment = payments[0]
    assert payment["claim_id"] == 0
    assert payment["payable_id"] == payable_id
    assert payment["payable_no"] == paid["payable_no"]
    assert payment["gl_status"] == "draft"

    # 付款凭证：借应付、贷银行
    r = await client.get(f"/api/gl/entries/{payment['gl_entry_id']}")
    assert r.status_code == 200
    pay_entry = r.json()
    assert pay_entry["debit"] == 5000.0 and pay_entry["credit"] == 5000.0
    assert next(x for x in pay_entry["lines"] if x["debit"] > 0)["account_id"] == payable_account
    assert next(x for x in pay_entry["lines"] if x["credit"] > 0)["account_id"] == bank

    # 银行流水按同账户/金额/方向匹配供应商付款
    r = await client.post(
        "/api/bank/transactions",
        json={
            "bank_account_id": bank,
            "txn_date": "2026-11-12",
            "direction": "out",
            "amount": 5000,
            "counterparty": "测试供应商",
        },
    )
    txn_id = int(r.json()["transaction"]["id"])
    r = await client.post(
        f"/api/bank/transactions/{txn_id}/match",
        json={"payment_id": payment["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["transaction"]["status"] == "matched"
    summary = (await client.get("/api/bank/summary")).json()
    assert summary["matched_count"] == 1
    assert summary["unmatched_count"] == 0

    # 已付款的应付不能再付一次
    r = await client.post(
        f"/api/procurement/payables/{payable_id}/pay",
        json={"bank_account_id": bank},
    )
    assert r.status_code == 400


async def test_procurement_status_gates(client) -> None:
    expense, payable_account, bank = await _accounts(client)
    vendor = await _vendor(client)

    # 未审核采购单不能生成应付
    r = await client.post(
        "/api/procurement/orders",
        json={
            "vendor_id": vendor,
            "order_date": "2026-11-06",
            "amount": 800,
        },
    )
    draft_po = int(r.json()["order"]["id"])
    r = await client.post(
        "/api/procurement/payables",
        json={
            "vendor_id": vendor,
            "po_id": draft_po,
            "invoice_date": "2026-11-10",
            "amount": 800,
            "expense_account_id": expense,
            "payable_account_id": payable_account,
        },
    )
    assert r.status_code == 400
    assert "已审核" in r.text

    # 草稿应付不能付款
    r = await client.post(
        "/api/procurement/payables",
        json={
            "vendor_id": vendor,
            "invoice_date": "2026-11-10",
            "amount": 800,
            "expense_account_id": expense,
            "payable_account_id": payable_account,
        },
    )
    assert r.status_code == 200, r.text
    payable_id = int(r.json()["payable"]["id"])
    r = await client.post(
        f"/api/procurement/payables/{payable_id}/pay",
        json={"bank_account_id": bank},
    )
    assert r.status_code == 400
    assert "已审核" in r.text

    # 科目类型不对：应付贷方不能选资产
    r = await client.post(
        "/api/procurement/payables",
        json={
            "vendor_id": vendor,
            "invoice_date": "2026-11-10",
            "amount": 100,
            "expense_account_id": expense,
            "payable_account_id": bank,
        },
    )
    assert r.status_code == 400
    assert "负债" in r.text


async def test_procurement_roles_and_cross_tenant(client) -> None:
    uid_a, token_a = await _user("proc-a")
    uid_b, token_b = await _user("proc-b")
    uid_c, token_c = await _user("proc-c")
    vendor = await _vendor(client, _headers(token_a))
    po = await _approved_po(client, vendor, _headers(token_a))
    expense, payable_account, _bank = await _accounts(client, _headers(token_a))

    # B 不是 A 租户成员，显式 tenant_id 也不能写
    r = await client.post(
        f"/api/procurement/vendors?tenant_id={uid_a}",
        json={"code": "X1", "name": "越权供应商"},
        headers=_headers(token_b),
    )
    assert r.status_code == 403

    # 把 B 设为会计：能建应付/付款，不能审核
    conn = await db._conn()
    await conn.execute(
        "INSERT INTO org_memberships(tenant_id,user_id,role,status,created_at)"
        " VALUES(?,?,'accountant','active','2026-11-01')",
        (uid_a, uid_b),
    )
    # 把 C 设为审批人：能审核，不能建单
    await conn.execute(
        "INSERT INTO org_memberships(tenant_id,user_id,role,status,created_at)"
        " VALUES(?,?,'approver','active','2026-11-01')",
        (uid_a, uid_c),
    )
    await conn.commit()

    r = await client.post(
        f"/api/procurement/payables?tenant_id={uid_a}",
        json={
            "vendor_id": vendor,
            "po_id": po,
            "invoice_date": "2026-11-10",
            "amount": 1200,
            "expense_account_id": expense,
            "payable_account_id": payable_account,
        },
        headers=_headers(token_b),
    )
    assert r.status_code == 200, r.text
    payable_id = int(r.json()["payable"]["id"])
    await client.post(
        f"/api/procurement/payables/{payable_id}/submit?tenant_id={uid_a}",
        headers=_headers(token_b),
    )

    # 会计不能审核
    r = await client.post(
        f"/api/procurement/payables/{payable_id}/approve?tenant_id={uid_a}",
        headers=_headers(token_b),
    )
    assert r.status_code == 403

    # 审批人不能建供应商
    r = await client.post(
        f"/api/procurement/vendors?tenant_id={uid_a}",
        json={"code": "X2", "name": "审批人建的供应商"},
        headers=_headers(token_c),
    )
    assert r.status_code == 403

    # 审批人可以审核
    r = await client.post(
        f"/api/procurement/payables/{payable_id}/approve?tenant_id={uid_a}",
        headers=_headers(token_c),
    )
    assert r.status_code == 200, r.text
    assert r.json()["payable"]["approved_by"] == uid_c

    # B 仍可付款
    r = await client.post(
        f"/api/procurement/payables/{payable_id}/pay?tenant_id={uid_a}",
        json={"bank_account_id": _bank},
        headers=_headers(token_b),
    )
    assert r.status_code == 200, r.text

    # 非成员读也被拒（B 已是 A 的会计，能读是正常的；用 D 验证隔离）
    _uid_d, token_d = await _user("proc-d")
    r = await client.get(
        f"/api/procurement/orders?tenant_id={uid_a}", headers=_headers(token_d)
    )
    assert r.status_code == 403
    r = await client.get(
        f"/api/procurement/payables?tenant_id={uid_a}", headers=_headers(token_d)
    )
    assert r.status_code == 403


async def test_procurement_backup_roundtrip(client) -> None:
    expense, payable_account, bank = await _accounts(client)
    vendor = await _vendor(client)
    po = await _approved_po(client, vendor)
    payable_id = await _approved_payable(
        client, vendor, po, expense, payable_account
    )
    r = await client.post(
        f"/api/procurement/payables/{payable_id}/pay",
        json={"bank_account_id": bank},
    )
    assert r.status_code == 200, r.text
    old_payment_id = int(
        (await client.get("/api/payments")).json()["payments"][0]["id"]
    )
    old_payable_entry = (await db.payable_get(0, payable_id))["gl_entry_id"]
    old_payment_entry = (await db.payment_get(0, old_payment_id))["gl_entry_id"]

    data = await db.export_data()
    assert len(data["vendors"]) == 1
    assert len(data["purchase_orders"]) == 1
    assert len(data["payables"]) == 1
    assert len(data["payments"]) == 1
    counts = await db.import_backup(data)
    assert counts["vendors"] == 1
    assert counts["purchase_orders"] == 1
    assert counts["payables"] == 1
    assert counts["payments"] == 1

    payable = (await db.payable_list(0))[0]
    assert payable["status"] == "paid"
    assert payable["gl_entry_id"] != old_payable_entry
    assert payable["payment_id"] is not None

    payment = (await db.payment_list(0))[0]
    assert payment["payable_id"] == payable["id"]
    assert payment["gl_entry_id"] != old_payment_entry
    assert payable["payment_id"] == payment["id"]

    # 付款/应付指向的凭证都还在
    assert await db.gl_get_entry(0, int(payment["gl_entry_id"])) is not None
    assert await db.gl_get_entry(0, int(payable["gl_entry_id"])) is not None


async def test_legacy_payment_index_migrates_to_partial(
    tmp_path, monkeypatch
) -> None:
    """旧库的 UNIQUE(tenant_id,claim_id) 必须换成部分索引。

    否则所有应付付款都以 claim_id=0 落库，第二条就撞唯一索引；
    这里直接构造带旧索引的库，跑 init_db 后验证索引形态。
    """
    db_file = tmp_path / "legacy-payments.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(
        """
        CREATE TABLE payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            payment_no TEXT NOT NULL,
            claim_id INTEGER NOT NULL,
            amount_cents INTEGER NOT NULL,
            payee TEXT NOT NULL DEFAULT '',
            bank_account_id INTEGER NOT NULL,
            method TEXT NOT NULL DEFAULT 'bank',
            status TEXT NOT NULL DEFAULT 'paid',
            paid_at TEXT NOT NULL DEFAULT '',
            created_by INTEGER,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE UNIQUE INDEX idx_payment_tenant_claim
            ON payments(tenant_id, claim_id);
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(db._core, "DB_PATH", db_file)
    await db.close_db()
    await db.init_db()
    try:
        rows = await db.fetch_all("PRAGMA index_list(payments)")
        partial = {r["name"]: int(r["partial"]) for r in rows}
        assert partial.get("idx_payment_tenant_claim") == 1
        assert "idx_payment_tenant_payable" in partial

        cols = {r["name"] for r in await db.fetch_all("PRAGMA table_info(payments)")}
        assert {"payable_id", "gl_entry_id"} <= cols

        # 两条 claim_id=0 的应付付款不应再互相冲突
        await db.fetch_all("SELECT 1")
        conn2 = await db._conn()
        await conn2.execute(
            "INSERT INTO payments(tenant_id,payment_no,claim_id,amount_cents,"
            "payee,bank_account_id) VALUES(0,'P1',0,100,'a',1)"
        )
        await conn2.execute(
            "INSERT INTO payments(tenant_id,payment_no,claim_id,amount_cents,"
            "payee,bank_account_id) VALUES(0,'P2',0,100,'b',1)"
        )
        await conn2.commit()
        n = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM payments WHERE tenant_id=0 AND claim_id=0"
        )
        assert n is not None and int(n["n"]) == 2
    finally:
        await db.close_db()
