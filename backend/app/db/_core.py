"""组合库 + 运行历史持久化（aiosqlite，单连接串行，不阻塞事件循环）。

所有函数都是异步的；连接在启动时创建（WAL 模式）。
首次运行自动建表。全新库为**空账本**（不种示例数据）：用户从记第一笔/添加持仓开始；
示例数据仅在设置页显式"导入示例数据"时种入（演示用）。

本文件为拆分后的基础设施层：连接/建表/迁移/种子/通用查询/成员会话存储。
域数据操作见同包 users/budgets/portfolio/ledger/debts/goals/memory/audit/undo/history/backup/family。
"""
from __future__ import annotations

import asyncio
import shutil
import weakref as _weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

from ..compat_env import getenv
from ..logging_utils import get_logger
from ..timeutil import now_iso as _now_iso  # noqa: F401 — db 门面重导出（app/db/__init__.py 使用）
from ._schema import SCHEMA

"""组合库 + 运行历史持久化（aiosqlite，单连接串行，不阻塞事件循环）。

所有函数都是异步的；连接在启动时创建（WAL 模式）。
首次运行自动建表。全新库为**空账本**（不种示例数据）：用户从记第一笔/添加持仓开始；
示例数据仅在设置页显式"导入示例数据"时种入（演示用）。
"""


def data_dir() -> Path:
    """运行期数据目录（数据库 / 备份 / checkpoint）。

    默认 `backend/data`（与 Dockerfile 的 VOLUME 一致），可用
    `MONEYHELPER_DATA_DIR` 覆盖。

    历史坑：默认值原先是 `backend/app/data`，而 Docker 卷挂的是
    `backend/data` —— 容器内账本写在卷外，重建即丢。统一到一处后，
    本地与容器看到的是同一个目录语义。

    覆盖值不允许指向程序自身目录（源码 / .git / 依赖清单）：否则一个环境变量
    就能让整个应用把数据写进源码树。最高权限需显式
    MONEYHELPER_ALLOW_SYSTEM_ACCESS=1。
    """
    raw = getenv("MONEYHELPER_DATA_DIR").strip()
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        from ..pathguard import assert_not_protected

        assert_not_protected(path, operation="把数据目录指向")
    else:
        path = Path(__file__).resolve().parent.parent.parent / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_db_path() -> Path:
    """解析数据库路径：MONEYHELPER_DB_PATH 优先，空串视为未设置。

    空串直接交给 Path("") 会退化成当前目录，导致建库失败或写错位置，
    因此这里显式过滤空值，并展开 ~ 与相对路径。
    """
    raw = getenv("MONEYHELPER_DB_PATH").strip()
    if not raw:
        return data_dir() / "wealth.db"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    from ..pathguard import assert_not_protected

    assert_not_protected(path, operation="把数据库放到")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# 旧版数据目录（backend/app/data）。2.4.2 起统一到 backend/data，
# 这里在首次启动时把老库搬过去，避免升级后"账本消失"。
_LEGACY_DB = Path(__file__).resolve().parent.parent / "data" / "wealth.db"


def _migrate_legacy_db(target: Path) -> None:
    """若新位置还没有库、但旧位置有，且没有显式指定 MONEYHELPER_DB_PATH，则搬移。

    WAL 模式下副本必须连带 -wal/-shm 一起搬，否则已提交但未 checkpoint
    的事务会丢。
    """
    if getenv("MONEYHELPER_DB_PATH").strip():
        return  # 用户显式指定了路径，不猜
    if target.exists() or not _LEGACY_DB.exists():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(_LEGACY_DB) + suffix)
            if src.exists():
                shutil.copy2(src, Path(str(target) + suffix))
        log = get_logger("db")
        log.info("db.migrated legacy=%s -> %s", _LEGACY_DB, target)
    except Exception as exc:  # noqa: BLE001 — 迁移失败不该阻断启动
        get_logger("db").warning("db.migrate_failed: %s", exc)


DB_PATH = _resolve_db_path()
_migrate_legacy_db(DB_PATH)

_db: aiosqlite.Connection | None = None
_inited = False

# --------------------------------------------------------------------------
# 家庭共享：当前活跃成员 session store（进程内，单实例部署够用）
# _ACTIVE_KEY 是进程级"当前 session" key；多 session 部署应换 JWT / cookie / Redis
# --------------------------------------------------------------------------

