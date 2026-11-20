"""LangGraph 磁盘 checkpoint：按事件循环惰性构建 AsyncSqliteSaver 与执行图。

路径、缓存与图定义一律经门面动态取（`_facade._CHECKPOINT_DB` / `_facade._build_graph`）：
测试夹具会把 checkpoint 库指到临时目录，import 时快照会让它写回真实库。
"""

from __future__ import annotations

import asyncio
import weakref
from typing import Any

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from . import agent_graph as _facade

_facade._savers: weakref.WeakKeyDictionary[Any, AsyncSqliteSaver] = weakref.WeakKeyDictionary()
_facade._exec_graphs: weakref.WeakKeyDictionary[Any, Any] = weakref.WeakKeyDictionary()


async def _acquire_saver() -> AsyncSqliteSaver:
    """按当前 event loop 惰性构建磁盘 AsyncSqliteSaver（WAL + setup）。"""
    loop = asyncio.get_running_loop()
    key = loop
    if key not in _facade._savers:
        _facade._CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(_facade._CHECKPOINT_DB))
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        _facade._savers[key] = saver
    return _facade._savers[key]


async def _acquire_exec_graph() -> Any:
    """按当前 event loop 惰性编译「带磁盘 checkpoint 的执行图」（供 run_graph / resume 使用）。"""
    loop = asyncio.get_running_loop()
    key = loop
    if key not in _facade._exec_graphs:
        saver = await _acquire_saver()
        _facade._exec_graphs[key] = _facade._build_graph().compile(checkpointer=saver)
    return _facade._exec_graphs[key]


async def close_checkpoints() -> None:
    """关闭并清空当前进程持有的磁盘 checkpoint 连接（供测试 teardown / 优雅停机复用）。

    生产端单 worker 单 loop 常驻连接无需调用；测试端每个 loop 各开一个连接，
    测试结束前由 conftest 调用本函数释放 aiosqlite worker 线程，避免 loop 关闭后挂住进程。
    """
    _facade._exec_graphs.clear()
    for saver in list(_facade._savers.values()):
        try:
            await saver.conn.close()
        except Exception:
            pass
    _facade._savers.clear()
    _facade._close_pending_conn()
