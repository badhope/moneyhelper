"""自动化工作流台账：真实步骤、幂等、失败留痕。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from app import automation_runner, db
from app.automation_runner import list_workflows, recover_missed_month_end, run_workflow
from app.db import automation as automation_db


@pytest.mark.asyncio
async def test_workflow_runs_real_steps_and_persists(client) -> None:
    out = await run_workflow("personal_daily")
    assert out["status"] in {"done", "partial"}, out
    assert [s["name"] for s in out["steps"]] == [
        "订阅到期巡检",
        "连接源自动同步",
        "账单收件箱扫描",
    ]
    assert out["duration_ms"] >= 0
    runs = await automation_db.list_runs()
    assert runs and runs[0]["id"] == out["id"]
    assert runs[0]["steps"][0]["result"]["subscriptions"] >= 0


@pytest.mark.asyncio
async def test_month_end_workflow_closes_draft(client) -> None:
    prev_end = date.today().replace(day=1) - timedelta(days=1)
    await db.gl_bootstrap(0, ref_date=prev_end.isoformat())
    accounts = await db.gl_list_accounts(0)
    cash = next(a for a in accounts if str(a["code"]) == "1001")
    rent = next(a for a in accounts if str(a["code"]) == "6602")
    await db.gl_create_entry(
        0,
        prev_end.isoformat(),
        "自动化月结测试",
        [
            {"account_id": cash["id"], "debit": 100, "credit": 0},
            {"account_id": rent["id"], "debit": 0, "credit": 100},
        ],
    )

    out = await run_workflow("enterprise_month_end")
    assert out["status"] == "done", out
    assert out["steps"][0]["result"]["status"] == "done"
    assert out["steps"][1]["result"]["period"] == "closed"
    assert out["steps"][1]["result"]["drafts"] == 0


@pytest.mark.asyncio
async def test_idempotency_key_deduplicates(client) -> None:
    first = await run_workflow("personal_daily", idempotency_key="daily-2026-11-24")
    second = await run_workflow("personal_daily", idempotency_key="daily-2026-11-24")
    assert second["id"] == first["id"]
    assert second.get("deduplicated") is True


@pytest.mark.asyncio
async def test_unknown_workflow_rejected(client) -> None:
    with pytest.raises(ValueError):
        await run_workflow("not-exist")


def test_workflow_catalog_has_scopes() -> None:
    keys = {w["key"]: w for w in list_workflows()}
    assert keys["personal_daily"]["scope"] == "personal"
    assert keys["enterprise_month_end"]["scope"] == "enterprise"


@pytest.mark.asyncio
async def test_api_runs_and_history(client) -> None:
    resp = await client.get("/api/automation/workflows")
    assert resp.status_code == 200
    assert len(resp.json()["workflows"]) == 2

    run = await client.post("/api/automation/workflows/personal_daily/run", json={})
    assert run.status_code == 200
    assert run.json()["workflow"] == "personal_daily"

    hist = await client.get("/api/automation/runs?limit=5")
    assert hist.status_code == 200
    assert hist.json()["count"] >= 1


@pytest.mark.asyncio
async def test_step_retry_uses_backoff_and_records_attempts(client, monkeypatch) -> None:
    calls = {"n": 0}

    async def flaky() -> dict:
        calls["n"] += 1
        if calls["n"] < 3:
            return {"status": "failed", "error": "database is locked"}
        return {"status": "done", "value": 1}

    monkeypatch.setitem(
        automation_runner.WORKFLOWS,
        "retry_probe",
        {"name": "重试探针", "scope": "test", "description": "", "steps": [("探针", flaky)]},
    )
    monkeypatch.setitem(automation_runner.STEP_MAX_ATTEMPTS, "探针", 3)
    monkeypatch.setattr(automation_runner, "RETRY_BASE_SECONDS", 0)

    out = await run_workflow("retry_probe")
    assert out["status"] == "done", out
    assert calls["n"] == 3
    assert out["steps"][0]["attempts"] == 3
    assert out["steps"][0]["ok"] is True


@pytest.mark.asyncio
async def test_failed_run_creates_alert_and_can_be_acked_and_replayed(
    client, monkeypatch
) -> None:
    async def always_fail() -> dict:
        return {"status": "failed", "error": "boom"}

    monkeypatch.setitem(
        automation_runner.WORKFLOWS,
        "alert_probe",
        {"name": "告警探针", "scope": "test", "description": "", "steps": [("必败", always_fail)]},
    )

    out = await run_workflow("alert_probe")
    assert out["status"] == "failed"
    alerts = await automation_db.list_alerts(unread_only=True)
    assert alerts and alerts[0]["run_id"] == out["id"]
    assert alerts[0]["severity"] == "error"

    ack = await client.post(f"/api/automation/alerts/{alerts[0]['id']}/ack")
    assert ack.status_code == 200
    assert ack.json()["alert"]["acknowledged"] is True
    assert (await client.get("/api/automation/alerts?unread_only=true")).json()["unread"] == 0

    replay = await client.post(f"/api/automation/runs/{out['id']}/replay")
    assert replay.status_code == 200
    assert replay.json()["id"] != out["id"]
    assert replay.json()["trigger"] == "replay"
    assert replay.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_startup_catchup_closes_missed_period(client) -> None:
    prev_end = date.today().replace(day=1) - timedelta(days=1)
    await db.gl_bootstrap(0, ref_date=prev_end.isoformat())
    accounts = await db.gl_list_accounts(0)
    cash = next(a for a in accounts if str(a["code"]) == "1001")
    rent = next(a for a in accounts if str(a["code"]) == "6602")
    await db.gl_create_entry(
        0,
        prev_end.isoformat(),
        "停机补偿测试",
        [
            {"account_id": cash["id"], "debit": 233, "credit": 0},
            {"account_id": rent["id"], "debit": 0, "credit": 233},
        ],
    )

    out = await recover_missed_month_end(date.today(), hour=12)
    assert out["status"] == "done", out
    assert out["trigger"] == "catchup"
    assert out["steps"][0]["result"]["status"] == "done"
    assert out["steps"][1]["result"]["period"] == "closed"

    again = await recover_missed_month_end(date.today(), hour=12)
    assert again["status"] == "skipped"
    assert again["reason"] == "already_closed"
