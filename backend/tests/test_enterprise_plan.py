"""4.19.0 企业预算与资金计划：口径、校验与只读实际数。"""

from __future__ import annotations

from datetime import date

import pytest
from app import db


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
async def test_budget_report_uses_posted_and_flags_over(client) -> None:
    await _post(0, "2026-11-05", "销售收入", [("1001", 1200, 0), ("6001", 0, 1200)])
    await _post(0, "2026-11-20", "管理费用", [("6602", 900, 0), ("1001", 0, 900)])
    saved = await db.budget_plan_save(
        0, "2026-11",
        [
            {"account_code": "6001", "amount": 1000},
            {"account_code": "6602", "amount": 800},
        ],
        note="测试预算",
    )
    assert saved["exists"] is True
    report = await db.budget_report(0, "2026-11")
    assert report["period_status"] == "open"
    row6001 = next(r for r in report["rows"] if r["account_code"] == "6001")
    row6602 = next(r for r in report["rows"] if r["account_code"] == "6602")
    assert row6001["actual"] == 1200 and row6001["status"] == "within"
    assert row6602["actual"] == 900 and row6602["status"] == "over"
    assert report["totals"]["actual_income"] == 1200
    assert report["totals"]["actual_expense"] == 900

    with pytest.raises(ValueError, match="不是收入或费用"):
        await db.budget_plan_save(0, "2026-11", [{"account_code": "1001", "amount": 1}])
    with pytest.raises(ValueError, match="不能为负"):
        await db.budget_plan_save(0, "2026-11", [{"account_code": "6001", "amount": -1}])
    with pytest.raises(ValueError, match="YYYY-MM"):
        await db.budget_report(0, "2026/11")


@pytest.mark.asyncio
async def test_budget_report_excludes_draft(client) -> None:
    await _post(0, "2026-11-05", "已过账收入", [("1001", 500, 0), ("6001", 0, 500)])
    await db.budget_plan_save(0, "2026-11", [{"account_code": "6001", "amount": 800}])
    accounts = {a["code"]: a for a in await db.gl_list_accounts(0)}
    await db.gl_create_entry(
        0, "2026-11-20", "草稿收入",
        [
            {"account_id": accounts["1001"]["id"], "debit": 300, "credit": 0},
            {"account_id": accounts["6001"]["id"], "debit": 0, "credit": 300},
        ],
    )
    report = await db.budget_report(0, "2026-11")
    row = next(r for r in report["rows"] if r["account_code"] == "6001")
    assert row["actual"] == 500
    assert report["draft_entries"] >= 1
    assert any("草稿" in w for w in report["warnings"])


@pytest.mark.asyncio
async def test_cash_plan_and_actual_comparison(client) -> None:
    await _post(0, "2026-11-05", "客户回款", [("1001", 1200, 0), ("6001", 0, 1200)])
    await _post(0, "2026-11-20", "供应商付款", [("6602", 900, 0), ("1001", 0, 900)])
    saved = await db.cash_plan_save(
        0, "2026-11",
        [
            {"expected_date": "2026-11-05", "direction": "in", "amount": 1200},
            {"expected_date": "2026-11-20", "direction": "out", "amount": 900},
        ],
        opening=500, target_min=400,
    )
    assert saved["exists"] is True
    report = await db.cash_report(0, "2026-11")
    assert report["projected_end"] == 800
    assert report["series"][0]["planned_in"] == 1200
    assert report["series"][-1]["actual_balance"] == 800
    assert report["warnings"] == [] or all("差" not in w for w in report["warnings"])

    with pytest.raises(ValueError, match="必须落在 2026-11"):
        await db.cash_plan_save(
            0, "2026-11",
            [{"expected_date": "2026-12-01", "direction": "in", "amount": 10}],
        )
    with pytest.raises(ValueError, match="方向"):
        await db.cash_plan_save(
            0, "2026-11",
            [{"expected_date": "2026-11-01", "direction": "sideways", "amount": 10}],
        )
    with pytest.raises(ValueError, match="1001 或 1002"):
        await db.cash_plan_save(
            0, "2026-11",
            [{"expected_date": "2026-11-01", "direction": "in", "amount": 10, "account_code": "6001"}],
        )


@pytest.mark.asyncio
async def test_plan_api_contract(client) -> None:
    await db.gl_bootstrap(0, ref_date="2026-11-01")
    resp = await client.get("/api/plan/budget?period=2026-11")
    assert resp.status_code == 200, resp.text
    resp = await client.put(
        "/api/plan/budget",
        json={"period": "2026-11", "lines": [{"account_code": "6001", "amount": 100}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    resp = await client.get("/api/plan/cash?period=2026-11")
    assert resp.status_code == 200, resp.text
    assert "boundary" in resp.json()