# 预定义配色池，轮流给新成员分配












_db_loop: object | None = None


async def init_db() -> None:
    """初始化数据库连接。

    连接与事件循环绑定：若发现连接是在**另一个 loop** 里创建的
    （CLI 连续调用、pytest 多次 asyncio.run），必须先丢弃旧连接重建，
    否则所有查询会挂在已关闭 loop 的 worker 线程上（实测无限等待）。
    """
    global _db, _inited, _db_loop
    loop = asyncio.get_running_loop()
    if _inited and _db is not None and _db_loop is loop:
        return
    if _db_loop is not None and _db_loop is not loop:
        # 旧连接属于别的 loop：不能 await 关闭（会挂），直接丢弃引用
        _db = None
        _inited = False
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None → sqlite3 的 autocommit 模式：每条语句自动提交，
    # 不会出现「A 协程的 commit 把 B 协程半截事务一起提交」的跨协程事务污染。
    #
    # 为什么必须显式设置：默认 isolation_level="" 会让第一条写语句开启隐式事务，
    # 而整库只有一条连接——所有协程共享同一个事务边界。历史上这导致
    # 「备份恢复 rollback 却已删数据」「批量导入半截提交」这类不可逆问题。
    #
    # 多语句事务（批量入账/导入/恢复）走 get_write_lock() + 显式 BEGIN IMMEDIATE，
    # 互斥仍在，但不再依赖隐式事务。
    _db = await aiosqlite.connect(str(DB_PATH), isolation_level=None)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.execute("PRAGMA synchronous=NORMAL")
    await _db.execute(
        "PRAGMA foreign_keys=ON"
    )  # SQLite 默认关外键；显式打开以启用 FK 约束/级联
    _db_loop = loop
    await _db.executescript(SCHEMA)
    await _migrate_add_columns()
    await _migrate_multitenant()
    # 企业组织影子模型：只回填事实，不改现有 user_id 鉴权/账本解析。
    from .org import backfill_org_shadow

    await backfill_org_shadow(_db)
    # 全新库（settings 表为空）不再自动种示例：空账本起步，用户自己记账/加持仓。
    # 老库即使用户清空了数据也绝不重置；示例数据只能显式导入（设置页/演示 API）。
    await _ensure_defaults()
    if await _count("positions") == 0:
        conn = await _conn()
        row = await (
            await conn.execute(
                "SELECT value FROM settings WHERE user_id=0 AND key='data_note'"
            )
        ).fetchone()
        if row and str(row["value"]).startswith("seed"):
            # 若旧库被清空但 data_note 仍是 seed，降级为 empty，避免误标示例
            await conn.execute(
                "INSERT INTO settings(user_id,key,value) VALUES(0,'data_note','empty') "
                "ON CONFLICT(user_id,key) DO UPDATE SET value='empty'"
            )
            await conn.commit()
    await _migrate_sessions_from_runs()
    await _db.commit()
    _inited = True


async def close_db(timeout: float = 5.0) -> None:
    """关闭连接并清空状态。

    加超时兜底：aiosqlite 的关闭要回到连接所属的**那个事件循环**执行；
    如果调用方在另一个 loop 里 close（CLI 连续调用、测试里 asyncio.run 多次），
    会永久等待。这种情况下宁可放弃优雅关闭，也不能卡死进程。
    """
    global _db, _inited, _read_conns, _db_loop, _pool_loop
    conn, _db = _db, None
    _inited = False
    _db_loop = None
    if conn is not None:
        # 先回滚未完成事务，避免 WAL 写锁被悬挂连接长期占住，
        # 让后续（可能是另一个 loop 的）连接永远等锁。
        try:
            await asyncio.wait_for(conn.rollback(), timeout=timeout)
        except Exception:  # noqa: BLE001
            pass
        try:
            await asyncio.wait_for(conn.close(), timeout=timeout)
        except Exception:  # noqa: BLE001
            pass
    from . import readpool

    read_conns = list(readpool._read_conns)
    readpool._read_conns.clear()
    for c in read_conns:
        try:
            await asyncio.wait_for(c.close(), timeout=timeout)
        except (asyncio.TimeoutError, RuntimeError, Exception):  # noqa: BLE001
            pass
    readpool.reset_pool_state()
    _write_locks.clear()


