"""一键建账与流水自动转凭证：让"导入流水 → 出报表"不需要任何会计知识。"""

from __future__ import annotations

import pytest
from app import auth, db
from app.calculations.chart import DEFAULT_CHART, pick_account_code


def test_chart_is_minimal_and_typed() -> None:
    codes = [c for c, _, _ in DEFAULT_CHART]
    assert len(codes) == len(set(codes)), "科目编码不能重复"
    types = {t for _, _, t in DEFAULT_CHART}
    assert types == {"asset", "liability", "equity", "income", "expense"}
    for code in codes:
        assert len(code) == 4 and code.isdigit()


def test_pick_account_code_by_keyword() -> None:
    assert pick_account_code("out", "11月房租") == "6602"
    assert pick_account_code("out", "", "供电局") == "6602"
    assert pick_account_code("out", "银行手续费") == "6603"
    assert pick_account_code("out", "采购原材料") == "6401"
    assert pick_account_code("in", "工资") == "6001"
    assert pick_account_code("in", "") == "6051"
    # 未知摘要必须落到默认科目，不能返回空
    assert pick_account_code("out", "乱七八糟") == "6602"


async def _user() -> tuple[int, str]:
    uid = await db.user_create("gl-auto", "pw-123456", "gl-auto", "admin")
    user = await db.user_get(uid)
    assert user is not None
    return uid, auth._make_jwt(user)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent(client) -> None:
    _, token = await _user()
    first = await client.post("/api/gl/bootstrap", json={}, headers=_headers(token))
    assert first.status_code == 200, first.text
    created = first.json()["accounts_created"]
    assert created == len(DEFAULT_CHART)

    second = await client.post("/api/gl/bootstrap", json={}, headers=_headers(token))
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["accounts_created"] == 0, "重复建账不能再加科目"
    assert body["period"]["id"] == first.json()["period"]["id"], "重复建账不能另开期间"


@pytest.mark.asyncio
async def test_import_creates_balanced_draft_entries(client) -> None:
    _, token = await _user()
    boot = await client.post("/api/gl/bootstrap", json={}, headers=_headers(token))
    assert boot.status_code == 200, boot.text
    accounts = (await client.get("/api/gl/accounts", headers=_headers(token))).json()["accounts"]
    # 银行账户就是 1001 银行存款这个科目，不需要另建"银行账户"对象
    bank = next(a for a in accounts if a["code"] == "1001")

    csv_text = (
        "date,amount,direction,counterparty,memo\n"
        "2026-11-03,-300,out,房东,11月房租\n"
        "2026-11-10,500,in,公司,工资\n"
    )
    resp = await client.post(
        "/api/bank/import",
        json={"bank_account_id": bank["id"], "csv": csv_text},
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 2
    assert body["entries_created"] == 2, "每条流水都应生成一张草稿凭证"

    entries = (await client.get("/api/gl/entries", headers=_headers(token))).json()["entries"]
    assert len(entries) == 2
    assert all(e["status"] == "draft" for e in entries)
    # 借贷必须自平：收入 500 - 房租 300 = 净流入 200
    for e in entries:
        # 注意：GET /api/gl/entries/{id} 直接返回凭证本体（POST 才包一层 {"entry": …}）
        detail = (await client.get(f"/api/gl/entries/{e['id']}", headers=_headers(token))).json()
        lines = detail["lines"]
        debit = sum(float(line["debit"]) for line in lines)
        credit = sum(float(line["credit"]) for line in lines)
        assert abs(debit - credit) < 0.01, f"{e['entry_no']} 借贷不平"


@pytest.mark.asyncio
async def test_import_then_report_without_any_manual_step(client) -> None:
    """定位验收：只导入流水，不改任何科目/凭证，报表就能出来。"""
    _, token = await _user()
    await client.post("/api/gl/bootstrap", json={}, headers=_headers(token))
    accounts = (await client.get("/api/gl/accounts", headers=_headers(token))).json()["accounts"]
    bank = next(a for a in accounts if a["code"] == "1001")

    csv_text = "date,amount,direction,counterparty,memo\n2026-11-05,-200,out,餐厅,午餐\n"
    resp = await client.post(
        "/api/bank/import",
        json={"bank_account_id": bank["id"], "csv": csv_text},
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.text

    report = await client.post(
        "/api/statements/from-gl", json={"auto_post": True}, headers=_headers(token)
    )
    assert report.status_code == 200, report.text
    data = report.json()
    assert data["auto_posted"] == 1
    pl = data["payload"]["periods"][0]["income_statement"]
    assert pl["expenses"] == 200.0
    assert pl["net_profit"] == -200.0
