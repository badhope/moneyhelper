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
