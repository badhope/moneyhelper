"""4.18.0 多主体合并：范围校验、只读过账总账、抵销分录与权限边界。"""

from __future__ import annotations

from datetime import date

import pytest
from app import db
from app.db.db_write_txn import write_txn


async def _post_sale(tenant_id: int, amount: float) -> None:
    await db.gl_bootstrap(tenant_id, ref_date=date.today().isoformat())
    accounts = await db.gl_list_accounts(tenant_id)
    cash = next(a for a in accounts if str(a["code"]) == "1001")
    revenue = next(a for a in accounts if str(a["code"]) == "6001")
    entry = await db.gl_create_entry(
        tenant_id,
        date.today().isoformat(),
        "合并测试销售",
        [
            {"account_id": cash["id"], "debit": amount, "credit": 0},
            {"account_id": revenue["id"], "debit": 0, "credit": amount},
        ],
    )
    await db.gl_post_entry(tenant_id, entry["id"])


@pytest.mark.asyncio
async def test_group_scope_validation(client) -> None:
    group = await db.consolidation_create_group(0, "测试集团")
    await db.consolidation_add_entity(
        0, group["id"], tenant_id=0, ownership_pct=100, method="proportional"
    )
    with pytest.raises(ValueError, match="已在合并范围"):
        await db.consolidation_add_entity(0, group["id"], tenant_id=0)
    with pytest.raises(ValueError, match="full"):
        await db.consolidation_add_entity(
            0, group["id"], tenant_id=0, ownership_pct=80, method="full"
        )
    with pytest.raises(ValueError, match="无权"):
        await db.consolidation_add_entity(99, group["id"], tenant_id=0)
    with pytest.raises(ValueError, match="同名"):
        await db.consolidation_create_group(0, "测试集团")

    resp = await client.get("/api/consolidation/groups")
    assert resp.status_code == 200, resp.text
    assert any(g["id"] == group["id"] for g in resp.json()["groups"])


@pytest.mark.asyncio
async def test_consolidation_combines_posted_and_excludes_missing(client) -> None:
    group = await db.consolidation_create_group(0, "演示控股")
    await db.consolidation_add_entity(
        0, group["id"], tenant_id=0, ownership_pct=100, method="full"
    )
    child = await db.consolidation_create_entity(
        0, group["id"], name="演示子公司", ownership_pct=80, method="proportional"
    )
    empty = await db.consolidation_create_entity(
        0, group["id"], name="未过账主体", ownership_pct=100, method="full"
    )
    await _post_sale(0, 600)
    await _post_sale(child["tenant_id"], 500)
    period = date.today().strftime("%Y-%m")

    out = await db.consolidation_report(0, group["id"], period)
    assert len(out["entities"]) == 3
    ok = [e for e in out["entities"] if e["status"] == "ok"]
    skipped = [e for e in out["entities"] if e["status"] == "no_posted"]
    assert len(ok) == 2 and len(skipped) == 1
    assert out["summary"]["reported"]["revenue"] == 1100.0
    assert out["summary"]["included"]["revenue"] == 1000.0
    assert out["summary"]["consolidated"]["revenue"] == 1000.0
    assert out["summary"]["consolidated"]["total_assets"] == 1000.0
    assert out["balanced"] is True
    assert any("缺账" in w or "没有已过账" in w for w in out["warnings"])
    assert out["period"] == period

    resp = await client.get(
        f"/api/consolidation/groups/{group['id']}/report?period={period}"
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["summary"]["consolidated"]["revenue"] == 1000.0
    assert payload["entities"][0]["tenant_id"] == 0

    detail = await client.get(f"/api/consolidation/groups/{group['id']}")
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["entities"]) == 3
    assert empty["tenant_id"] in {e["tenant_id"] for e in detail.json()["entities"]}


