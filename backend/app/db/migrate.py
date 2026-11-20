"""老库迁移：补列、多租户重建、唯一键组合化、临时表清理。

从 _core.py 拆出。这些函数共享单写连接（_core._db），因此不持有自己的连接状态：
一律通过 _core 读取当前连接，测试夹具替换连接/路径后立即生效。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..logging_utils import get_logger
from . import _core

log = get_logger(__name__)

async def _migrate_add_columns() -> None:
    """老库增量迁移：为已有表补新列（CREATE TABLE IF NOT EXISTS 不会改老表）。"""
    assert _core._db is not None
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
            # harness：按轮 token 计量（模型真实回传，无模型时保持 0）
            "tokens_in": "INTEGER NOT NULL DEFAULT 0",
            "tokens_out": "INTEGER NOT NULL DEFAULT 0",
        },
        # 主动遗忘：记录每次被注入/使用的时间，便于按未使用时长清理
        "user_memory": {"last_used": "TEXT NOT NULL DEFAULT ''"},
        # 知识库：附件可标记为「入库」，问答时按 BM25 检索其片段
        "attachments": {"indexed": "INTEGER NOT NULL DEFAULT 0"},
        # 审计哈希链：旧库补列；历史行没有哈希，验链时作为 legacy 前缀跳过
        "audit_logs": {
            "prev_hash": "TEXT NOT NULL DEFAULT ''",
            "entry_hash": "TEXT NOT NULL DEFAULT ''",
        },
        # 切片 7b：用户显式选择的工作租户（全局租户切换）
        "users": {"active_tenant_id": "INTEGER"},
        # 切片 8：付款可关联报销单或应付单；应付付款生成付款凭证草稿
        "payments": {"payable_id": "INTEGER", "gl_entry_id": "INTEGER"},
        # 切片 9：银行流水可自动生成凭证，用 gl_entry_id 记下归属（兼作幂等标记）
        "bank_transactions": {"gl_entry_id": "INTEGER"},
    }
    # transactions 表：新增 owner_id（交易归属成员）与 is_shared（是否共享）
    tx_cols = await _core._db.execute("PRAGMA table_info(transactions)")
    tx_existing = {row["name"] for row in await tx_cols.fetchall()}
    if "owner_id" not in tx_existing:
        await _core._db.execute(
            "ALTER TABLE transactions ADD COLUMN owner_id INTEGER REFERENCES members(id)"
        )
    if "is_shared" not in tx_existing:
        await _core._db.execute(
            "ALTER TABLE transactions ADD COLUMN is_shared INTEGER NOT NULL DEFAULT 1"
        )

    for table, adds in cols.items():
        cur = await _core._db.execute(f"PRAGMA table_info({table})")
        existing = {row["name"] for row in await cur.fetchall()}
        for col, decl in adds.items():
            if col not in existing:
                await _core._db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    # 付款唯一性按来源拆分：报销付款 claim_id>0；应付付款 payable_id 非空。
    # 旧库原索引是全表 UNIQUE(tenant_id,claim_id)，必须替换成部分索引，
    # 否则所有应付付款都会以 claim_id=0 互相冲突。
    await _core._db.execute("DROP INDEX IF EXISTS idx_payment_tenant_claim")
    await _core._db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_tenant_claim"
        " ON payments(tenant_id, claim_id) WHERE claim_id > 0"
    )
    await _core._db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_tenant_payable"
        " ON payments(tenant_id, payable_id) WHERE payable_id IS NOT NULL"
    )


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


async def _backup_db_consistent(target: Path) -> None:
    """用 SQLite 在线备份 API 生成一致性快照。

    为什么不能 shutil.copy2：WAL 模式下已提交数据可能还在 -wal 文件里，
    只复制主文件会得到一个"空库"（专家评审 P0-1 实测：备份里 0 张表）。
    Connection.backup() 由 SQLite 负责 checkpoint 与一致性，是最可靠的做法。
    """
    import sqlite3

    src = sqlite3.connect(str(_core.DB_PATH))
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
    assert _core._db is not None
    cur = await _core._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%__mt_migrate' OR name LIKE '%__uq_migrate')"
    )
    stale = [r["name"] for r in await cur.fetchall()]
    for name in stale:
        base = name.split("__")[0]
        base_pk = await _core._pk_cols(base)
        if base_pk:
            # 原表还在（崩溃在 DROP 之前）：临时表是多余的
            await _core._db.execute(f"DROP TABLE IF EXISTS {name}")
            get_logger("db").info("db.migrate_cleanup_temp=%s", name)
        else:
            # 原表已 DROP、只剩临时表：把它改回正式名，保住数据
            await _core._db.execute(f"ALTER TABLE {name} RENAME TO {base}")
            get_logger("db").info("db.migrate_recover_temp=%s -> %s", name, base)


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

    await _recover_stale_temp_tables()
    if not await _core._needs_multitenant():
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = Path(str(_core.DB_PATH) + f".pre-mt-{stamp}")
    try:
        await _backup_db_consistent(backup_path)
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
            await _rebuild_with_user_id(table, key_col, [])

        # 3) 复合主键表（settings / budgets）
        for table, (cols, copy_sql) in _COMPOSITE_MULTI.items():
            if await _core._pk_cols(table) == list(cols):
                continue
            await _rebuild_composite(table, cols, copy_sql)

        # 4) 只带 UNIQUE 约束的表（sessions.thread_id）
        for table, col in _UNIQUE_COLS.items():
            await _ensure_unique_by_tenant(table, col)

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


async def _rebuild_composite(table: str, cols: tuple[str, ...], copy_sql: str) -> None:
    """重建带复合主键的表（settings / budgets），保留原有数据到租户 0。"""
    assert _core._db is not None
    tmp = f"{table}__mt_migrate"
    await _core._db.execute(f"DROP TABLE IF EXISTS {tmp}")
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
    await _core._db.execute(ddl)
    await _core._db.execute(copy_sql.replace("{tmp}", tmp))
    await _core._db.execute(f"DROP TABLE {table}")
    await _core._db.execute(f"ALTER TABLE {tmp} RENAME TO {table}")


async def _ensure_unique_by_tenant(table: str, col: str) -> None:
    """把列级 UNIQUE 改成 (user_id, col) 复合唯一（sessions.thread_id）。

    已经重建过（主键含 user_id 且存在复合唯一索引）则跳过。
    """
    assert _core._db is not None
    cur = await _core._db.execute(f"PRAGMA index_list({table})")
    idx = await cur.fetchall()
    for r in idx:
        if not r["unique"]:
            continue
        iinfo = await (await _core._db.execute(f"PRAGMA index_info({r['name']})")).fetchall()
        if [x["name"] for x in iinfo] == ["user_id", col]:
            return  # 已是复合唯一
    # 存在旧的单列唯一 → 重建表
    for r in idx:
        if not r["unique"]:
            continue
        iinfo = await (await _core._db.execute(f"PRAGMA index_info({r['name']})")).fetchall()
        if [x["name"] for x in iinfo] == [col]:
            await _rebuild_unique_as_composite(table, col, [])
            await _core._db.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_user_{col}"
                f" ON {table}(user_id, {col})"
            )
            return


async def _rebuild_with_user_id(table: str, key_col: str, columns: list[str]) -> None:
    """把单主键表重建为 (user_id, 原主键) 复合主键，保留全部数据。

    用 PRAGMA 拿到的列信息重建，而不是解析原 DDL 文本：
    后者要处理注释、换行、约束顺序，容易在真实 schema 上解析错。
    """
    assert _core._db is not None
    tmp = f"{table}__mt_migrate"
    cur = await _core._db.execute(f"PRAGMA table_info({table})")
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
    await _core._db.execute(
        f"CREATE TABLE {tmp} (\n    user_id INTEGER NOT NULL DEFAULT 0,\n"
        f"    {col_defs},\n    PRIMARY KEY (user_id, {key_col})\n)"
    )
    if not columns:
        columns = [r["name"] for r in info if r["name"] != "user_id"]
    collist = ", ".join(columns)
    await _core._db.execute(
        f"INSERT INTO {tmp} (user_id, {collist}) SELECT 0, {collist} FROM {table}"
    )
    await _core._db.execute(f"DROP TABLE {table}")
    await _core._db.execute(f"ALTER TABLE {tmp} RENAME TO {table}")
    await _core._db.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{table}_user ON {table}(user_id)"
    )


async def _rebuild_unique_as_composite(
    table: str, col: str, columns: list[str]
) -> None:
    """重建表：去掉列级 UNIQUE，保留数据（唯一性由调用方补的复合唯一索引保证）。"""
    assert _core._db is not None
    tmp = f"{table}__uq_migrate"
    cur = await _core._db.execute(f"PRAGMA table_info({table})")
    info = await cur.fetchall()
    ddl_row = await (
        await _core._db.execute(
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
    await _core._db.execute(ddl)
    names = [r["name"] for r in info if r["name"] != "user_id"]
    collist = ", ".join(names)
    await _core._db.execute(
        f"INSERT INTO {tmp} (user_id, {collist}) SELECT 0, {collist} FROM {table}"
    )
    await _core._db.execute(f"DROP TABLE {table}")
    await _core._db.execute(f"ALTER TABLE {tmp} RENAME TO {table}")


