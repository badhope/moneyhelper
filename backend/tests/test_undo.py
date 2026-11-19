"""撤回（undo）能力集成测试。

覆盖 4 个用例：
1. 新增流水 → 撤回 → 余额复原
2. 删持仓 → 撤回 → 持仓恢复
3. 合并持仓（同名两条） → 各自撤回 → 复原两条
4. 撤回一条已不存在（未留快照）的实体 → 404
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
from app import db, main
from app import quotes as quotes_mod


@pytest.fixture(autouse=True)
async def _auto_temp_db(temp_db):
    """保持原文件的 autouse 语义：本文件每个用例都跑在临时库上。

    `_temp_db` 转发版已收敛到 conftest；此处只保留「自动生效」这一行为差异。
    """
    yield


@pytest.fixture
async def client(_temp_db, monkeypatch):
    async def _snap(positions):
        return {p["symbol"]: float(p["last"]) for p in positions}

    monkeypatch.setattr(quotes_mod, "live_quotes", _snap)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8787"
    ) as ac:
        yield ac


async def _balance() -> float:
    """当前流水净余额（收入 - 支出）。"""
    rows = await db.fetch_all("SELECT amount FROM transactions")
    return round(sum(r["amount"] for r in rows), 2)


async def test_undo_new_transaction_restores_balance(client) -> None:
    """新增一笔支出流水后撤回，净余额应完全复原。"""
    before = await _balance()
    dc = datetime.now().astimezone()
    date = dc.replace(day=min(dc.day, 28)).strftime("%Y-%m-%d")

    r = await client.post(
        "/api/transactions",
        json={
            "date": date,
            "item": "test undo tx",
            "category": "其他",
            "amount": -123.45,
        },
    )
    assert r.status_code == 200, r.text
    after_add = round(before - 123.45, 2)
    assert await _balance() == after_add

    undo_r = await client.post(f"/api/transactions/{r.json()['id']}/undo")
    assert undo_r.status_code == 200, undo_r.text
    # 撤回后余额必须精确复原
    assert await _balance() == before
    # 业务流水也应消失
    rows = await db.fetch_all("SELECT id FROM transactions WHERE item = 'test undo tx'")
    assert rows == []


async def test_undo_delete_position_restores_position(client) -> None:
    """删一条持仓再撤回，应完整恢复。"""
    positions_before = await db.list_positions()
    target = positions_before[0]
    sym = target["symbol"]
    old_len = len(positions_before)

    r = await client.delete(f"/api/positions/{sym}")
    assert r.status_code == 200
    assert len(await db.list_positions()) == old_len - 1

    undo_r = await client.post(f"/api/positions/{sym}/undo")
    assert undo_r.status_code == 200, undo_r.text
    restored = await db.list_positions()
    assert len(restored) == old_len
    row = next(p for p in restored if p["symbol"] == sym)
    # 关键字段与删除前一致
    for k in ("name", "kind", "shares", "cost", "last"):
        assert row[k] == target[k], f"{k}: {row[k]!r} != {target[k]!r}"


async def test_undo_merge_positions_restores_two_rows(client) -> None:
    """构造两条同名持仓，合并后逐条撤回，应恢复两条独立记录。"""
    await db.add_position(
        {
            "symbol": "AAA",
            "name": "同名测试股",
            "kind": "股票",
            "industry": "测试",
            "shares": 100,
            "cost": 10.0,
            "last": 12.0,
            "buy_date": None,
            "fee": 0,
        }
    )
    await db.add_position(
        {
            "symbol": "BBB",
            "name": "同名测试股",
            "kind": "股票",
            "industry": "测试",
            "shares": 200,
            "cost": 20.0,
            "last": 25.0,
            "buy_date": None,
            "fee": 0,
        }
    )
    rows_before = [p for p in await db.list_positions() if p["name"] == "同名测试股"]
    assert len(rows_before) == 2
    keep_sym = "AAA"
    drop_sym = "BBB"

    mr = await client.post("/api/positions/merge", json={"name": "同名测试股"})
    assert mr.status_code == 200, mr.text
    assert mr.json().get("merged", 0) == 1
    rows_after = [p for p in await db.list_positions() if p["name"] == "同名测试股"]
    assert len(rows_after) == 1

    # 先撤回被 merge 掉的 BBB → 恢复 BBB
    undo_drop = await client.post(f"/api/positions/{drop_sym}/undo")
    assert undo_drop.status_code == 200, undo_drop.text
    snaps = await db.list_undo_records()
    rows_mid = [p for p in await db.list_positions() if p["name"] == "同名测试股"]
    assert len(rows_mid) == 2
    assert _has_sym(rows_mid, drop_sym)

    # 再撤回 keep（AAA），它的快照是合并前的旧持仓
    _ = snaps
    undo_keep = await client.post(f"/api/positions/{keep_sym}/undo")
    assert undo_keep.status_code == 200, undo_keep.text
    rows_final = [p for p in await db.list_positions() if p["name"] == "同名测试股"]
    # AAA 恢复合并前状态（单条 100 股 @10），BBB 刚才已单独撤回
    aaa = next(p for p in rows_final if p["symbol"] == "AAA")
    bbb = next((p for p in rows_final if p["symbol"] == "BBB"), None)
    assert aaa["shares"] == 100
    assert aaa["cost"] == 10.0
    assert bbb is not None
    assert bbb["shares"] == 200
    assert bbb["cost"] == 20.0


def _has_sym(rows, sym):
    return any(p["symbol"] == sym for p in rows)


async def test_undo_missing_snapshot_returns_404(client) -> None:
    """撤回一条从未写入过的实体 → 404。"""
    # 找一条不存在的流水 id
    max_id = (await db.fetch_all("SELECT COALESCE(MAX(id), 0) AS m FROM transactions"))[
        0
    ]["m"]
    missing = int(max_id) + 9999
    r = await client.post(f"/api/transactions/{missing}/undo")
    assert r.status_code == 404
