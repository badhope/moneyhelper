"""M6.2 错误台账：评测错题沉淀到经验库。"""

from __future__ import annotations

import httpx
import pytest
from app import db, main


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    yield


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


async def test_ledger_requires_details_or_prior_run(client) -> None:
    r = await client.post("/api/eval/ledger", json={})
    assert r.status_code == 200
    assert r.json()["ok"] is False


async def test_ledger_writes_wrong_answers(client) -> None:
    details = [
        {"id": "P01", "passed": False, "reason": "数字不匹配", "answer_preview": "999"},
        {"id": "P02", "passed": True, "reason": "ok", "answer_preview": "1"},
    ]
    r = await client.post("/api/eval/ledger", json={"details": details, "model": "demo"})
    body = r.json()
    assert body["wrong"] == 1
    assert body["written"] == 1

    rows = await db.list_reflections(10)
    assert rows and "P01" in rows[0]["lesson"]
    assert rows[0]["tool"] == "eval:demo"


async def test_ledger_dedupes_same_question(client) -> None:
    details = [{"id": "P01", "passed": False, "reason": "r", "answer_preview": "x"}]
    await client.post("/api/eval/ledger", json={"details": details, "model": "demo"})
    await client.post("/api/eval/ledger", json={"details": details, "model": "demo"})
    rows = await db.list_reflections(50)
    same = [r for r in rows if "P01" in r["lesson"] and r["tool"] == "eval:demo"]
    assert len(same) == 1


async def test_ledger_list_endpoint(client) -> None:
    details = [{"id": "P02", "passed": False, "reason": "r", "answer_preview": "y"}]
    await client.post("/api/eval/ledger", json={"details": details, "model": "m2"})
    r = await client.get("/api/eval/ledger")
    assert r.status_code == 200
    assert any("P02" in x["lesson"] for x in r.json()["reflections"])
