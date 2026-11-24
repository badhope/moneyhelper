"""4.17.1 财税时序与归因确认：真实总账聚合、规则候选、确认落库。"""

from __future__ import annotations

from datetime import date

import pytest
from app import db
from app.db import attribution as attribution_db


@pytest.mark.asyncio
async def test_timeline_aggregates_posted_gl_only(client) -> None:
    today = date.today()
    await db.gl_bootstrap(0, ref_date=today.isoformat())
    accounts = await db.gl_list_accounts(0)
    cash = next(a for a in accounts if str(a["code"]) == "1001")
    revenue = next(a for a in accounts if str(a["code"]) == "6001")
    expense = next(a for a in accounts if str(a["code"]) == "6602")
    tax = next(a for a in accounts if str(a["code"]) == "2203")

    sale = await db.gl_create_entry(
        0,
        today.isoformat(),
        "销售收款",
        [
            {"account_id": cash["id"], "debit": 1130, "credit": 0},
            {"account_id": revenue["id"], "debit": 0, "credit": 1000},
            {"account_id": tax["id"], "debit": 0, "credit": 130},
        ],
    )
    await db.gl_post_entry(0, sale["id"])

    rent = await db.gl_create_entry(
        0,
        today.isoformat(),
        "房租",
        [
            {"account_id": expense["id"], "debit": 200, "credit": 0},
            {"account_id": cash["id"], "debit": 0, "credit": 200},
        ],
    )
    await db.gl_post_entry(0, rent["id"])

    # 草稿不计入：金额 999 不应出现在任何统计里。
    draft = await db.gl_create_entry(
        0,
        today.isoformat(),
        "草稿销售",
        [
            {"account_id": cash["id"], "debit": 999, "credit": 0},
            {"account_id": revenue["id"], "debit": 0, "credit": 999},
        ],
    )
    assert draft["status"] == "draft"

    out = await db.finance_timeline(0, months=3)
    assert len(out["months"]) == 3
    assert out["range"]["to"] == today.strftime("%Y-%m")
    this_month = out["months"][-1]
    assert this_month["month"] == today.strftime("%Y-%m")
    assert this_month["status"] == "open"
    assert this_month["source"] == "gl_posted"
    assert this_month["income"] == 1000.0
    assert this_month["expense"] == 200.0
    assert this_month["profit"] == 800.0
    assert this_month["cash_in"] == 1130.0
    assert this_month["cash_out"] == 200.0
    assert this_month["cash_net"] == 930.0
    assert this_month["tax_accrued"] == 130.0
    assert this_month["tax_paid"] == 0.0
    assert this_month["tax_net"] == 130.0
    assert this_month["posted_entries"] == 2
    assert this_month["draft_entries"] == 1
    assert out["months"][0]["status"] == "missing"

    resp = await client.get("/api/finance/timeline?months=3")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["months"][-1]["income"] == 1000.0


