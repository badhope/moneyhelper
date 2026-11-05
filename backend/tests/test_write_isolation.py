"""写事务边界：并发写入不能互相污染（回归测试）。

历史缺陷（真实现象）：
  整库只有一条 aiosqlite 连接，默认 isolation_level="" 会让第一条写语句
  开启隐式事务。A 协程的 commit() 会把 B 协程未完成的事务一起提交；
  A 协程的 rollback() 会把 B 协程已写入的数据一起回滚。

  最坏的组合发生在「备份恢复 + 并发记账」：import_backup 持锁 DELETE 后失败
  rollback，而普通记账在中间 commit 了 —— 结果是原账本被清空、对方的流水留下，
  接口还返回「数据已回滚」。

修复：连接改为 isolation_level=None（autocommit），单语句各自提交，
多语句事务显式 BEGIN IMMEDIATE + 写锁。

本文件断言的是「并发下数据不丢、不串」，而不是内部实现。
"""

import asyncio

import pytest

from app import db


@pytest.mark.asyncio
async def test_concurrent_transactions_all_persist(temp_db):
    """12 个并发记账：一条都不能丢。"""
    async def add(i: int) -> None:
        await db.add_transaction("2026-11-04", f"并发{i}", "餐饮", -float(i + 1))

    await asyncio.gather(*[add(i) for i in range(12)])
    rows = await db.list_transactions()
    items = {r["item"] for r in rows}
    assert {f"并发{i}" for i in range(12)} <= items


@pytest.mark.asyncio
async def test_batch_insert_is_atomic_on_failure(temp_db):
    """批量入账中途失败必须整体回滚，不能留下半截。"""
    await db.add_transaction("2026-11-01", "基线", "其他", -1.0)
    before = len(await db.list_transactions())

    bad_batch = [
        {"date": "2026-11-02", "item": "正常A", "category": "餐饮", "amount": -10.0},
        {"date": "非法日期", "item": "坏行", "category": "餐饮", "amount": -20.0},
    ]
    with pytest.raises(Exception):
        await db.add_transactions_batch(bad_batch)

    after = len(await db.list_transactions())
    assert after == before, "失败批次不应留下任何一条"


@pytest.mark.asyncio
async def test_concurrent_batches_do_not_interleave(temp_db):
    """两个批次并发执行：各自要么全成、要么全败，不交叉污染。"""
    b1 = [
        {"date": "2026-11-03", "item": f"B1-{i}", "category": "餐饮", "amount": -1.0}
        for i in range(5)
    ]
    b2 = [
        {"date": "2026-11-03", "item": f"B2-{i}", "category": "交通", "amount": -1.0}
        for i in range(5)
    ]
    await asyncio.gather(db.add_transactions_batch(b1), db.add_transactions_batch(b2))
    items = {r["item"] for r in await db.list_transactions()}
    assert {f"B1-{i}" for i in range(5)} <= items
    assert {f"B2-{i}" for i in range(5)} <= items


@pytest.mark.asyncio
async def test_write_txn_rolls_back_on_error(temp_db):
    """write_txn 通道在异常时必须回滚，且不留下半个事务。"""
    from app.db._core import write_txn

    await db.add_transaction("2026-11-01", "原始", "其他", -1.0)
    before = len(await db.list_transactions())

    with pytest.raises(RuntimeError):
        async with write_txn() as conn:
            await conn.execute(
                "INSERT INTO transactions(user_id,date,item,category,amount)"
                " VALUES(0,'2026-11-02','半截','其他',-9)"
            )
            raise RuntimeError("模拟中途失败")

    after = len(await db.list_transactions())
    assert after == before, "失败事务的写入必须被回滚"


@pytest.mark.asyncio
async def test_write_txn_commits_on_success(temp_db):
    from app.db._core import write_txn

    async with write_txn() as conn:
        await conn.execute(
            "INSERT INTO transactions(user_id,date,item,category,amount)"
            " VALUES(0,'2026-11-02','成功','其他',-9)"
        )
    items = {r["item"] for r in await db.list_transactions()}
    assert "成功" in items


@pytest.mark.asyncio
async def test_invalid_position_update_leaves_no_ghost_snapshot(temp_db):
    """校验失败不能留下撤销快照，且连接必须回到空闲状态。

    回归背景：update_position 原实现先 _record_snapshot（INSERT，开启事务），
    再 float("abc") 抛错——快照留在未提交事务里，下一条无关写操作的 commit()
    会把它一起提交，产生「幽灵撤销点」。
    """
    await db.add_position({
        "symbol": "600519", "name": "贵州茅台", "kind": "股票",
        "industry": "白酒", "shares": 100, "cost": 1600, "last": 1650,
    })
    from app.db._core import _conn

    conn = await _conn()
    before_snapshots = await db.fetch_all(
        "SELECT * FROM undo_snapshots WHERE entity_id=?", ("600519",)
    ) if await _table_exists("undo_snapshots") else []

    with pytest.raises((ValueError, TypeError)):
        await db.update_position({"shares": "abc"}, "600519")

    # 连接不应停留在事务中
    assert conn.in_transaction is False, "校验失败后连接仍处于事务中"

    after_snapshots = await db.fetch_all(
        "SELECT * FROM undo_snapshots WHERE entity_id=?", ("600519",)
    ) if await _table_exists("undo_snapshots") else []
    assert len(after_snapshots) == len(before_snapshots), "校验失败却写入了撤销快照"


async def _table_exists(name: str) -> bool:
    rows = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return bool(rows)


@pytest.mark.asyncio
async def test_write_lock_not_shared_across_event_loops(temp_db):
    """写锁必须按「事件循环对象」隔离，不能按 id(loop)。

    回归背景：_write_locks 原用 id(loop) 作键且从不清理。CPython 会复用对象 id：
    旧循环销毁后新循环可能拿到同一个 id，于是命中一把「属于死循环」的 Lock——
    它可能处于已 acquire 状态，`async with lock` 立即返回，并发保护静默失效。
    表现为 test_studio 的 12 并发只存下几条，且单独跑必过、全量跑偶发挂。
    """
    from app.db import _core

    # 记录当前锁对象的身份
    lk1 = _core.get_write_lock()
    # 键必须是 loop 对象（弱引用字典），不是 int id
    assert not isinstance(next(iter(_core._write_locks.keys())), int), (
        "_write_locks 仍以 id(loop) 为键，存在 id 复用风险"
    )
    assert lk1 is _core.get_write_lock(), "同一循环内应返回同一把锁"
