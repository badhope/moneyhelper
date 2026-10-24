"""组合库 + 运行历史持久化（aiosqlite，单连接串行，不阻塞事件循环）。

所有函数都是异步的；连接在启动时创建（WAL 模式）。
首次运行自动建表。全新库为**空账本**（不种示例数据）：用户从记第一笔/添加持仓开始；
示例数据仅在设置页显式"导入示例数据"时种入（演示用）。

本文件为拆分后的基础设施层：连接/建表/迁移/种子/通用查询/成员会话存储。
域数据操作见同包 users/budgets/portfolio/ledger/debts/goals/memory/audit/undo/history/backup/family。
"""
from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from ..logging_utils import get_logger
from ._schema import (
    DEFAULT_SETTINGS,
    SCHEMA,
    SEED_DEBTS,
    SEED_POSITIONS,
    SEED_SETTINGS,
    SEED_SUBSCRIPTIONS,
    SEED_TRANSACTIONS,
)

"""组合库 + 运行历史持久化（aiosqlite，单连接串行，不阻塞事件循环）。

所有函数都是异步的；连接在启动时创建（WAL 模式）。
首次运行自动建表。全新库为**空账本**（不种示例数据）：用户从记第一笔/添加持仓开始；
示例数据仅在设置页显式"导入示例数据"时种入（演示用）。
"""


