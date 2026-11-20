"""多租户迁移清单与判定：哪些表加 user_id、哪些要重建主键。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..logging_utils import get_logger
from . import _core

log = get_logger(__name__)


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
    "financial_statements",
    "paper_accounts",
    "paper_trades",
    "paper_snapshots",
    "family_motions",
    "family_votes",
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
    assert _core._db is not None
    cur = await _core._db.execute(f"PRAGMA table_info({table})")
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
        pk = await _core._pk_cols(table)
        if not pk:
            continue
        if pk != ["user_id", key_col]:
            return True
    for table, (cols, _sql) in _COMPOSITE_MULTI.items():
        pk = await _core._pk_cols(table)
        if not pk:
            continue
        if pk != list(cols):
            return True
    # 普通表：缺 user_id 列也需要迁移
    for table in _TENANT_TABLES:
        cur = await _core._db.execute(f"PRAGMA table_info({table})")
        info = await cur.fetchall()
        if not info:
            continue
        if "user_id" not in {r["name"] for r in info}:
            return True
    return False


async def _migrate_multitenant() -> None:
    """多租户迁移：加 user_id 维度，并把历史数据归到默认租户 0。

    安全性（专家评审 P0-1/P0-2/P0-3 修复）：
    1. 动结构前用 SQLite backup API 生成**一致性快照**（WAL 下 copy2 会得到空库）；
       备份失败直接中止迁移——备份是 DROP 的唯一逃生舱。
    2. 整个迁移包在 BEGIN IMMEDIATE ... COMMIT 里，中途崩溃自动回滚；
       启动时还会清理/恢复上次遗留的临时表。
    3. 是否需要迁移按**主键形状**判断（见 _core._needs_multitenant），
       半迁移库能被识别并修复。
    """
    assert _core._db is not None

    await _core._recover_stale_temp_tables()
    if not await _core._needs_multitenant():
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = Path(str(_core.DB_PATH) + f".pre-mt-{stamp}")
    try:
        await _core._backup_db_consistent(backup_path)
    except Exception as exc:  # noqa: BLE001
        # 备份失败不能继续：重建表是不可逆的 DROP
        get_logger("db").error("db.migrate_backup_failed, abort: %s", exc)
        raise RuntimeError(f"多租户迁移前备份失败，已中止：{exc}") from exc
    get_logger("db").info("db.migrate_backup=%s", backup_path)

    await _core._db.execute("BEGIN IMMEDIATE")
    try:
        # 1) 普通表：加 user_id 列。
        # 关键：复合主键表（positions 等）也会遍历到这里，但它们的 user_id
        # 由重建逻辑负责；若这里先 ALTER 加列，重建时的 CREATE 会撞
        # "duplicate column name: user_id"（专家评审 P0-3 的半迁移场景实测）。
        for table in _TENANT_TABLES:
            if table in _COMPOSITE_TABLES or table in _COMPOSITE_MULTI:
                continue
            cur = await _core._db.execute(f"PRAGMA table_info({table})")
            cols = {row["name"] for row in await cur.fetchall()}
            if not cols:
                continue
            if "user_id" not in cols:
                await _core._db.execute(
                    f"ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0"
                )

        # 2) 单列业务主键表：重建为 (user_id, key)
        for table, (key_col, _decl) in _COMPOSITE_TABLES.items():
            if await _core._pk_cols(table) == ["user_id", key_col]:
                continue
            await _core._rebuild_with_user_id(table, key_col, [])

        # 3) 复合主键表（settings / budgets）
        for table, (cols, copy_sql) in _COMPOSITE_MULTI.items():
            if await _core._pk_cols(table) == list(cols):
                continue
            await _core._rebuild_composite(table, cols, copy_sql)

        # 4) 只带 UNIQUE 约束的表（sessions.thread_id）
        for table, col in _UNIQUE_COLS.items():
            await _core._ensure_unique_by_tenant(table, col)

        # 4.5) 成员用户名：租户内唯一（放在迁移后建，旧库此时才有 user_id 列）
        try:
            await _core._db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_members_user_username"
                " ON members(user_id, username)"
            )
        except Exception:  # noqa: BLE001 — 旧库可能还没有 members 表
            pass

        # 5) 索引
        for table in (*_TENANT_TABLES, *_COMPOSITE_TABLES, *_COMPOSITE_MULTI):
            try:
                await _core._db.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_user ON {table}(user_id)"
                )
            except Exception:  # noqa: BLE001
                continue

        await _core._db.commit()
    except Exception:
        await _core._db.rollback()
        raise
