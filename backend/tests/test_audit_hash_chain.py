"""审计哈希链：正常链可验证；改字段/删中间行会断链；旧库无哈希行按 legacy 跳过。"""

from __future__ import annotations

from app import db


async def _add(path: str) -> None:
    await db.add_audit_log(
        action="WRITE",
        method="POST",
        path=path,
        status=200,
        actor="user:1",
        detail=f"POST {path}",
        duration_ms=3,
    )


async def _latest_heads() -> list[dict]:
    conn = await db._conn()
    cur = await conn.execute(
        "SELECT id, entry_hash FROM audit_logs WHERE user_id=0 ORDER BY id"
    )
    return [dict(r) for r in await cur.fetchall()]


async def test_chain_verifies_and_detects_field_tamper(temp_db) -> None:
    await _add("/api/a")
    await _add("/api/b")
    ok = await db.verify_audit_chain()
    assert ok["ok"] is True
    assert ok["checked"] == 2
    assert ok["head"]

    conn = await db._conn()
    await conn.execute(
        "UPDATE audit_logs SET detail='tampered' WHERE user_id=0 AND path='/api/a'"
    )
    await conn.commit()

    broken = await db.verify_audit_chain()
    assert broken["ok"] is False
    assert broken["checked"] == 0
    assert "entry_hash" in broken["reason"]


async def test_chain_detects_deleted_middle_row(temp_db) -> None:
    await _add("/api/a")
    await _add("/api/b")
    await _add("/api/c")
    heads = await _latest_heads()

    conn = await db._conn()
    await conn.execute("DELETE FROM audit_logs WHERE id=?", (heads[1]["id"],))
    await conn.commit()

    broken = await db.verify_audit_chain()
    assert broken["ok"] is False
    assert broken["checked"] == 1
    assert broken["broken_at"] == heads[2]["id"]
    assert "prev_hash" in broken["reason"]


async def test_legacy_rows_are_skipped(temp_db) -> None:
    conn = await db._conn()
    await conn.execute(
        "INSERT INTO audit_logs(user_id,ts,action,method,path,status,actor,detail,duration_ms)"
        " VALUES(0,'2026-01-01T00:00:00+08:00','WRITE','POST','/legacy',200,'','',0)"
    )
    await conn.commit()
    await _add("/api/new")

    result = await db.verify_audit_chain()
    assert result["ok"] is True
    assert result["checked"] == 1
    assert result["legacy_rows"] == 1