async def _conn() -> aiosqlite.Connection:
    if _db is None:
        await init_db()
    assert _db is not None
    return _db


# 写事务串行锁（按事件循环各自持有，理由同 _pool_locks）。
# 整库只有一条写连接：多语句事务（批量入账 / 导出导入）必须互相排他，
# 否则两个协程的 BEGIN/SAVEPOINT 会互相干扰——CI 实测表现为
# "cannot start a transaction within a transaction" 与
# "no such savepoint: add_tx_batch"（另一个协程已经 RELEASE 了同名 savepoint）。
#
# 用 WeakKeyDictionary 以**循环对象本身**为键，而不是 id(loop)：
#   - id() 会在对象被回收后被复用。旧循环销毁、新循环拿到同一个 id 时，
#     会命中一把"属于死循环"的 Lock —— 它可能处于已 acquire 状态，
#     于是 `async with lock` 立即返回，并发保护静默失效
#     （表现为 test_studio 的 12 并发只存下几条，且单独跑必过）。
#   - WeakKeyDictionary 在循环被 GC 时自动移除条目，不会无限增长。
_write_locks: _weakref.WeakKeyDictionary[Any, asyncio.Lock] = _weakref.WeakKeyDictionary()


def get_write_lock() -> asyncio.Lock:
    """取当前事件循环的写事务锁。所有多语句事务都必须持它。"""
    loop = asyncio.get_running_loop()
    lk = _write_locks.get(loop)
    if lk is None:
        lk = asyncio.Lock()
        _write_locks[loop] = lk
    return lk


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
    lock = get_write_lock()
    async with lock:
        conn = await _conn()
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




















# --------------------------------------------------------------------------
# 读
# --------------------------------------------------------------------------



# --------------------------------------------------------------------------
# 待确认动作（写操作 HITL：确认前不落库，token 一次性消费）
# --------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 门面：schema 常量 / 通用工具 / 查询 / 成员 / 种子
# 这些名字原先都定义在本文件，拆分后仍从这里导出，调用方与测试无需改动。
# ---------------------------------------------------------------------------
from ._schema import (  # noqa: F401,E402
    DEFAULT_SETTINGS,
    SEED_DEBTS,
    SEED_POSITIONS,
    SEED_SETTINGS,
    SEED_SUBSCRIPTIONS,
    SEED_TRANSACTIONS,
)
from .members import (  # noqa: F401,E402
    _ACTIVE_KEY,
    _AVATAR_COLORS,
    _active_member_id,
    _fetch_member,
    get_active_member,
    set_active_member,
    uuid_hex,
)

# 迁移族已拆到 migrate.py；init_db 运行时按名字解析，import 放末尾即可。
from .migrate import (  # noqa: F401,E402
    _backup_db_consistent,
    _ensure_unique_by_tenant,
    _migrate_add_columns,
    _migrate_multitenant,
    _needs_multitenant,
    _pk_cols,
    _rebuild_composite,
    _rebuild_unique_as_composite,
    _rebuild_with_user_id,
    _recover_stale_temp_tables,
)
from .queries import (  # noqa: F401,E402
    get_settings,
    list_debts,
    list_positions,
    list_subscriptions,
    list_transactions,
    list_transactions_by_month,
    set_setting,
)

# 预算口径排除项：投资/还款属于储蓄或资金转移，不是消费支出，不计入预算使用
NON_CONSUMPTION_CATEGORIES: tuple[str, ...] = ("投资", "还款")

from .readpool import (  # noqa: F401,E402
    _get_pool_lock,
    _read_conn,
    _read_conns,
    execute,
    fetch_all,
    fetch_one,
    set_read_pool,
)
from .seed import (  # noqa: F401,E402
    _COUNT_ALLOWED_TABLES,
    PENDING_TTL_MINUTES,
    _clean_due_day,
    _count,
    _ensure_defaults,
    _mark_user_data,
    _migrate_sessions_from_runs,
    _seed_all,
    _seed_date,
    reset_to_seed,
)
from .util import (  # noqa: F401,E402
    _LIST_LIMIT_MAX,
    _clamp_limit,
    row_dict,
)
