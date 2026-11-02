"""M6.4 家庭议会：提案、投票、法定人数与多数决。"""

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


async def _members(n: int = 3) -> list[int]:
    ids = []
    for i in range(n):
        ids.append(await db.member_create(f"成员{i + 1}"))
    return ids


async def test_motion_requires_title(temp_db) -> None:
    with pytest.raises(ValueError):
        await db.create_motion("  ")


async def test_motion_flow_approved(temp_db) -> None:
    ids = await _members(3)
    m = await db.create_motion("换车", amount=150000, category="大额支出", proposer_id=ids[0])
    assert m["status"] == "voting"

    await db.cast_vote(m["id"], ids[0], "yes")
    await db.cast_vote(m["id"], ids[1], "yes")
    after = await db.cast_vote(m["id"], ids[2], "no")
    assert after["status"] == "approved"
    assert after["tally"]["yes"] == 2
    assert after["tally"]["no"] == 1


async def test_motion_rejected_when_majority_no(temp_db) -> None:
    ids = await _members(3)
    m = await db.create_motion("买游艇", amount=900000, proposer_id=ids[0])
    await db.cast_vote(m["id"], ids[0], "no")
    await db.cast_vote(m["id"], ids[1], "no")
    after = await db.cast_vote(m["id"], ids[2], "yes")
    assert after["status"] == "rejected"


async def test_vote_after_decided_rejected(temp_db) -> None:
    ids = await _members(2)
    m = await db.create_motion("测试", proposer_id=ids[0])
    await db.cast_vote(m["id"], ids[0], "yes")
    after = await db.cast_vote(m["id"], ids[1], "yes")
    assert after["status"] == "approved"
    with pytest.raises(ValueError, match="已结束"):
        await db.cast_vote(m["id"], ids[0], "no")


async def test_invalid_vote_value(temp_db) -> None:
    ids = await _members(1)
    m = await db.create_motion("测试")
    with pytest.raises(ValueError):
        await db.cast_vote(m["id"], ids[0], "maybe")


async def test_withdraw_motion(temp_db) -> None:
    ids = await _members(2)
    m = await db.create_motion("撤回测试", proposer_id=ids[0])
    out = await db.withdraw_motion(m["id"])
    assert out["status"] == "withdrawn"
    with pytest.raises(ValueError, match="已结束"):
        await db.withdraw_motion(m["id"])


async def test_motion_api_e2e(client) -> None:
    ids = await _members(2)
    created = await client.post(
        "/api/family/motions",
        json={"title": "换冰箱", "amount": 8000, "category": "家电", "proposer_id": ids[0]},
    )
    assert created.status_code == 200
    mid = created.json()["id"]

    v1 = await client.post(f"/api/family/motions/{mid}/votes", json={"member_id": ids[0], "vote": "yes"})
    assert v1.status_code == 200 and v1.json()["status"] == "voting"

    v2 = await client.post(f"/api/family/motions/{mid}/votes", json={"member_id": ids[1], "vote": "yes"})
    assert v2.json()["status"] == "approved"

    listed = await client.get("/api/family/motions?status=approved")
    assert any(x["id"] == mid for x in listed.json()["items"])


async def test_motion_api_404(client) -> None:
    r = await client.get("/api/family/motions/nope")
    assert r.status_code == 404