def data_dir() -> Path:
    """运行期数据目录（数据库 / 备份 / checkpoint）。

    默认 `backend/data`（与 Dockerfile 的 VOLUME 一致），可用
    `XIAOMAN_DATA_DIR` 覆盖。

    历史坑：默认值原先是 `backend/app/data`，而 Docker 卷挂的是
    `backend/data` —— 容器内账本写在卷外，重建即丢。统一到一处后，
    本地与容器看到的是同一个目录语义。
    """
    raw = (os.getenv("XIAOMAN_DATA_DIR") or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
    else:
        path = Path(__file__).resolve().parent.parent.parent / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_db_path() -> Path:
    """解析数据库路径：XIAOMAN_DB_PATH 优先，空串视为未设置。

    空串直接交给 Path("") 会退化成当前目录，导致建库失败或写错位置，
    因此这里显式过滤空值，并展开 ~ 与相对路径。
    """
    raw = (os.getenv("XIAOMAN_DB_PATH") or "").strip()
    if not raw:
        return data_dir() / "wealth.db"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# 旧版数据目录（backend/app/data）。2.4.2 起统一到 backend/data，
# 这里在首次启动时把老库搬过去，避免升级后"账本消失"。
_LEGACY_DB = Path(__file__).resolve().parent.parent / "data" / "wealth.db"


def _migrate_legacy_db(target: Path) -> None:
    """若新位置还没有库、但旧位置有，且没有显式指定 XIAOMAN_DB_PATH，则搬移。

    WAL 模式下副本必须连带 -wal/-shm 一起搬，否则已提交但未 checkpoint
    的事务会丢。
    """
    if os.getenv("XIAOMAN_DB_PATH", "").strip():
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
_ACTIVE_KEY = "__default__"
_active_member_id: dict[str, int | None] = {}  # session_key → member_id

# 预定义配色池，轮流给新成员分配
_AVATAR_COLORS = [
    "#b8891f",
    "#2e7d32",
    "#1565c0",
    "#6a1b9a",
    "#c62828",
    "#00838f",
    "#ef6c00",
    "#37474f",
    "#ad1457",
    "#3949ab",
]


def set_active_member(member_id: int | None, session_key: str = _ACTIVE_KEY) -> None:
    """切换当前活跃成员"""
    _active_member_id[session_key] = member_id


def get_active_member(session_key: str = _ACTIVE_KEY) -> int | None:
    """获取当前活跃成员 id"""
    return _active_member_id.get(session_key)


async def _fetch_member(member_id: int) -> dict[str, Any] | None:
    """根据 id 取成员信息（限当前租户，防跨租户按 id 探测）"""
    from .tenant import current_user_id

    conn = await _conn()
    cur = await conn.execute(
        "SELECT id, username, display_name, role, avatar_color, created_at "
        "FROM members WHERE user_id=? AND id=?",
        (current_user_id(), member_id),
    )
    row = await cur.fetchone()
    return dict(row) if row else None




def _seed_date(day: int) -> str:
    """种子流水的日期：本月已过去的日期（不晚于今天）。"""
    now = datetime.now()
    return now.replace(day=min(day, now.day)).strftime("%Y-%m-%d")


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
    _db = await aiosqlite.connect(str(DB_PATH))
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


async def _migrate_add_columns() -> None:
    """老库增量迁移：为已有表补新列（CREATE TABLE IF NOT EXISTS 不会改老表）。"""
    assert _db is not None
    cols = {
        "subscriptions": {"due_day": "TEXT NOT NULL DEFAULT ''"},
        "debts": {"due_day": "TEXT NOT NULL DEFAULT ''"},
        # 问答来源可溯源：route/llm 落库后历史回答也能显示真实来源（此前只能显示等级）
        "runs": {
            "route": "TEXT NOT NULL DEFAULT ''",
            "llm": "TEXT NOT NULL DEFAULT ''",
            "route_reason": "TEXT NOT NULL DEFAULT ''",
            "tools": "TEXT NOT NULL DEFAULT ''",
            "actions": "TEXT NOT NULL DEFAULT '[]'",
        },
        # 主动遗忘：记录每次被注入/使用的时间，便于按未使用时长清理
        "user_memory": {"last_used": "TEXT NOT NULL DEFAULT ''"},
        # 知识库：附件可标记为「入库」，问答时按 BM25 检索其片段
        "attachments": {"indexed": "INTEGER NOT NULL DEFAULT 0"},
    }
    # transactions 表：新增 owner_id（交易归属成员）与 is_shared（是否共享）
    tx_cols = await _db.execute("PRAGMA table_info(transactions)")
    tx_existing = {row["name"] for row in await tx_cols.fetchall()}
    if "owner_id" not in tx_existing:
        await _db.execute(
            "ALTER TABLE transactions ADD COLUMN owner_id INTEGER REFERENCES members(id)"
        )
    if "is_shared" not in tx_existing:
        await _db.execute(
            "ALTER TABLE transactions ADD COLUMN is_shared INTEGER NOT NULL DEFAULT 1"
        )

    for table, adds in cols.items():
        cur = await _db.execute(f"PRAGMA table_info({table})")
        existing = {row["name"] for row in await cur.fetchall()}
        for col, decl in adds.items():
            if col not in existing:
                await _db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


# 需要按租户隔离的表。四张"业务字段作主键"的表要重建（复合主键），
# 其余表只需加 user_id 列。
_TENANT_TABLES = (
    "transactions",
    "runs",
    "sessions",
    "budgets",
    "user_memory",
    "attachments",
    "dept_reports",
    "pending_actions",
    "undo_records",
    "member_loans",
    "members",
    "provenance_log",
    "audit_logs",
    "allocation_targets",
    "dca_plans",
)

# 复合主键重建表：旧主键 + user_id = 新主键
_COMPOSITE_TABLES = {
    "positions": ("symbol", "TEXT PRIMARY KEY"),
    "subscriptions": ("name", "TEXT PRIMARY KEY"),
    "debts": ("name", "TEXT PRIMARY KEY"),
    "watchlist": ("symbol", "TEXT PRIMARY KEY"),
    # goals 同样用业务名作主键：两个人都有「买房」目标时必须能共存
    "goals": ("name", "TEXT PRIMARY KEY"),
    # 会话摘要按 thread_id 主键；不同用户的同名 thread 必须各存一份
    "conversation_summary": ("thread_id", "TEXT PRIMARY KEY"),
}

# settings/budgets 的主键不是单列（复合），单独处理
_COMPOSITE_MULTI = {
    "settings": (("user_id", "key"), "INSERT INTO {tmp} (user_id,key,value) SELECT 0,key,value FROM settings"),
    "budgets": (("user_id", "month", "category"), "INSERT INTO {tmp} (user_id,month,category,amount) SELECT 0,month,category,amount FROM budgets"),
}

# 非主键但带 UNIQUE 约束的列：多租户下唯一性要按 (user_id, col) 计算
_UNIQUE_COLS = {"sessions": "thread_id"}


async def _pk_cols(table: str) -> list[str]:
    """返回表的主键列（按 pk 序号排序）；表不存在返回空列表。"""
    assert _db is not None
    cur = await _db.execute(f"PRAGMA table_info({table})")
    info = await cur.fetchall()
    return [r["name"] for r in sorted((x for x in info if x["pk"]), key=lambda x: x["pk"])]


async def _needs_multitenant() -> bool:
    """是否需要多租户迁移。

    判据是**主键形状**而不是"列是否存在"：
    历史上出现过先加 user_id 列、后重建表，中途失败导致
    `positions` 有 user_id 但主键仍是单列 symbol 的"半迁移"库；
    只查列会让这种库永久跳过修复，多租户静默失效（专家评审 P0-3）。
    """
    for table, (key_col, _decl) in _COMPOSITE_TABLES.items():
        pk = await _pk_cols(table)
        if not pk:
            continue
        if pk != ["user_id", key_col]:
            return True
    for table, (cols, _sql) in _COMPOSITE_MULTI.items():
        pk = await _pk_cols(table)
        if not pk:
            continue
        if pk != list(cols):
            return True
    # 普通表：缺 user_id 列也需要迁移
    for table in _TENANT_TABLES:
        cur = await _db.execute(f"PRAGMA table_info({table})")
        info = await cur.fetchall()
        if not info:
            continue
        if "user_id" not in {r["name"] for r in info}:
            return True
    return False


async def _backup_db_consistent(target: Path) -> None:
    """用 SQLite 在线备份 API 生成一致性快照。

    为什么不能 shutil.copy2：WAL 模式下已提交数据可能还在 -wal 文件里，
    只复制主文件会得到一个"空库"（专家评审 P0-1 实测：备份里 0 张表）。
    Connection.backup() 由 SQLite 负责 checkpoint 与一致性，是最可靠的做法。
    """
    import sqlite3

    src = sqlite3.connect(str(DB_PATH))
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


async def _recover_stale_temp_tables() -> None:
    """清理上次迁移中断留下的临时表。

    重建流程若在 DROP 与 RENAME 之间崩溃，会遗留 `<table>__mt_migrate`，
    下次启动 CREATE 直接报 "already exists"，服务起不来（专家评审 P0-2）。
    能恢复就恢复，否则删掉重来——原表若还在，数据未丢。
    """
    assert _db is not None
    cur = await _db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%__mt_migrate' OR name LIKE '%__uq_migrate')"
    )
    stale = [r["name"] for r in await cur.fetchall()]
    for name in stale:
        base = name.split("__")[0]
        base_pk = await _pk_cols(base)
        if base_pk:
            # 原表还在（崩溃在 DROP 之前）：临时表是多余的
            await _db.execute(f"DROP TABLE IF EXISTS {name}")
            get_logger("db").info("db.migrate_cleanup_temp=%s", name)
        else:
            # 原表已 DROP、只剩临时表：把它改回正式名，保住数据
            await _db.execute(f"ALTER TABLE {name} RENAME TO {base}")
            get_logger("db").info("db.migrate_recover_temp=%s -> %s", name, base)


