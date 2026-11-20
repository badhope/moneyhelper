"""表重建：主键/唯一约束按租户组合化，数据原地搬运到 user_id=0。"""

from __future__ import annotations

from ..logging_utils import get_logger
from . import _core

log = get_logger(__name__)


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
            await _core._rebuild_unique_as_composite(table, col, [])
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