@pytest.mark.asyncio
async def test_attribution_candidates_and_confirm(client) -> None:
    today = date.today().isoformat()
    await db.add_transaction(today, "星巴克咖啡", "其他", -32.0)
    await db.add_transaction(today, "11月房租", "其他", -2200.0)
    await db.add_transaction(today, "某某科技", "其他", -88.0)

    resp = await client.get("/api/finance/attribution/candidates?limit=10")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pending"] == 3, body
    assert body["source"] == "rules+history"
    assert all(t["needs_review"] for t in body["transactions"])
    rule_rows = [t for t in body["transactions"] if t["candidate"]["category"]]
    assert rule_rows
    assert all(t["candidate"]["reason"] for t in rule_rows)

    target = next(t for t in body["transactions"] if "星巴克" in t["item"])
    assert target["candidate"]["category"] == "餐饮"

    confirm = await client.post(
        "/api/finance/attribution/confirm",
        json={
            "transaction_id": target["transaction_id"],
            "category": "餐饮",
            "source": "rule",
            "rule_id": target["candidate"]["rule_id"],
            "confidence": target["candidate"]["confidence"],
            "matched": target["candidate"]["matched"],
        },
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["ok"] is True
    assert confirm.json()["previous_category"] == "其他"

    rows = await db.list_transactions(limit=20)
    updated = next(t for t in rows if int(t["id"]) == target["transaction_id"])
    assert updated["category"] == "餐饮"

    conf = await attribution_db.get_confirmation(0, 0, target["transaction_id"])
    assert conf is not None
    assert conf["confirmed_category"] == "餐饮"
    assert conf["source"] == "rule"
    assert conf["matched"] == target["candidate"]["matched"]

    after = (await client.get("/api/finance/attribution/candidates?limit=10")).json()
    assert after["pending"] == 2
    assert after["resolved"] >= 1

    bad = await client.post(
        "/api/finance/attribution/confirm",
        json={"transaction_id": target["transaction_id"], "category": "其他"},
    )
    assert bad.status_code == 400

    missing = await client.post(
        "/api/finance/attribution/confirm",
        json={"transaction_id": 999999, "category": "餐饮"},
    )
    assert missing.status_code == 400


@pytest.mark.asyncio
async def test_attribution_rules_batch_rollback_and_stats(client) -> None:
    today = date.today().isoformat()
    cloud = await db.add_transaction(today, "云 GPU 订阅", "其他", -50.0)
    taxi = await db.add_transaction(today, "夜里打车", "其他", -28.0)

    created = await client.post(
        "/api/finance/attribution/rules",
        json={
            "name": "云资源",
            "keyword": "云 GPU",
            "category": "办公软件",
            "direction": "支出",
            "priority": 10,
        },
    )
    assert created.status_code == 200, created.text
    rule_id = created.json()["rule"]["rule_id"]

    rules = (await client.get("/api/finance/attribution/rules")).json()
    assert rules["count"] == 1
    assert rules["rules"][0]["confirmed"] == 0
    assert "办公软件" in rules["categories"]

    test = await client.post(
        "/api/finance/attribution/rules/test",
        json={"item": "云 GPU 订阅 11 月", "direction": "支出", "amount": -50},
    )
    assert test.status_code == 200, test.text
    assert test.json()["matched"] is True
    assert test.json()["candidate"]["source"] == "custom_rule"

    body = (await client.get("/api/finance/attribution/candidates?limit=10")).json()
    row = next(t for t in body["transactions"] if "云 GPU" in t["item"])
    assert row["candidate"]["category"] == "办公软件"
    assert row["candidate"]["source"] == "custom_rule"
    assert row["candidate"]["rule_id"] == rule_id
    assert body["custom_rule_hits"][rule_id] >= 1

    disabled = await client.put(
        f"/api/finance/attribution/rules/{rule_id}", json={"enabled": False}
    )
    assert disabled.status_code == 200, disabled.text
    after_disable = (await client.get("/api/finance/attribution/candidates?limit=10")).json()
    assert not any(
        t["candidate"]["rule_id"] == rule_id for t in after_disable["transactions"]
    )
    restored = await client.put(
        f"/api/finance/attribution/rules/{rule_id}", json={"enabled": True}
    )
    assert restored.status_code == 200, restored.text

    rejected = await client.post(
        "/api/finance/attribution/confirm-batch",
        json={
            "items": [
                {"transaction_id": cloud["id"], "category": "办公软件", "source": "custom_rule"},
                {"transaction_id": 999999, "category": "交通"},
            ]
        },
    )
    assert rejected.status_code == 400
    rows_before = await db.list_transactions(limit=20)
    cloud_before = next(t for t in rows_before if int(t["id"]) == cloud["id"])
    assert cloud_before["category"] == "其他"

    batch = await client.post(
        "/api/finance/attribution/confirm-batch",
        json={
            "items": [
                {
                    "transaction_id": cloud["id"],
                    "category": "办公软件",
                    "source": "custom_rule",
                    "rule_id": rule_id,
                    "confidence": 0.92,
                    "matched": ["keyword:云 GPU"],
                },
                {
                    "transaction_id": taxi["id"],
                    "category": "交通",
                    "source": "manual",
                    "confidence": 1,
                    "matched": ["manual"],
                },
            ]
        },
    )
    assert batch.status_code == 200, batch.text
    assert batch.json()["confirmed"] == 2

    confirmed = (await client.get("/api/finance/attribution/confirmed?limit=10")).json()
    assert confirmed["count"] == 2
    assert any(int(r["transaction_id"]) == cloud["id"] for r in confirmed["items"])

    stats = (await client.get("/api/finance/attribution/stats")).json()
    assert stats["confirmed_total"] == 2
    assert stats["by_source"]["custom_rule"] == 1
    assert stats["by_source"]["manual"] == 1

    rollback = await client.post(
        "/api/finance/attribution/rollback", json={"transaction_id": cloud["id"]}
    )
    assert rollback.status_code == 200, rollback.text
    rows = await db.list_transactions(limit=20)
    restored_row = next(t for t in rows if int(t["id"]) == cloud["id"])
    assert restored_row["category"] == "其他"
    assert await attribution_db.get_confirmation(0, 0, cloud["id"]) is None
    stats2 = (await client.get("/api/finance/attribution/stats")).json()
    assert stats2["reverted_total"] == 1

    again = await client.post(
        "/api/finance/attribution/rollback", json={"transaction_id": cloud["id"]}
    )
    assert again.status_code == 400

    deleted = await client.delete(f"/api/finance/attribution/rules/{rule_id}")
    assert deleted.status_code == 200, deleted.text
    empty = (await client.get("/api/finance/attribution/rules")).json()
    assert empty["count"] == 0


@pytest.mark.asyncio
async def test_demo_reset_clears_attribution_state(client) -> None:
    demo = {"X-Demo-Mode": "1"}
    created = await client.post(
        "/api/finance/attribution/rules",
        headers=demo,
        json={
            "name": "演示规则",
            "keyword": "演示关键词",
            "category": "办公软件",
            "direction": "支出",
            "priority": 1,
        },
    )
    assert created.status_code == 200, created.text
    reset = await client.post("/api/demo/enter", headers=demo)
    assert reset.status_code == 200, reset.text
    rules = (await client.get("/api/finance/attribution/rules", headers=demo)).json()
    assert rules["count"] == 0
    stats = (await client.get("/api/finance/attribution/stats", headers=demo)).json()
    assert stats["confirmed_total"] == 0
    assert stats["reverted_total"] == 0