async def _migrate_multitenant() -> None:
    """多租户迁移：加 user_id 维度，并把历史数据归到默认租户 0。

    安全性（专家评审 P0-1/P0-2/P0-3 修复）：
    1. 动结构前用 SQLite backup API 生成**一致性快照**（WAL 下 copy2 会得到空库）；
       备份失败直接中止迁移——备份是 DROP 的唯一逃生舱。
    2. 整个迁移包在 BEGIN IMMEDIATE ... COMMIT 里，中途崩溃自动回滚；
       启动时还会清理/恢复上次遗留的临时表。
    3. 是否需要迁移按**主键形状**判断（见 _needs_multitenant），
       半迁移库能被识别并修复。
    """
    assert _db is not None

    await _recover_stale_temp_tables()
    if not await _needs_multitenant():
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = Path(str(DB_PATH) + f".pre-mt-{stamp}")
    try:
        await _backup_db_consistent(backup_path)
    except Exception as exc:  # noqa: BLE001
        # 备份失败不能继续：重建表是不可逆的 DROP
        get_logger("db").error("db.migrate_backup_failed, abort: %s", exc)
        raise RuntimeError(f"多租户迁移前备份失败，已中止：{exc}") from exc
    get_logger("db").info("db.migrate_backup=%s", backup_path)

    await _db.execute("BEGIN IMMEDIATE")
    try:
        # 1) 普通表：加 user_id 列。
        # 关键：复合主键表（positions 等）也会遍历到这里，但它们的 user_id
        # 由重建逻辑负责；若这里先 ALTER 加列，重建时的 CREATE 会撞
        # "duplicate column name: user_id"（专家评审 P0-3 的半迁移场景实测）。
        for table in _TENANT_TABLES:
            if table in _COMPOSITE_TABLES or table in _COMPOSITE_MULTI:
                continue
            cur = await _db.execute(f"PRAGMA table_info({table})")
            cols = {row["name"] for row in await cur.fetchall()}
            if not cols:
                continue
            if "user_id" not in cols:
                await _db.execute(
                    f"ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0"
                )

        # 2) 单列业务主键表：重建为 (user_id, key)
        for table, (key_col, _decl) in _COMPOSITE_TABLES.items():
            if await _pk_cols(table) == ["user_id", key_col]:
                continue
            await _rebuild_with_user_id(table, key_col, [])

        # 3) 复合主键表（settings / budgets）
        for table, (cols, copy_sql) in _COMPOSITE_MULTI.items():
            if await _pk_cols(table) == list(cols):
                continue
            await _rebuild_composite(table, cols, copy_sql)

        # 4) 只带 UNIQUE 约束的表（sessions.thread_id）
        for table, col in _UNIQUE_COLS.items():
            await _ensure_unique_by_tenant(table, col)

        # 4.5) 成员用户名：租户内唯一（放在迁移后建，旧库此时才有 user_id 列）
        try:
            await _db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_members_user_username"
                " ON members(user_id, username)"
            )
        except Exception:  # noqa: BLE001 — 旧库可能还没有 members 表
            pass

        # 5) 索引
        for table in (*_TENANT_TABLES, *_COMPOSITE_TABLES, *_COMPOSITE_MULTI):
            try:
                await _db.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_user ON {table}(user_id)"
                )
            except Exception:  # noqa: BLE001
                continue

        await _db.commit()
    except Exception:
        await _db.rollback()
        raise


