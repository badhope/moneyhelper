"""批量入账：一次写多笔流水，用于导入/自动记账。"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from ._core import (
    _ACTIVE_KEY,
    _active_member_id,
    _conn,
    _fetch_member,
    _mark_user_data,
    get_write_lock,
)
from .tenant import current_user_id
from .undo import _record_snapshot


async def add_transactions_batch(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """批量入账唯一事务入口（一句话多笔 / CSV 导入走这里）。

    全部条目先校验、后入账：任一条校验失败直接抛错，一条都不写；
    写入阶段单事务包裹（BEGIN...COMMIT），中途任何失败整体回滚——
    保证"多笔记账要么全成、要么全无"的真实原子性。
    entries 元素即 add_transaction 的关键字参数。
    """
    if not entries:
        return []
    # 阶段一：全部校验（不触碰数据库写入）
    cleaned: list[dict[str, Any]] = []
    for i, e in enumerate(entries):
        d = str(e.get("date", "")).strip()
        amt = float(e.get("amount", 0))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise ValueError(f"第 {i + 1} 条日期需为 YYYY-MM-DD：{d!r}") from None
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"第 {i + 1} 条不是有效日历日：{d!r}") from None
        if amt == 0 or not math.isfinite(amt):
            raise ValueError(f"第 {i + 1} 条金额不能为 0、NaN 或无穷")
        cleaned.append(
            {
                "date": d,
                "item": str(e.get("item", "")).strip()[:80] or "未命名",
                "category": str(e.get("category", "")).strip()[:20] or "其他",
                "amount": amt,
                "owner_id": e.get("owner_id"),
                "is_shared": e.get("is_shared"),
            }
        )

    # 阶段二：解析归属（校验通过后，写库前完成）
    for c in cleaned:
        if c["owner_id"] is None:
            active = _active_member_id.get(_ACTIVE_KEY)
            if active is not None:
                c["owner_id"] = active
        if c["is_shared"] is None and c["owner_id"] is not None:
            m = await _fetch_member(c["owner_id"])
            c["is_shared"] = bool(m and m.get("role") in ("owner", "admin"))
        if c["is_shared"] is None:
            c["is_shared"] = 1


    uid = current_user_id()
    conn = await _conn()
    results: list[dict[str, Any]] = []
    # 整库只有一条写连接，多语句事务必须排他：否则并发「确认」入账时
    # BEGIN 会抛 "cannot start a transaction within a transaction"，
    # 而用 SAVEPOINT 又会因共享连接上的同名 savepoint 互相干扰
    # （CI 实测："no such savepoint: add_tx_batch"）。用写锁串行化。
    async with get_write_lock():
        # autocommit 连接（isolation_level=None）下 commit/rollback 是空操作，
        # 必须显式开事务，否则「任一条失败整批回滚」的承诺是假的。
        # 已在事务中时改用 SAVEPOINT（SQLite 标准的嵌套写法）。
        nested = bool(conn.in_transaction)
        sp = "sp_batch_tx"
        if nested:
            await conn.execute(f"SAVEPOINT {sp}")
        else:
            await conn.execute("BEGIN IMMEDIATE")
        try:
            for c in cleaned:
                cur = await conn.execute(
                    "INSERT INTO transactions(user_id,date,item,category,amount,owner_id,is_shared)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (
                        uid,
                        c["date"],
                        c["item"],
                        c["category"],
                        c["amount"],
                        c["owner_id"],
                        1 if c["is_shared"] else 0,
                    ),
                )
                await _record_snapshot("transaction", str(cur.lastrowid), "{}")
                results.append({"ok": True, "id": cur.lastrowid})
            await _mark_user_data(conn)
            if nested:
                await conn.execute(f"RELEASE {sp}")
            else:
                await conn.execute("COMMIT")
            return results
        except Exception:
            if nested:
                await conn.execute(f"ROLLBACK TO {sp}")
                await conn.execute(f"RELEASE {sp}")
            else:
                await conn.execute("ROLLBACK")
            raise
