"""读连接池与只读/直写语句封装。

从 `_core.py` 拆出（原 340-455 行）：WAL 下多读者并发、写仍走单连接串行。连接与
写锁的真源仍留在 `_core.py`，这里每次调用时动态取 `_core._conn()`——测试 monkeypatch
`_core._conn` / `_core._db` 依旧生效，不会因拆分变成两套连接。
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiosqlite

from ..logging_utils import get_logger

log = get_logger(__name__)


def _core_mod():
    from . import _core

    return _core


async def _conn() -> aiosqlite.Connection:
    return await _core_mod()._conn()


def reset_pool_state() -> None:
    """清空池、锁与循环标记（关库时调用）：连接由调用方先关，这里只重置登记表。"""
    global _pool_loop
    _read_conns.clear()
    _pool_locks.clear()
    _pool_loop = None


# 读连接池（M1.3）：WAL 下多读者并发，写仍走 _conn 单连接串行——
# 部门模式（M3）多 agent 并行取数的地基。池在首次读取时惰性建连。
_READ_POOL_SIZE = 3
_read_conns: list[aiosqlite.Connection] = []
_pool_loop: object | None = None
# 读池开关：CLI 这类"短进程、每命令一个事件循环"的场景关掉读池，
# 避免连接跨 loop 复用（会永久等待）。HTTP 服务保持开启。
_read_pool_enabled = True


def set_read_pool(enabled: bool) -> None:
    """启用/禁用读连接池（CLI 在启动时禁用）。"""
    global _read_pool_enabled
    _read_pool_enabled = enabled
_rr = 0
# 锁必须按事件循环各自持有：模块级 asyncio.Lock 会绑定导入时的循环，
# 换循环（TestClient/多 worker）即 "bound to a different event loop"（CI 实测教训）
_pool_locks: dict[object, asyncio.Lock] = {}


def _get_pool_lock() -> asyncio.Lock:
    """按**事件循环对象**（而非 id）维护锁。

    用 id(loop) 做 key 有复用风险：旧 loop 被回收后新 loop 可能拿到同一 id，
    于是复用了绑定在已关闭 loop 上的 Lock（表现为永久等待）。专家项。
    """
    loop = asyncio.get_running_loop()
    for (lp, lk) in list(_pool_locks.items()):
        if lp is loop:
            return lk
    lk = asyncio.Lock()
    _pool_locks[loop] = lk
    return lk


async def _read_conn() -> aiosqlite.Connection:
    """取一条读连接：池未满则建连（持锁防并发超建），满了轮询复用。仅供只读查询。

    与 init_db 同理：读连接也绑事件循环。换 loop 时必须丢弃旧池重建，
    否则查询会挂在已关闭 loop 的 worker 线程上（CLI 连续调用实测）。
    """
    global _rr, _pool_loop
    loop = asyncio.get_running_loop()
    async with _get_pool_lock():
        if _pool_loop is not None and _pool_loop is not loop:
            _read_conns.clear()
            _pool_loop = None
        core = _core_mod()
        if core._db is None:
            await core.init_db()
        _pool_loop = loop
        if len(_read_conns) < _READ_POOL_SIZE:
            # 用 PRAGMA query_only 实现只读，而不是 URI 的 mode=ro：
            # mode=ro 在 WAL 模式下需要读 -wal 文件，若写连接尚未 checkpoint，
            # 只读连接会一直等待（CLI 连续调用实测卡死）。
            # query_only 复用普通连接语义，只禁止写入，不改变 WAL 打开方式。
            c = await aiosqlite.connect(str(_core_mod().DB_PATH))
            await c.execute("PRAGMA query_only=ON")
            c.row_factory = aiosqlite.Row
            await c.execute("PRAGMA busy_timeout=5000")
            _read_conns.append(c)
            return c
        c = _read_conns[_rr % _READ_POOL_SIZE]
        _rr += 1
        return c


async def fetch_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    if not _read_pool_enabled:
        # 单连接模式（CLI/测试）：直接用写连接读，避免跨 loop 的连接池
        c = await _conn()
        cur = await c.execute(sql, params)
        try:
            return [dict(r) for r in await cur.fetchall()]
        finally:
            await cur.close()
    conn = await _read_conn()
    cur = await conn.execute(sql, params)
    try:
        rows = await cur.fetchall()
    finally:
        await cur.close()  # 显式终结语句：游标悬挂会长期持有读锁（M1.3 教训）
    return [dict(r) for r in rows]


async def fetch_one(sql: str, params: tuple = ()) -> aiosqlite.Row | None:
    """执行查询并返回单行结果（无匹配返回 None）。"""
    conn = await _read_conn()
    cur = await conn.execute(sql, params)
    try:
        row = await cur.fetchone()
        await cur.fetchall()  # 耗尽游标终结语句，释放读锁
        return row
    finally:
        await cur.close()


async def execute(sql: str, params: tuple = ()) -> None:
    """执行写语句（INSERT/UPDATE/DELETE）并提交。"""
    conn = await _conn()
    await conn.execute(sql, params)
    await conn.commit()