async def _rebuild_composite(table: str, cols: tuple[str, ...], copy_sql: str) -> None:
    """重建带复合主键的表（settings / budgets），保留原有数据到租户 0。"""
    assert _db is not None
    tmp = f"{table}__mt_migrate"
    await _db.execute(f"DROP TABLE IF EXISTS {tmp}")
    if table == "settings":
        ddl = (
            f"CREATE TABLE {tmp} ("
            " user_id INTEGER NOT NULL DEFAULT 0,"
            " key TEXT NOT NULL,"
            " value TEXT NOT NULL,"
            " PRIMARY KEY (user_id, key))"
        )
    elif table == "budgets":
        ddl = (
            f"CREATE TABLE {tmp} ("
            " user_id INTEGER NOT NULL DEFAULT 0,"
            " month TEXT NOT NULL,"
            " category TEXT NOT NULL,"
            " amount REAL NOT NULL,"
            " PRIMARY KEY (user_id, month, category))"
        )
    else:  # pragma: no cover — 目前只有上面两张
        raise ValueError(f"未定义的重建表：{table}")
    await _db.execute(ddl)
    await _db.execute(copy_sql.replace("{tmp}", tmp))
    await _db.execute(f"DROP TABLE {table}")
    await _db.execute(f"ALTER TABLE {tmp} RENAME TO {table}")


