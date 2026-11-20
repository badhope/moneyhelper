"""迁移安全网：一致性快照与中断残留临时表的恢复/清理。"""

from __future__ import annotations

from pathlib import Path

from ..logging_utils import get_logger
from . import _core

log = get_logger(__name__)


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
