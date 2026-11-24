"""自动化工作流台账：真实步骤、幂等、失败留痕。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from app import db
from app.automation_runner import list_workflows, run_workflow
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