async def _ensure_unique_by_tenant(table: str, col: str) -> None:
    """把列级 UNIQUE 改成 (user_id, col) 复合唯一（sessions.thread_id）。

    已经重建过（主键含 user_id 且存在复合唯一索引）则跳过。
    """
    assert _db is not None
    cur = await _db.execute(f"PRAGMA index_list({table})")
    idx = await cur.fetchall()
    for r in idx:
        if not r["unique"]:
            continue
        iinfo = await (await _db.execute(f"PRAGMA index_info({r['name']})")).fetchall()
        if [x["name"] for x in iinfo] == ["user_id", col]:
            return  # 已是复合唯一
    # 存在旧的单列唯一 → 重建表
    for r in idx:
        if not r["unique"]:
            continue
        iinfo = await (await _db.execute(f"PRAGMA index_info({r['name']})")).fetchall()
        if [x["name"] for x in iinfo] == [col]:
            await _rebuild_unique_as_composite(table, col, [])
            await _db.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_user_{col}"
                f" ON {table}(user_id, {col})"
            )
            return


async def _rebuild_with_user_id(table: str, key_col: str, columns: list[str]) -> None:
    """把单主键表重建为 (user_id, 原主键) 复合主键，保留全部数据。

    用 PRAGMA 拿到的列信息重建，而不是解析原 DDL 文本：
    后者要处理注释、换行、约束顺序，容易在真实 schema 上解析错。
    """
    assert _db is not None
    tmp = f"{table}__mt_migrate"
    cur = await _db.execute(f"PRAGMA table_info({table})")
    info = await cur.fetchall()

    defs: list[str] = []
    for r in info:
        name, decl = r["name"], str(r["type"] or "")
        if name == "user_id":
            # 半迁移库已有该列：跳过，否则新表会出现两个 user_id
            continue
        if r["notnull"]:
            decl += " NOT NULL"
        if r["dflt_value"] is not None:
            decl += f" DEFAULT {r['dflt_value']}"
        if name != key_col and r["pk"]:
            # 非主键列上的单列主键（理论上没有），保留其唯一性
            decl += " PRIMARY KEY"
        defs.append(f"{name} {decl}".strip())
    col_defs = ",\n    ".join(defs)
    await _db.execute(
        f"CREATE TABLE {tmp} (\n    user_id INTEGER NOT NULL DEFAULT 0,\n"
        f"    {col_defs},\n    PRIMARY KEY (user_id, {key_col})\n)"
    )
    if not columns:
        columns = [r["name"] for r in info if r["name"] != "user_id"]
    collist = ", ".join(columns)
    await _db.execute(
        f"INSERT INTO {tmp} (user_id, {collist}) SELECT 0, {collist} FROM {table}"
    )
    await _db.execute(f"DROP TABLE {table}")
    await _db.execute(f"ALTER TABLE {tmp} RENAME TO {table}")
    await _db.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{table}_user ON {table}(user_id)"
    )


