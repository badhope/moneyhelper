"""单语句写事务通道：持写锁 + 显式事务 + 异常必回滚。

锁与连接的真源仍在 `_core.py`，这里**每次调用**动态取
`_core.get_write_lock()` / `_core._conn()`，测试替换 `_core` 时行为不变。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite

from . import _core


@asynccontextmanager
async def write_txn() -> AsyncIterator[aiosqlite.Connection]:
    """单语句写操作的安全通道：持写锁 + 显式事务 + 异常必回滚。

    为什么需要它：全库只有一条 aiosqlite 连接，隐含事务是所有协程共享的。
    一个协程写完未提交时，另一个协程的 commit() 会把它一起提交；一个协程
    失败未回滚时，下一个 commit() 会把半截数据固化。历史上这类问题只在
    「备份恢复 + 并发记账」时暴露，表现为"回滚了但数据已经没了"。

    用法（替代裸 `conn.execute(...); commit()`）：
        async with write_txn() as conn:
            await conn.execute(...)
            await conn.execute(...)
        # 正常退出 → COMMIT；异常退出 → ROLLBACK 后原样抛出

    注意：不接受嵌套——已在事务内再进入会死锁（同一把非重入锁）。
    确实需要嵌套时用 savepoint，或把逻辑合并到一个 write_txn 里。
    """
    lock = _core.get_write_lock()
    async with lock:
        conn = await _core._conn()
        # 连接是 autocommit（isolation_level=None），commit()/rollback() 都是空操作，
        # 必须显式开事务才能拿到「要么全成、要么全败」的语义。
        #
        # 嵌套处理：调用方可能已在外层事务里（测试或组合操作）。
        # 此时 BEGIN 会抛 "cannot start a transaction within a transaction"，
        # 改用 SAVEPOINT —— 这是 SQLite 标准的嵌套事务写法，回滚只影响内层。
        import uuid as _uuid

        sp = f"sp_{_uuid.uuid4().hex[:12]}"
        nested = bool(conn.in_transaction)
        if nested:
            await conn.execute(f"SAVEPOINT {sp}")
        else:
            await conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            if nested:
                await conn.execute(f"RELEASE {sp}")
            else:
                await conn.execute("COMMIT")
        except BaseException:
            try:
                if nested:
                    await conn.execute(f"ROLLBACK TO {sp}")
                    await conn.execute(f"RELEASE {sp}")
                else:
                    await conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001 — 回滚失败不能掩盖原始异常
                pass
            raise