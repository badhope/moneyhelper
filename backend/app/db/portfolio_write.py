"""持仓写入口：新增/删除/追加/编辑，全部带撤销快照与事务。"""

from __future__ import annotations

import json
import math
from typing import Any

from ._core import (
    _conn,
    _mark_user_data,
    list_positions,
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


async def append_position(
    symbol: str,
    shares: float,
    cost: float,
    last: float | None = None,
    name: str | None = None,
) -> dict[str, Any] | None:
    """同一 symbol 追加买入：股数累加、成本加权平均（不覆盖）。

    返回合并后的持仓；symbol 不存在时返回 None，由调用方决定「报 404」还是
    「新建」（REST 追加接口要求先有持仓，MCP 的买入工具允许第一条就建立）。

    此前这段加权平均逻辑有两份：`routes/ledger.py` 的 /append 与
    `tools.py` 的 record_position。两份各自实现，改一处忘另一处就会出现
    「REST 追加按加权、MCP 追加按覆盖」的口径分裂，而两边用户看到的是
    同一张持仓表。
    """
    rows = await list_positions()
    cur = next((r for r in rows if r["symbol"] == symbol), None)
    if cur is None:
        return None

    add_shares = float(shares or 0)
    add_cost = float(cost or 0)
    if add_shares <= 0 or not math.isfinite(add_shares):
        raise ValueError("追加股数需大于 0")

    old_shares = float(cur.get("shares") or 0)
    old_cost = float(cur.get("cost") or 0)
    total = old_shares + add_shares
    avg_cost = (
        (old_shares * old_cost + add_shares * add_cost) / total if total > 0 else old_cost
    )
    # 现价只升不降：追加买入不应该把已知的市价往回拉低
    new_last = float(cur.get("last") or 0)
    if last is not None and float(last) > new_last:
        new_last = float(last)

    merged = {
        **cur,
        "shares": total,
        "cost": round(avg_cost, 6),
        "last": new_last,
    }
    if name:
        merged["name"] = name
    await update_position(merged, symbol)
    # update_position 只回 {"ok","symbol"}；调用方（MCP 文案 / REST 回执）需要
    # 合并后的股数与加权成本，这里把算好的值一起返回。
    return {**merged, "symbol": symbol}


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