async def _rebuild_unique_as_composite(
    table: str, col: str, columns: list[str]
) -> None:
    """重建表：去掉列级 UNIQUE，保留数据（唯一性由调用方补的复合唯一索引保证）。"""
    assert _db is not None
    tmp = f"{table}__uq_migrate"
    cur = await _db.execute(f"PRAGMA table_info({table})")
    info = await cur.fetchall()
    ddl_row = await (
        await _db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
    ).fetchone()
    orig_ddl = str(ddl_row["sql"] or "") if ddl_row else ""
    defs: list[str] = ["user_id INTEGER NOT NULL DEFAULT 0"]
    for r in info:
        name, decl = r["name"], str(r["type"] or "")
        if name == "user_id":
            continue
        if r["notnull"]:
            decl += " NOT NULL"
        if r["dflt_value"] is not None:
            decl += f" DEFAULT {r['dflt_value']}"
        if r["pk"]:
            # AUTOINCREMENT 必须保留，否则 id 会被复用（专家评审 S-8）。
            # PRAGMA 的 type 不含 AUTOINCREMENT，要回查建表 SQL。
            if "AUTOINCREMENT" in orig_ddl.upper():
                decl += " PRIMARY KEY AUTOINCREMENT"
            else:
                decl += " PRIMARY KEY"
        defs.append(f"{name} {decl}".strip())
    body = ("," + chr(10) + "    ").join(defs)
    ddl = "CREATE TABLE " + tmp + " (" + chr(10) + "    " + body + chr(10) + ")"
    await _db.execute(ddl)
    names = [r["name"] for r in info if r["name"] != "user_id"]
    collist = ", ".join(names)
    await _db.execute(
        f"INSERT INTO {tmp} (user_id, {collist}) SELECT 0, {collist} FROM {table}"
    )
    await _db.execute(f"DROP TABLE {table}")
    await _db.execute(f"ALTER TABLE {tmp} RENAME TO {table}")


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
    read_conns, _read_conns = _read_conns, []
    for c in read_conns:
        try:
            await asyncio.wait_for(c.close(), timeout=timeout)
        except (asyncio.TimeoutError, RuntimeError, Exception):  # noqa: BLE001
            pass
    _pool_locks.clear()
    _write_locks.clear()
    _pool_loop = None


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
_write_locks: dict[int, asyncio.Lock] = {}


def get_write_lock() -> asyncio.Lock:
    """取当前事件循环的写事务锁。所有多语句事务都必须持它。"""
    loop_id = id(asyncio.get_running_loop())
    lk = _write_locks.get(loop_id)
    if lk is None:
        lk = asyncio.Lock()
        _write_locks[loop_id] = lk
    return lk


def _clean_due_day(v: object) -> str:
    """扣款日归一化：'' / '1'..'31'；非法值返回 ''。"""
    s = str(v or "").strip()
    if s in {"", "0"}:
        return ""
    if s.isdigit() and 1 <= int(s) <= 31:
        return s
    return ""


_COUNT_ALLOWED_TABLES = frozenset(
    {
        "transactions",
        "positions",
        "budgets",
        "goals",
        "subscriptions",
        "members",
        "runs",
        "audit_log",
        "transactions_fts",
    }
)
_LIST_LIMIT_MAX = 500


def _clamp_limit(limit: int, default: int = 50) -> int:
    """限制分页上限，防止 limit=9999999 导致内存爆炸。"""
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return default
    if n <= 0:
        return default
    return min(n, _LIST_LIMIT_MAX)


async def _count(table: str) -> int:
    if table not in _COUNT_ALLOWED_TABLES:
        raise ValueError(f"disallowed table for _count: {table!r}")
    cur = await _db.execute(f"SELECT COUNT(*) AS n FROM {table}")
    row = await cur.fetchone()
    return int(row["n"]) if row else 0


async def _seed_all(user_id: int = 0) -> None:
    """种入示例数据到指定租户。

    默认 0（本机默认账本）；`reset_to_seed` 传入当前租户，避免把示例数据
    写到别人的账本里。
    """
    assert _db is not None
    await _db.executemany(
        "INSERT INTO positions(user_id,symbol,name,kind,industry,shares,cost,last,buy_date,fee)"
        " VALUES(:user_id,:symbol,:name,:kind,:industry,:shares,:cost,:last,:buy_date,:fee)",
        [{**p, "buy_date": None, "fee": 0.0, "user_id": user_id} for p in SEED_POSITIONS],
    )
    await _db.executemany(
        "INSERT INTO transactions(user_id,date,item,category,amount) VALUES(?,?,?,?,?)",
        [
            (user_id, _seed_date(d), item, cat, amt)
            for d, item, cat, amt in SEED_TRANSACTIONS
        ],
    )
    await _db.executemany(
        "INSERT INTO subscriptions(user_id,name,monthly,note,due_day)"
        " VALUES(:user_id,:name,:monthly,:note,:due_day)",
        [
            {**s, "due_day": s.get("due_day", ""), "user_id": user_id}
            for s in SEED_SUBSCRIPTIONS
        ],
    )
    await _db.executemany(
        "INSERT INTO debts(user_id,name,monthly,balance,rate,due_day)"
        " VALUES(:user_id,:name,:monthly,:balance,:rate,:due_day)",
        [{**d, "due_day": d.get("due_day", ""), "user_id": user_id} for d in SEED_DEBTS],
    )
    await _db.executemany(
        "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
        list(SEED_SETTINGS.items()),
    )


