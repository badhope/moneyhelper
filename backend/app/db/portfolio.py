"""持仓域：持仓 CRUD/合并 + 自选股。"""
from __future__ import annotations

import json
import math
from typing import Any

from ._core import (
    _conn,
    _mark_user_data,
)
from .tenant import current_user_id
from .undo import _record_snapshot, _row_to_json

# --------------------------------------------------------------------------
# 写
# --------------------------------------------------------------------------


async def add_position(p: dict[str, Any]) -> dict[str, Any]:
    conn = await _conn()
    clean = {
        "symbol": str(p.get("symbol", "")).strip(),
        "name": str(p.get("name", "")).strip() or "未命名",
        "kind": str(p.get("kind", "股票")).strip() or "股票",
        "industry": str(p.get("industry", "其他")).strip() or "其他",
        "shares": float(p.get("shares", 0) or 0),
        "cost": float(p.get("cost", 0) or 0),
        "last": float(p.get("last", 0) or 0),
        "buy_date": (str(p.get("buy_date") or "").strip() or None),
        "fee": float(p.get("fee", 0) or 0),
    }
    if not clean["symbol"]:
        raise ValueError("代码不能为空")
    # isfinite 同时挡 NaN 与 ±Inf：Inf 会被 SQLite 原样存下，
    # 随后 JSON 序列化（allow_nan=False）抛错，把整个持仓/总览接口打成 500。
    if clean["shares"] <= 0 or not math.isfinite(clean["shares"]):
        raise ValueError("股数需为大于 0 的有限数字")
    if clean["cost"] < 0 or not math.isfinite(clean["cost"]):
        raise ValueError("成本价需为有限数字且不能为负")
    if clean["last"] < 0 or not math.isfinite(clean["last"]):
        raise ValueError("现价需为有限数字且不能为负")
    if clean["fee"] < 0 or not math.isfinite(clean["fee"]):
        raise ValueError("费用需为有限数字且不能为负")
    uid = current_user_id()
    # 撤销快照：记录 upsert 前的状态（已存在 → 旧行 JSON，新增 → '{}'）
    existing = await (
        await conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND symbol=?", (uid, clean["symbol"])
        )
    ).fetchone()
    await _record_snapshot("position", clean["symbol"], _row_to_json(existing))
    await conn.execute(
        "INSERT INTO positions(user_id,symbol,name,kind,industry,shares,cost,last,buy_date,fee)"
        " VALUES(:user_id,:symbol,:name,:kind,:industry,:shares,:cost,:last,:buy_date,:fee)"
        " ON CONFLICT(user_id,symbol) DO UPDATE SET name=excluded.name, kind=excluded.kind,"
        " industry=excluded.industry, shares=excluded.shares, cost=excluded.cost,"
        " last=excluded.last, buy_date=excluded.buy_date, fee=excluded.fee",
        {**clean, "user_id": uid},
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "symbol": clean["symbol"]}


async def delete_position(symbol: str) -> dict[str, Any]:
    conn = await _conn()
    uid = current_user_id()
    # 撤销快照：记录删除前的全量旧行，撤回时 INSERT OR REPLACE 恢复
    old = await (
        await conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND symbol=?", (uid, symbol)
        )
    ).fetchone()
    if old is None:
        return {"ok": False, "deleted": 0}
    await _record_snapshot("position", symbol, _row_to_json(old))
    cur = await conn.execute(
        "DELETE FROM positions WHERE user_id=? AND symbol=?", (uid, symbol)
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount}


async def update_position(p: dict[str, Any], symbol: str) -> dict[str, Any]:
    """编辑指定 symbol 的持仓。fields 里缺的键保持原值；校验与 add_position 一致。

    整个「读旧值 → 校验 → 写快照 → 更新」包在一个事务里（write_txn）：
    原实现先写撤销快照再做 float() 解析，传入 "abc" 时解析抛错、事务悬空，
    下一条无关写操作的 commit 会把这条幽灵快照一起提交。
    """
    from ._core import write_txn

    async with write_txn() as conn:
        return await _update_position_locked(conn, p, symbol)


async def _update_position_locked(conn, p: dict[str, Any], symbol: str) -> dict[str, Any]:
    """update_position 的实际写入段（调用方必须已在 write_txn 内）。"""
    uid = current_user_id()
    cur = await conn.execute(
        "SELECT name,kind,industry,shares,cost,last,buy_date,fee FROM positions"
        " WHERE user_id=? AND symbol=?",
        (uid, symbol),
    )
    row = await cur.fetchone()
    if row is None:
        raise ValueError(f"持仓 {symbol} 不存在")
    old = {
        "name": row[0],
        "kind": row[1],
        "industry": row[2],
        "shares": row[3],
        "cost": row[4],
        "last": row[5],
        "buy_date": row[6],
        "fee": row[7],
    }
    clean = {
        "name": str(p.get("name", old["name"])).strip() or old["name"],
        "kind": str(p.get("kind", old["kind"])).strip() or old["kind"],
        "industry": str(p.get("industry", old["industry"])).strip() or old["industry"],
        "shares": float(p.get("shares", old["shares"])),
        "cost": float(p.get("cost", old["cost"])),
        "last": float(p.get("last", old["last"])),
        "buy_date": (str(p.get("buy_date", old["buy_date"] or "")).strip() or None),
        "fee": float(p.get("fee", old["fee"])),
    }
    # 校验必须在写快照之前完成：否则校验失败时快照已落库。
    if clean["shares"] <= 0 or not math.isfinite(clean["shares"]):
        raise ValueError("股数需为大于 0 的有限数字")
    if clean["cost"] < 0 or not math.isfinite(clean["cost"]):
        raise ValueError("成本价需为有限数字且不能为负")
    if clean["last"] < 0 or not math.isfinite(clean["last"]):
        raise ValueError("现价需为有限数字且不能为负")
    if clean["fee"] < 0 or not math.isfinite(clean["fee"]):
        raise ValueError("费用需为有限数字且不能为负")

    # 撤销快照：写入前的全量旧行，撤回时恢复（在校验通过后、更新前）
    await _record_snapshot(
        "position",
        symbol,
        json.dumps({"symbol": symbol, **old}, ensure_ascii=False, default=str),
    )
    await conn.execute(
        "UPDATE positions SET name=:name, kind=:kind, industry=:industry,"
        " shares=:shares, cost=:cost, last=:last, buy_date=:buy_date, fee=:fee"
        " WHERE user_id=:user_id AND symbol=:symbol",
        {**clean, "symbol": symbol, "user_id": uid},
    )
    await _mark_user_data(conn)
    return {"ok": True, "symbol": symbol}