@pytest.mark.asyncio
async def test_adjustment_must_balance_and_changes_consolidation(client) -> None:
    group = await db.consolidation_create_group(0, "抵销测试集团")
    await db.consolidation_add_entity(0, group["id"], tenant_id=0)
    await _post_sale(0, 600)
    period = date.today().strftime("%Y-%m")

    with pytest.raises(ValueError, match="借贷不平衡"):
        await db.consolidation_create_adjustment(
            0, group["id"], period=period, description="不平抵销",
            lines=[
                {"account_code": "6001", "debit_cents": 20000, "credit_cents": 0},
                {"account_code": "1001", "debit_cents": 0, "credit_cents": 10000},
            ],
        )
    with pytest.raises(ValueError, match="科目"):
        await db.consolidation_create_adjustment(
            0, group["id"], period=period, description="未知科目",
            lines=[
                {"account_code": "9999", "debit_cents": 10000, "credit_cents": 0},
                {"account_code": "1001", "debit_cents": 0, "credit_cents": 10000},
            ],
        )

    adj = await db.consolidation_create_adjustment(
        0, group["id"], period=period, description="内部销售抵销",
        lines=[
            {"account_code": "6001", "debit_cents": 20000, "credit_cents": 0},
            {"account_code": "1001", "debit_cents": 0, "credit_cents": 20000},
        ],
    )
    out = await db.consolidation_report(0, group["id"], period)
    assert out["summary"]["consolidated"]["revenue"] == 400.0
    assert out["summary"]["consolidated"]["total_assets"] == 400.0
    assert out["summary"]["eliminations"]["vouchers"] == 1
    assert out["balanced"] is True

    removed = await db.consolidation_delete_adjustment(0, group["id"], adj["voucher_id"])
    assert removed["ok"] is True
    out2 = await db.consolidation_report(0, group["id"], period)
    assert out2["summary"]["consolidated"]["revenue"] == 600.0
    assert out2["summary"]["eliminations"]["vouchers"] == 0


@pytest.mark.asyncio
async def test_report_rejects_empty_scope_and_bad_period(client) -> None:
    group = await db.consolidation_create_group(0, "空集团")
    with pytest.raises(ValueError, match="合并范围为空"):
        await db.consolidation_report(0, group["id"], "2026-11")
    resp = await client.get(
        f"/api/consolidation/groups/{group['id']}/report?period=2026-13"
    )
    assert resp.status_code == 400
    assert "期间" in resp.json()["error"]


@pytest.mark.asyncio
async def test_demo_seed_builds_consolidation_group(client) -> None:
    demo = {"X-Demo-Mode": "1"}
    entered = await client.post("/api/demo/enter", headers=demo)
    assert entered.status_code == 200, entered.text
    groups = (await client.get("/api/consolidation/groups", headers=demo)).json()["groups"]
    demo_group = next(g for g in groups if g["id"] == "grp_demo")
    assert demo_group["entity_count"] == 3

    report = (
        await client.get(
            "/api/consolidation/groups/grp_demo/report?period=2026-11", headers=demo
        )
    ).json()
    statuses = {e["tenant_id"]: e["status"] for e in report["entities"]}
    assert statuses[10000001] == "ok"
    assert statuses[10000002] == "ok"
    assert statuses[10000003] == "missing"
    assert report["summary"]["eliminations"]["vouchers"] == 1
    assert report["summary"]["reported"]["revenue"] > 0


@pytest.mark.asyncio
async def test_report_excludes_entity_after_access_revoked() -> None:
    group = await db.consolidation_create_group(0, "权限复查集团")
    member = await db.consolidation_create_entity(
        0, group["id"], name="权限将失效主体", ownership_pct=100, method="full"
    )
    async with write_txn() as conn:
        await conn.execute(
            "DELETE FROM org_memberships WHERE tenant_id=? AND user_id=?",
            (member["tenant_id"], 0),
        )
    with pytest.raises(ValueError, match="没有可用主体"):
        await db.consolidation_report(0, group["id"], date.today().strftime("%Y-%m"))


@pytest.mark.asyncio
async def test_adjustment_rejects_nan_and_fractional_cents() -> None:
    group = await db.consolidation_create_group(0, "金额校验集团")
    await db.consolidation_add_entity(0, group["id"], tenant_id=0)
    await _post_sale(0, 100)
    period = date.today().strftime("%Y-%m")
    with pytest.raises(ValueError, match="持股比例"):
        await db.consolidation_add_entity(
            0, group["id"], tenant_id=0, ownership_pct=float("nan")
        )
    with pytest.raises(ValueError, match="整数分"):
        await db.consolidation_create_adjustment(
            0, group["id"], period=period, description="小数分",
            lines=[
                {"account_code": "6001", "debit_cents": 100.5, "credit_cents": 0},
                {"account_code": "1001", "debit_cents": 0, "credit_cents": 100.5},
            ],
        )