async def _ensure_defaults() -> None:
    """补齐默认设置键。

    注意：默认值要落给**每一个已存在的租户**（否则新用户读不到默认项），
    而不是只落给当前请求的租户——这个函数在启动时运行，没有请求上下文。
    """
    conn = await _conn()
    try:
        rows = await fetch_all("SELECT DISTINCT user_id FROM settings")
        uids = {int(r["user_id"]) for r in rows} or {0}
    except Exception:  # noqa: BLE001 — 旧库可能还没有 user_id 列
        uids = {0}
    params = [(uid, k, v) for uid in sorted(uids) for k, v in DEFAULT_SETTINGS.items()]
    await conn.executemany(
        "INSERT OR IGNORE INTO settings(user_id,key,value) VALUES(?,?,?)", params
    )


async def _migrate_sessions_from_runs() -> None:
    """历史迁移：已有问答（旧库）按 thread 生成会话，标题取该线程首个问题。

    系统归档线程（cron 晨报、skill:<id> 技能定时触发）不属于「问AI」会话列表：
    它们由 save_run(skip_session=True) 写入，此处也必须一并排除，否则重启时会把
    系统产出补建成会话、污染会话列表（skip_session 只拦写入侧）。
    同时自愈清理历史版本已误建的系统线程会话行。
    """
    conn = await _conn()
    # 启动期维护：跨租户清理系统归档线程（cron / skill:*）的会话行。
    # 这些线程本就不属于任何用户的会话列表，清理是幂等的全局操作。
    await conn.execute(
        "DELETE FROM sessions WHERE thread_id='cron' OR thread_id LIKE 'skill:%'"  # tenant: allow
    )
    # 按租户各建一份：同一 thread_id 可能属于不同用户，不能混用
    rows = await (
        await conn.execute(
            "SELECT r.user_id, r.thread_id, r.question FROM runs r"
            " WHERE r.id = (SELECT MIN(id) FROM runs x"
            "               WHERE x.thread_id = r.thread_id AND x.user_id = r.user_id)"
            "   AND r.thread_id <> 'cron' AND r.thread_id NOT LIKE 'skill:%'"
            "   AND NOT EXISTS (SELECT 1 FROM sessions s"
            "                   WHERE s.thread_id = r.thread_id AND s.user_id = r.user_id)"
        )
    ).fetchall()
    if not rows:
        await conn.commit()
        return
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for r in rows:
        await conn.execute(
            "INSERT OR IGNORE INTO sessions(user_id,thread_id,title,created_at,updated_at)"
            " VALUES(?,?,?,?,?)",
            (r["user_id"], r["thread_id"], str(r["question"])[:40] or "新会话", now, now),
        )
    await conn.commit()  # M1.3：读池时代所有写路径必须真实提交，否则读池不可见


async def reset_to_seed() -> dict[str, Any]:
    """清空并重新种入示例数据（演示/测试用）。

    只重置示例数据本身（持仓/流水/订阅/负债/预算）与 data_note 标记；用户设置
    （AI 端点与密钥、Agent 配置、偏好、账本假设）一律保留——「恢复示例数据」
    不应把用户的模型密钥与个性化配置一起清掉（e2e 复用在跑的研发服务时同理）。
    """
    from .tenant import current_user_id

    uid = current_user_id()
    conn = await _conn()
    for t in (
        "positions",
        "transactions",
        "subscriptions",
        "debts",
        "budgets",
    ):
        # 只清当前租户：此前无 WHERE，任何用户调用都会抹掉全实例账本
        await conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
    # 数据已换回种子 → data_note 标回 seed；其余 settings 全部保留
    await conn.execute(
        "INSERT INTO settings(user_id,key,value) VALUES(?,'data_note','seed') "
        "ON CONFLICT(user_id,key) DO UPDATE SET value='seed'",
        (uid,),
    )
    await _seed_all(uid)
    await conn.commit()
    return {"ok": True, "reset": True}


