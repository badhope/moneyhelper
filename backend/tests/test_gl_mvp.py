"""复式总账 MVP：借贷平衡、期间锁、过账/反冲、试算表、租户隔离。"""

from __future__ import annotations

import httpx
import pytest
from app import auth, db
from app.calculations.gl import assert_balanced, to_cents
from app.main import app


@pytest.fixture
async def client(temp_db):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787"
    ) as c:
        yield c


async def _user(username: str, role: str = "admin") -> tuple[int, str]:
    uid = await db.user_create(username, "pw-123456", username, role)
    user = await db.user_get(uid)
    assert user is not None
    return uid, auth._make_jwt(user)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _account(client, token: str, code: str, name: str, type_: str) -> int:
    r = await client.post(
        "/api/gl/accounts",
        json={"code": code, "name": name, "type": type_},
        headers=_headers(token),
    )
    assert r.status_code == 200, r.text
    return int(r.json()["account"]["id"])


async def _period(client, token: str, year: int, month: int) -> int:
    r = await client.post(
        "/api/gl/periods",
        json={"year": year, "month": month},
        headers=_headers(token),
    )
    assert r.status_code == 200, r.text
    return int(r.json()["period"]["id"])


def _lines(cash: int, revenue: int, amount: float = 1000.0) -> list[dict]:
    return [
        {"account_id": cash, "debit": amount, "credit": 0, "memo": "收款"},
        {"account_id": revenue, "debit": 0, "credit": amount, "memo": "收入"},
    ]


def test_cents_rounding_and_balance() -> None:
    assert to_cents("1.005") == 101
    assert to_cents(0.005) == 1
    assert to_cents("0") == 0
    for bad in ("", None, "NaN", "Infinity", -1, "-0.01"):
        with pytest.raises(ValueError):
            to_cents(bad)
    with pytest.raises(ValueError, match="只能填写"):
        assert_balanced(
            [
                {"debit": 100, "credit": 100},
                {"account_id": 1, "debit": 0, "credit": 0},
            ]
        )
    with pytest.raises(ValueError, match="不平衡"):
        assert_balanced([{"debit": 100}, {"credit": 90}])


