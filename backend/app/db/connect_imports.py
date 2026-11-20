"""券商交割单导入批次记录。"""

from __future__ import annotations

import json
from typing import Any

from ..logging_utils import get_logger
from ..timeutil import new_id as _new_id
from ..timeutil import now_iso as _now
from ._core import _conn, fetch_all, fetch_one, get_write_lock
from .connect_invoices import file_hash
from .tenant import current_user_id

log = get_logger(__name__)


async def record_brokerage_import(
    *,
    file_name: str,
    raw: bytes,
    account: str,
    position_count: int,
    applied: int,
    warnings: list[str],
) -> dict[str, Any]:
    """记录一次持仓导入；同文件重复导入返回既有记录（duplicate=True）。"""
    uid = current_user_id()
    digest = file_hash(raw)
    existing = await fetch_one(
        "SELECT * FROM brokerage_imports WHERE user_id=? AND file_hash=?", (uid, digest)
    )
    if existing:
        row = dict(existing)
        row["warnings"] = json.loads(row.pop("warnings_json", "[]"))
        row["duplicate"] = True
        return row

    bid = _new_id("bimp")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO brokerage_imports(user_id,id,file_name,file_hash,account,"
            "position_count,applied,warnings_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                uid,
                bid,
                file_name[:120],
                digest,
                account[:40],
                int(position_count),
                int(applied),
                json.dumps(warnings[:50], ensure_ascii=False),
                _now(),
            ),
        )
        await conn.commit()
    return {
        "id": bid,
        "file_name": file_name,
        "account": account,
        "position_count": position_count,
        "applied": applied,
        "warnings": warnings,
        "duplicate": False,
    }


async def list_brokerage_imports(limit: int = 30) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM brokerage_imports WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (current_user_id(), max(1, min(int(limit), 200))),
    )
    out = []
    for r in rows:
        row = dict(r)
        row["warnings"] = json.loads(row.pop("warnings_json", "[]"))
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# 条件单
# ---------------------------------------------------------------------------