# --------------------------------------------------------------------------
# 读
# --------------------------------------------------------------------------


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
        if _db is None:
            await init_db()
        _pool_loop = loop
        if len(_read_conns) < _READ_POOL_SIZE:
            # 用 PRAGMA query_only 实现只读，而不是 URI 的 mode=ro：
            # mode=ro 在 WAL 模式下需要读 -wal 文件，若写连接尚未 checkpoint，
            # 只读连接会一直等待（CLI 连续调用实测卡死）。
            # query_only 复用普通连接语义，只禁止写入，不改变 WAL 打开方式。
            c = await aiosqlite.connect(str(DB_PATH))
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


async def list_positions() -> list[dict[str, Any]]:
    # 租户过滤：只返回当前用户的持仓（默认租户 0 = 未启用登录的本机用户）
    from .tenant import current_user_id

    return await fetch_all(
        "SELECT * FROM positions WHERE user_id=? ORDER BY symbol",
        (current_user_id(),),
    )


async def list_transactions(member_id: int | None = None) -> list[dict[str, Any]]:
    """列出交易流水。

    - member_id=None：返回当前租户的全部流水
    - member_id=0 or specific id：返回 shared=1 的流水 + 自己拥有的流水
    """
    from .tenant import current_user_id

    uid = current_user_id()
    if member_id is None:
        return await fetch_all(
            "SELECT * FROM transactions WHERE user_id=? ORDER BY date DESC, id DESC",
            (uid,),
        )
    # 有 member_id：共享流水 + 自己的流水（含私有）
    return await fetch_all(
        "SELECT * FROM transactions WHERE user_id=? AND (is_shared=1 OR owner_id=?) "
        "ORDER BY date DESC, id DESC",
        (uid, member_id),
    )


async def list_subscriptions() -> list[dict[str, Any]]:
    from .tenant import current_user_id

    return await fetch_all(
        "SELECT * FROM subscriptions WHERE user_id=? ORDER BY name",
        (current_user_id(),),
    )


async def list_debts() -> list[dict[str, Any]]:
    from .tenant import current_user_id

    return await fetch_all(
        "SELECT * FROM debts WHERE user_id=? ORDER BY name", (current_user_id(),)
    )


async def get_settings() -> dict[str, str]:
    """当前租户的设置。缺省键回落到 DEFAULT_SETTINGS，保证接口形状稳定。"""
    from .tenant import current_user_id

    rows = await fetch_all(
        "SELECT * FROM settings WHERE user_id=?", (current_user_id(),)
    )
    out = dict(DEFAULT_SETTINGS)
    out.update({r["key"]: r["value"] for r in rows})
    return out


# 预算口径排除项：投资/还款属于储蓄或资金转移，不是消费支出，不计入预算使用
NON_CONSUMPTION_CATEGORIES: tuple[str, ...] = ("投资", "还款")


async def set_setting(key: str, value: str) -> dict[str, Any]:
    from .tenant import current_user_id

    conn = await _conn()
    await conn.execute(
        "INSERT INTO settings(user_id,key,value) VALUES(?,?,?) "
        "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
        (current_user_id(), str(key), str(value)),
    )
    await conn.commit()
    return {"ok": True}


async def _mark_user_data(conn: aiosqlite.Connection) -> None:
    from .tenant import current_user_id

    await conn.execute(
        "INSERT INTO settings(user_id,key,value) VALUES(?,'data_note','user') "
        "ON CONFLICT(user_id,key) DO UPDATE SET value='user'",
        (current_user_id(),),
    )


def uuid_hex() -> str:
    return uuid.uuid4().hex


# --------------------------------------------------------------------------
# 待确认动作（写操作 HITL：确认前不落库，token 一次性消费）
# --------------------------------------------------------------------------


PENDING_TTL_MINUTES = 10


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