async def test_gl_flow_post_reverse_and_trial_balance(client) -> None:
    _, token = await _user("gl-owner")
    cash = await _account(client, token, "1001", "库存现金", "asset")
    revenue = await _account(client, token, "4001", "营业收入", "income")
    period_id = await _period(client, token, 2026, 11)

    r = await client.post(
        "/api/gl/entries",
        json={
            "entry_date": "2026-11-15",
            "description": "销售收款",
            "lines": _lines(cash, revenue),
        },
        headers=_headers(token),
    )
    assert r.status_code == 200, r.text
    entry = r.json()["entry"]
    assert entry["status"] == "draft"
    assert entry["entry_no"].startswith("GL-202611-")

    r = await client.post(
        f"/api/gl/entries/{entry['id']}/post", headers=_headers(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["status"] == "posted"

    r = await client.get(
        f"/api/gl/trial-balance?period_id={period_id}", headers=_headers(token)
    )
    assert r.status_code == 200, r.text
    tb = r.json()
    assert tb["balanced"] is True
    assert tb["total_debit"] == 1000.0
    assert tb["total_credit"] == 1000.0

    r = await client.post(
        f"/api/gl/entries/{entry['id']}/reverse",
        json={"entry_date": "2026-11-16", "description": "取消销售"},
        headers=_headers(token),
    )
    assert r.status_code == 200, r.text
    reversal = r.json()["entry"]
    assert reversal["source"] == "reversal"
    assert reversal["status"] == "posted"

    # 同一凭证不能重复反冲（数据库唯一索引 + 事务内复查）
    r = await client.post(
        f"/api/gl/entries/{entry['id']}/reverse",
        json={"entry_date": "2026-11-16"},
        headers=_headers(token),
    )
    assert r.status_code == 400
    assert "已经反冲" in r.text

    r = await client.get(
        f"/api/gl/trial-balance?period_id={period_id}", headers=_headers(token)
    )
    tb = r.json()
    assert tb["balanced"] is True
    assert tb["total_debit"] == 2000.0
    assert tb["total_credit"] == 2000.0
    cash_row = next(x for x in tb["items"] if x["code"] == "1001")
    assert cash_row["balance"] == 0.0


async def test_unbalanced_entry_and_cross_account_rejected(client) -> None:
    _, token = await _user("gl-invalid")
    cash = await _account(client, token, "1001", "库存现金", "asset")
    revenue = await _account(client, token, "4001", "营业收入", "income")
    await _period(client, token, 2026, 11)

    r = await client.post(
        "/api/gl/entries",
        json={
            "entry_date": "2026-11-15",
            "lines": [
                {"account_id": cash, "debit": 100, "credit": 0},
                {"account_id": revenue, "debit": 0, "credit": 90},
            ],
        },
        headers=_headers(token),
    )
    assert r.status_code == 400
    assert "不平衡" in r.text


async def test_period_lock_and_draft_close_guard(client) -> None:
    _, token = await _user("gl-period")
    cash = await _account(client, token, "1001", "库存现金", "asset")
    revenue = await _account(client, token, "4001", "营业收入", "income")
    period_id = await _period(client, token, 2026, 12)

    r = await client.post(
        "/api/gl/entries",
        json={"entry_date": "2026-12-01", "lines": _lines(cash, revenue)},
        headers=_headers(token),
    )
    entry_id = r.json()["entry"]["id"]

    r = await client.post(
        f"/api/gl/periods/{period_id}/close", headers=_headers(token)
    )
    assert r.status_code == 400
    assert "草稿" in r.text

    r = await client.post(
        f"/api/gl/entries/{entry_id}/post", headers=_headers(token)
    )
    assert r.status_code == 200
    r = await client.post(
        f"/api/gl/periods/{period_id}/close", headers=_headers(token)
    )
    assert r.status_code == 200
    assert r.json()["period"]["status"] == "closed"

    r = await client.post(
        "/api/gl/entries",
        json={"entry_date": "2026-12-02", "lines": _lines(cash, revenue)},
        headers=_headers(token),
    )
    assert r.status_code == 400
    assert "已关闭" in r.text


async def test_delete_draft_only(client) -> None:
    _, token = await _user("gl-delete")
    cash = await _account(client, token, "1001", "库存现金", "asset")
    revenue = await _account(client, token, "4001", "营业收入", "income")
    await _period(client, token, 2026, 11)

    r = await client.post(
        "/api/gl/entries",
        json={"entry_date": "2026-11-15", "lines": _lines(cash, revenue)},
        headers=_headers(token),
    )
    entry_id = r.json()["entry"]["id"]
    r = await client.delete(f"/api/gl/entries/{entry_id}", headers=_headers(token))
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/gl/entries/{entry_id}", headers=_headers(token))
    assert r.status_code == 404

    r = await client.post(
        "/api/gl/entries",
        json={"entry_date": "2026-11-15", "lines": _lines(cash, revenue)},
        headers=_headers(token),
    )
    posted_id = r.json()["entry"]["id"]
    await client.post(f"/api/gl/entries/{posted_id}/post", headers=_headers(token))
    r = await client.delete(f"/api/gl/entries/{posted_id}", headers=_headers(token))
    assert r.status_code == 400
    assert "草稿" in r.text


async def test_gl_tenant_isolation_and_readonly_role(client) -> None:
    _, token_a = await _user("gl-a")
    uid_b, token_b = await _user("gl-b", role="user")
    cash = await _account(client, token_a, "1001", "库存现金", "asset")
    revenue = await _account(client, token_a, "4001", "营业收入", "income")
    await _period(client, token_a, 2026, 11)
    r = await client.post(
        "/api/gl/entries",
        json={"entry_date": "2026-11-15", "lines": _lines(cash, revenue)},
        headers=_headers(token_a),
    )
    entry_id = r.json()["entry"]["id"]

    # B 看不到 A 的凭证/科目
    r = await client.get(f"/api/gl/entries/{entry_id}", headers=_headers(token_b))
    assert r.status_code == 404
    r = await client.get("/api/gl/accounts", headers=_headers(token_b))
    assert r.status_code == 200
    assert r.json()["accounts"] == []

    # B 是 viewer：可读不可写
    conn = await db._conn()
    await conn.execute(
        "UPDATE org_memberships SET role='viewer' WHERE tenant_id=? AND user_id=?",
        (uid_b, uid_b),
    )
    await conn.commit()
    r = await client.get("/api/gl/accounts", headers=_headers(token_b))
    assert r.status_code == 200
    r = await client.post(
        "/api/gl/accounts",
        json={"code": "1002", "name": "银行存款", "type": "asset"},
        headers=_headers(token_b),
    )
    assert r.status_code == 403

    # 会计角色可写
    conn = await db._conn()
    await conn.execute(
        "UPDATE org_memberships SET role='accountant' WHERE tenant_id=? AND user_id=?",
        (uid_b, uid_b),
    )
    await conn.commit()
    r = await client.post(
        "/api/gl/accounts",
        json={"code": "1002", "name": "银行存款", "type": "asset"},
        headers=_headers(token_b),
    )
    assert r.status_code == 200, r.text


async def test_gl_backup_roundtrip(temp_db) -> None:
    cash = await db.gl_create_account(0, "1001", "库存现金", "asset")
    revenue = await db.gl_create_account(0, "4001", "营业收入", "income")
    await db.gl_create_period(0, 2026, 11)
    entry = await db.gl_create_entry(
        0,
        "2026-11-15",
        "销售收款",
        [
            {"account_id": cash["id"], "debit": 1000, "credit": 0},
            {"account_id": revenue["id"], "debit": 0, "credit": 1000},
        ],
    )
    await db.gl_post_entry(0, entry["id"])

    data = await db.export_data()
    assert len(data["gl_accounts"]) == 2
    assert len(data["gl_entries"]) == 1
    assert len(data["gl_entry_lines"]) == 2

    counts = await db.import_backup(data)
    assert counts["gl_accounts"] == 2
    assert counts["gl_periods"] == 1
    assert counts["gl_entries"] == 1
    assert counts["gl_entry_lines"] == 2

    periods = await db.gl_list_periods(0)
    restored_period = next(p for p in periods if p["year"] == 2026 and p["month"] == 11)
    tb = await db.gl_trial_balance(0, int(restored_period["id"]))
    assert tb["balanced"] is True
    assert tb["total_debit"] == 1000.0
    assert tb["total_credit"] == 1000.0