async def merge_positions_by_name(name: str) -> dict[str, Any]:
    """同名不同 symbol 的持仓合并成一条：保留最早录入那条的 symbol，
    股数求和、成本/现价/费用加权平均。返回合并掉的条数。"""
    nm = str(name).strip()
    if not nm:
        raise ValueError("名称不能为空")
    conn = await _conn()
    # 合并快照需要全量字段，以备撤回时按 symbol 完整恢复每一行
    cur = await conn.execute(
        "SELECT * FROM positions WHERE user_id=? AND name=? ORDER BY symbol",
        (current_user_id(), nm),
    )
    old_rows = [dict(r) for r in await cur.fetchall()]
    if len(old_rows) <= 1:
        return {"ok": True, "merged": 0}

    # 撤销快照：为合并涉及的所有行各存一份完整旧行 JSON，撤回时按 symbol 各自 INSERT OR REPLACE
    for r in old_rows:
        await _record_snapshot(
            "position", r["symbol"], json.dumps(r, ensure_ascii=False, default=str)
        )

    rows = [
        {
            "symbol": r["symbol"],
            "shares": r["shares"],
            "cost": r["cost"],
            "last": r["last"],
            "fee": r["fee"],
        }
        for r in old_rows
    ]

    # 保留最早录入那条（created_at 最小 / symbol 字典序最小兜底），其余合并进它
    keep = rows[0]
    total_shares = sum(r["shares"] for r in rows if r["shares"] > 0)
    if total_shares <= 0:
        total_shares = keep["shares"]

    # 成本/现价/费用按股数加权平均（share=0 的条目权重取 1）
    def _wavg(field: str) -> float:
        num = 0.0
        den = 0.0
        for r in rows:
            w = r["shares"] if r["shares"] > 0 else 1.0
            num += r[field] * w
            den += w
        return round(num / den, 6) if den else 0.0

    merged_cost = _wavg("cost")
    merged_last = _wavg("last")
    # 佣金（fee）是每笔持仓的总额，合并时求和而非加权平均
    merged_fee = round(sum(r["fee"] for r in rows), 6)

    await conn.execute(
        "UPDATE positions SET shares=?, cost=?, last=?, fee=?"
        " WHERE user_id=? AND symbol=?",
        (
            total_shares,
            merged_cost,
            merged_last,
            merged_fee,
            current_user_id(),
            keep["symbol"],
        ),
    )
    for r in rows[1:]:
        await conn.execute(
            "DELETE FROM positions WHERE user_id=? AND symbol=?",
            (current_user_id(), r["symbol"]),
        )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "merged": len(rows) - 1, "symbol": keep["symbol"]}


# --------------------------------------------------------------------------
# 自选行情（watchlist）
# --------------------------------------------------------------------------


async def list_watchlist() -> list[dict[str, Any]]:
    """当前租户的自选列表。"""
    conn = await _conn()
    cur = await conn.execute(
        "SELECT symbol,name,kind,created_at FROM watchlist WHERE user_id=? ORDER BY created_at",
        (current_user_id(),),
    )
    rows = await cur.fetchall()
    return [
        {"symbol": r[0], "name": r[1], "kind": r[2], "created_at": r[3]} for r in rows
    ]


async def add_watchlist(
    symbol: str, name: str = "", kind: str = "股票"
) -> dict[str, Any]:
    sym = str(symbol).strip().upper()
    if not sym:
        raise ValueError("代码不能为空")
    import datetime as _dt

    conn = await _conn()
    await conn.execute(
        "INSERT INTO watchlist(user_id,symbol,name,kind,created_at) VALUES(?,?,?,?,?)"
        " ON CONFLICT(user_id,symbol) DO UPDATE SET name=excluded.name, kind=excluded.kind",
        (
            current_user_id(),
            sym,
            str(name).strip()[:40] or sym,
            str(kind).strip()[:10] or "股票",
            _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        ),
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "symbol": sym}


async def delete_watchlist(symbol: str) -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute(
        "DELETE FROM watchlist WHERE user_id=? AND symbol=?",
        (current_user_id(), symbol.strip().upper()),
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount}
