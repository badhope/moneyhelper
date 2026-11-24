"""4.23-4.25 托管台：策略边界、待确认、自动执行与留痕。"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from app import autopilot, db
from app.db import attribution as attribution_db
from app.db.tenant import current_tenant_id, current_user_id


async def _fake_channels() -> dict[str, Any]:
    return {
        "channels": [
            {
                "channel_id": "smtp",
                "label": "代账邮箱",
                "kinds": ["tax", "payment"],
                "ready": True,
                "config": {"to_addrs": ["accountant@example.com"]},
            }
        ]
    }


async def _prepare_tax() -> str:
    period = date.today().strftime("%Y-%m")
    day = date.today().isoformat()
    await db.gl_bootstrap(0, ref_date=day)
    accounts = {a["code"]: a for a in await db.gl_list_accounts(0)}
    entry = await db.gl_create_entry(
        0,
        day,
        "托管台测试销售",
        [
            {"account_id": accounts["1001"]["id"], "debit": 900, "credit": 0},
            {"account_id": accounts["6001"]["id"], "debit": 0, "credit": 900},
        ],
    )
    await db.gl_post_entry(0, entry["id"])
    return period


@pytest.mark.asyncio
async def test_manual_mode_only_prepares_plan(client, monkeypatch) -> None:
    monkeypatch.setattr(autopilot, "list_channels", _fake_channels)
    period = await _prepare_tax()
    run = await client.post(
        "/api/autopilot/actions/tax_deliver/run", json={"period": period}
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["decision"] == "manual"
    assert body["channel_id"] == "smtp"
    assert "outcome" not in body
    decisions = await client.get("/api/autopilot/decisions")
    assert decisions.status_code == 200
    assert decisions.json()["items"][0]["decision"] == "manual"


@pytest.mark.asyncio
async def test_manual_mode_cannot_be_confirmed_into_execution(client, monkeypatch) -> None:
    monkeypatch.setattr(autopilot, "list_channels", _fake_channels)
    period = await _prepare_tax()
    called: list[dict[str, Any]] = []

    async def fake_execute(plan: dict[str, Any]) -> dict[str, Any]:
        called.append(plan)
        return {"delivery": {"status": "accepted"}}

    monkeypatch.setattr(autopilot, "_execute_plan", fake_execute)
    run = await client.post(
        "/api/autopilot/actions/tax_deliver/run",
        json={"period": period, "confirm": True},
    )
    assert run.status_code == 200, run.text
    assert run.json()["decision"] == "manual"
    assert "outcome" not in run.json()
    assert called == []

@pytest.mark.asyncio
async def test_assist_mode_waits_then_confirms(client, monkeypatch) -> None:
    monkeypatch.setattr(autopilot, "list_channels", _fake_channels)
    period = await _prepare_tax()

    async def fake_execute(plan: dict[str, Any]) -> dict[str, Any]:
        return {"delivery": {"status": "accepted", "receipt": {"id": "R-ASSIST"}}}

    monkeypatch.setattr(autopilot, "_execute_plan", fake_execute)
    policy = await client.put(
        "/api/autopilot/policies/tax_deliver",
        json={"mode": "assist", "enabled": True, "config": {"max_amount": 0}},
    )
    assert policy.status_code == 200, policy.text
    first = await client.post(
        "/api/autopilot/actions/tax_deliver/run", json={"period": period}
    )
    assert first.status_code == 200, first.text
    assert first.json()["decision"] == "awaiting"
    again = await client.post(
        "/api/autopilot/actions/tax_deliver/run",
        json={"period": period, "confirm": True},
    )
    assert again.status_code == 200, again.text
    assert again.json()["decision"] == "executed"


@pytest.mark.asyncio
async def test_auto_mode_respects_amount_threshold(client, monkeypatch) -> None:
    monkeypatch.setattr(autopilot, "list_channels", _fake_channels)
    period = await _prepare_tax()

    async def fake_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "action_key": "tax_deliver",
            "decision": "ready",
            "period": period,
            "packet_id": "P-THRESHOLD",
            "channel_id": "smtp",
            "amount": 900.0,
            "max_amount": 1.0,
            "requires_confirmation": True,
            "confirm_reason": "税费净额 ¥900.00 超过预设阈值 ¥1.00",
        }

    monkeypatch.setattr(autopilot, "build_plan", fake_plan)
    policy = await client.put(
        "/api/autopilot/policies/tax_deliver",
        json={"mode": "auto", "enabled": True, "config": {"max_amount": 1}},
    )
    assert policy.status_code == 200, policy.text
    run = await client.post(
        "/api/autopilot/actions/tax_deliver/run", json={"period": period}
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["decision"] == "awaiting"
    assert "超过预设阈值" in body["confirm_reason"]
    assert body["amount"] > 1


@pytest.mark.asyncio
async def test_auto_mode_executes_within_rule(client, monkeypatch) -> None:
    monkeypatch.setattr(autopilot, "list_channels", _fake_channels)
    called: list[dict[str, Any]] = []

    async def fake_execute(plan: dict[str, Any]) -> dict[str, Any]:
        called.append(plan)
        return {"delivery": {"status": "accepted", "receipt": {"id": "R-TEST"}}}

    monkeypatch.setattr(autopilot, "_execute_plan", fake_execute)
    period = await _prepare_tax()
    policy = await client.put(
        "/api/autopilot/policies/tax_deliver",
        json={"mode": "auto", "enabled": True, "config": {"max_amount": 50000}},
    )
    assert policy.status_code == 200, policy.text
    run = await client.post(
        "/api/autopilot/actions/tax_deliver/run", json={"period": period}
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["decision"] == "executed"
    assert len(called) == 1
    assert called[0]["channel_id"] == "smtp"


@pytest.mark.asyncio
async def test_dry_run_never_executes(client, monkeypatch) -> None:
    monkeypatch.setattr(autopilot, "list_channels", _fake_channels)
    period = await _prepare_tax()
    called: list[dict[str, Any]] = []

    async def fake_execute(plan: dict[str, Any]) -> dict[str, Any]:
        called.append(plan)
        return {"delivery": {"status": "accepted"}}

    monkeypatch.setattr(autopilot, "_execute_plan", fake_execute)
    policy = await client.put(
        "/api/autopilot/policies/tax_deliver",
        json={"mode": "auto", "enabled": True, "config": {"max_amount": 50000}},
    )
    assert policy.status_code == 200, policy.text
    run = await client.post(
        "/api/autopilot/actions/tax_deliver/run",
        json={"period": period, "dry_run": True},
    )
    assert run.status_code == 200, run.text
    assert run.json()["decision"] == "manual"
    assert run.json()["dry_run"] is True
    assert "outcome" not in run.json()
    assert called == []

@pytest.mark.asyncio
async def test_negative_threshold_is_rejected(client) -> None:
    resp = await client.put(
        "/api/autopilot/policies/tax_deliver",
        json={"mode": "auto", "enabled": True, "config": {"max_amount": -1}},
    )
    assert resp.status_code == 400, resp.text
    assert "阈值" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_disabled_policy_blocks_execution(client, monkeypatch) -> None:
    monkeypatch.setattr(autopilot, "list_channels", _fake_channels)
    await _prepare_tax()
    policy = await client.put(
        "/api/autopilot/policies/month_end_close",
        json={"mode": "auto", "enabled": False, "config": {}},
    )
    assert policy.status_code == 200, policy.text
    run = await client.post("/api/autopilot/actions/month_end_close/run", json={})
    assert run.status_code == 200, run.text
    assert run.json()["decision"] == "blocked"
    assert "停用" in run.json()["reason"]


async def _attribution_rule(keyword: str, category: str) -> dict[str, Any]:
    return await attribution_db.create_rule(
        tenant_id=current_tenant_id(),
        user_id=current_user_id(),
        name=f"托管测试规则-{keyword}",
        keyword=keyword,
        category=category,
        direction="支出",
        priority=10,
    )


@pytest.mark.asyncio
async def test_attribution_auto_confirms_rule_hit(client) -> None:
    period = date.today().strftime("%Y-%m")
    day = date.today().isoformat()
    await _attribution_rule("托管归因专用", "测试餐饮")
    tx = await db.add_transaction(day, "托管归因专用商户 8848", "其他", -88)
    policy = await client.put(
        "/api/autopilot/policies/attribution_confirm",
        json={
            "mode": "auto",
            "enabled": True,
            "config": {"max_amount": 10000, "min_confidence": 0.7},
        },
    )
    assert policy.status_code == 200, policy.text
    run = await client.post(
        "/api/autopilot/actions/attribution_confirm/run",
        json={"period": period},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["decision"] == "executed"
    assert body["outcome"]["confirmed"] >= 1
    rows = await db.list_transactions_by_month(period)
    row = next(r for r in rows if int(r["id"]) == int(tx["id"]))
    assert row["category"] == "测试餐饮"


@pytest.mark.asyncio
async def test_attribution_does_not_auto_confirm_history(client) -> None:
    period = date.today().strftime("%Y-%m")
    day = date.today().isoformat()
    await db.add_transaction(day, "历史同类测试商户 9921", "餐饮", -20)
    await db.add_transaction(day, "历史同类测试商户 9922", "餐饮", -21)
    current = await db.add_transaction(day, "历史同类测试商户 9923", "其他", -22)
    plan = await autopilot.build_plan(
        "attribution_confirm",
        period=period,
        config={"max_amount": 10000, "min_confidence": 0.7},
    )
    ids = {int(item["transaction_id"]) for item in plan.get("items") or []}
    assert int(current["id"]) not in ids
    assert all(
        item["source"] in {"custom_rule", "rule"}
        for item in plan.get("items") or []
    )


@pytest.mark.asyncio
async def test_attribution_batch_amount_stops_for_confirmation(client) -> None:
    period = date.today().strftime("%Y-%m")
    day = date.today().isoformat()
    await _attribution_rule("托管大额归因", "测试大额")
    first = await db.add_transaction(day, "托管大额归因 A", "其他", -6000)
    second = await db.add_transaction(day, "托管大额归因 B", "其他", -6000)
    policy = await client.put(
        "/api/autopilot/policies/attribution_confirm",
        json={
            "mode": "auto",
            "enabled": True,
            "config": {"max_amount": 10000, "min_confidence": 0.7},
        },
    )
    assert policy.status_code == 200, policy.text
    run = await client.post(
        "/api/autopilot/actions/attribution_confirm/run", json={"period": period}
    )
    assert run.status_code == 200, run.text
    assert run.json()["decision"] == "awaiting"
    assert run.json()["requires_confirmation"] is True
    confirmed = await client.post(
        "/api/autopilot/actions/attribution_confirm/run",
        json={"period": period, "confirm": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["decision"] == "executed"
    rows = await db.list_transactions_by_month(period)
    by_id = {int(r["id"]): r for r in rows}
    assert by_id[int(first["id"])]["category"] == "测试大额"
    assert by_id[int(second["id"])]["category"] == "测试大额"


@pytest.mark.asyncio
async def test_attribution_confidence_must_be_in_range(client) -> None:
    resp = await client.put(
        "/api/autopilot/policies/attribution_confirm",
        json={
            "mode": "auto",
            "enabled": True,
            "config": {"max_amount": 10000, "min_confidence": 1.2},
        },
    )
    assert resp.status_code == 400, resp.text
    assert "置信度" in resp.json()["detail"]


async def _bank_account() -> dict[str, Any]:
    await db.gl_bootstrap(0, ref_date=date.today().isoformat())
    accounts = {a["code"]: a for a in await db.gl_list_accounts(0)}
    return accounts["1001"]


async def _bank_payment(account_id: int, amount: float, suffix: str) -> dict[str, Any]:
    from app.timeutil import now_str

    today = date.today().isoformat()
    conn = await db._conn()
    cur = await conn.execute(
        "INSERT INTO payments(tenant_id,payment_no,claim_id,amount_cents,payee,"
        "bank_account_id,method,status,paid_at,note,created_at,updated_at)"
        " VALUES(0,?,0,?,?,?,'bank','paid',?, '',?,?)",
        (
            f"PAY-4250-{suffix}",
            round(amount * 100),
            f"测试收款方 {suffix}",
            int(account_id),
            f"{today} 10:00:00",
            now_str(),
            now_str(),
        ),
    )
    await conn.commit()
    return await db.payment_get(0, int(cur.lastrowid or 0))


async def _bank_txn(account_id: int, amount: float, suffix: str) -> dict[str, Any]:
    return await db.bank_create(
        0,
        int(account_id),
        date.today().isoformat(),
        "out",
        amount,
        counterparty=f"测试收款方 {suffix}",
        memo=f"流水 {suffix}",
        bank_ref=f"REF-{suffix}",
    )


@pytest.mark.asyncio
async def test_bank_match_auto_executes_unique_pair(client) -> None:
    account = await _bank_account()
    payment = await _bank_payment(account["id"], 148.0, "A")
    txn = await _bank_txn(account["id"], 148.0, "A")
    policy = await client.put(
        "/api/autopilot/policies/bank_match",
        json={"mode": "auto", "enabled": True, "config": {"max_amount": 10000}},
    )
    assert policy.status_code == 200, policy.text
    period = date.today().strftime("%Y-%m")
    run = await client.post(
        "/api/autopilot/actions/bank_match/run", json={"period": period}
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["decision"] == "executed", body
    assert body["outcome"]["matched"] == 1
    txns = [t for t in await db.bank_list(0, status="matched") if t["id"] == txn["id"]]
    assert len(txns) == 1
    assert txns[0]["payment_id"] == payment["id"]


@pytest.mark.asyncio
async def test_bank_match_ambiguous_is_left_for_human(client) -> None:
    account = await _bank_account()
    await _bank_payment(account["id"], 220.0, "B1")
    await _bank_payment(account["id"], 220.0, "B2")
    txn = await _bank_txn(account["id"], 220.0, "B")
    period = date.today().strftime("%Y-%m")
    plan = await autopilot.build_plan("bank_match", period=period)
    assert plan["decision"] == "blocked"
    assert "不唯一" in plan["reason"]
    assert plan["ambiguous"] == 1
    assert (await db.bank_get(0, txn["id"]))["status"] == "unmatched"


@pytest.mark.asyncio
async def test_bank_match_amount_cap_waits_then_confirms(client) -> None:
    account = await _bank_account()
    await _bank_payment(account["id"], 148.0, "C1")
    await _bank_payment(account["id"], 220.0, "C2")
    await _bank_txn(account["id"], 148.0, "C1")
    await _bank_txn(account["id"], 220.0, "C2")
    policy = await client.put(
        "/api/autopilot/policies/bank_match",
        json={"mode": "auto", "enabled": True, "config": {"max_amount": 100}},
    )
    assert policy.status_code == 200, policy.text
    period = date.today().strftime("%Y-%m")
    first = await client.post(
        "/api/autopilot/actions/bank_match/run", json={"period": period}
    )
    assert first.status_code == 200, first.text
    assert first.json()["decision"] == "awaiting"
    assert first.json()["amount"] == 368.0
    again = await client.post(
        "/api/autopilot/actions/bank_match/run",
        json={"period": period, "confirm": True},
    )
    assert again.status_code == 200, again.text
    assert again.json()["decision"] == "executed"
    assert again.json()["outcome"]["matched"] == 2


@pytest.mark.asyncio
async def test_bank_match_batch_rolls_back_on_stale_plan(client) -> None:
    account = await _bank_account()
    payment_one = await _bank_payment(account["id"], 148.0, "D1")
    await _bank_payment(account["id"], 220.0, "D2")
    txn_one = await _bank_txn(account["id"], 148.0, "D1")
    txn_two = await _bank_txn(account["id"], 220.0, "D2")
    period = date.today().strftime("%Y-%m")
    plan = await autopilot.build_plan("bank_match", period=period)
    assert plan["decision"] == "ready"
    await db.bank_match(0, txn_one["id"], payment_one["id"], 0)
    with pytest.raises(ValueError):
        await autopilot._execute_bank_match(plan)
    assert (await db.bank_get(0, txn_two["id"]))["status"] == "unmatched"
    assert (await db.bank_get(0, txn_two["id"]))["payment_id"] is None


@pytest.mark.asyncio
async def test_bank_match_window_must_be_integral_and_in_range(client) -> None:
    for days in (1.5, 31):
        resp = await client.put(
            "/api/autopilot/policies/bank_match",
            json={
                "mode": "auto",
                "enabled": True,
                "config": {"max_amount": 50000, "window_days": days},
            },
        )
        assert resp.status_code == 400, resp.text
        assert "日期窗口" in resp.json()["detail"]
