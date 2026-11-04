"""流水域：入账（单笔/批量原子）/改删/合并。"""
from __future__ import annotations

import math

import json
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
from .undo import _record_snapshot, _row_to_json


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
        if amt == 0 or amt != amt:
            raise ValueError(f"第 {i + 1} 条金额不能为 0 或 NaN")
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

    from .tenant import current_user_id

    uid = current_user_id()
    conn = await _conn()
    results: list[dict[str, Any]] = []
    # 整库只有一条写连接，多语句事务必须排他：否则并发「确认」入账时
    # BEGIN 会抛 "cannot start a transaction within a transaction"，
    # 而用 SAVEPOINT 又会因共享连接上的同名 savepoint 互相干扰
    # （CI 实测："no such savepoint: add_tx_batch"）。用写锁串行化。
    async with get_write_lock():
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
            await conn.commit()
            return results
        except Exception:
            await conn.rollback()
            raise


async def add_transaction(
    date: str,
    item: str,
    category: str,
    amount: float,
    owner_id: int | None = None,
    is_shared: bool | None = None,
) -> dict[str, Any]:
    """入账唯一入口：所有路径（手动 / 一句话记账 / CSV 导入）都必须经过这里。

    在此统一做真实日历校验与金额校验——`2026-13-99` 这类正则放行的
    脏日期会污染月度统计（趋势 / 预算 / 现金流），必须在写入前拦截。

    owner_id: 归属成员 id；未指定时尝试取当前活跃成员，无活跃成员则为 NULL（我的账本模式）
    is_shared: 是否共享；未指定时 owner 身份自动 1，viewer/member 默认 0（私有）
    """
    d = str(date).strip()
    amt = float(amount)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        raise ValueError(f"日期需为 YYYY-MM-DD：{d!r}") from None
    try:
        datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"日期不是有效日历日：{d!r}") from None
    # 拒绝 0 / NaN / ±Inf：SQLite 会把 Inf 原样存下，而 JSONResponse 用
    # allow_nan=False 序列化时抛 ValueError → 整个 dashboard/持仓接口持续 500，
    # 用户连打开列表删掉这条坏数据都做不到。
    if amt == 0 or not math.isfinite(amt):
        raise ValueError("金额必须是有限非零数字")

    # 解析 owner_id
    resolved_owner = owner_id
    if resolved_owner is None:
        active = _active_member_id.get(_ACTIVE_KEY)
        if active is not None:
            resolved_owner = active

    # 解析 is_shared
    resolved_shared = is_shared
    if resolved_shared is None and resolved_owner is not None:
        # 查成员角色：owner/admin 的流水自动共享
        m = await _fetch_member(resolved_owner)
        resolved_shared = bool(m and m.get("role") in ("owner", "admin"))
    if resolved_shared is None:
        resolved_shared = 1  # 默认值：无 owner 时保持向后兼容

    from .tenant import current_user_id

    conn = await _conn()
    cur = await conn.execute(
        "INSERT INTO transactions(user_id,date,item,category,amount,owner_id,is_shared)"
        " VALUES(?,?,?,?,?,?,?)",
        (
            current_user_id(),
            d,
            str(item).strip()[:80] or "未命名",
            str(category).strip()[:20] or "其他",
            amt,
            resolved_owner,
            1 if resolved_shared else 0,
        ),
    )
    # 撤销快照：新增前 before_json='{}'，撤回时按 entity_id(=id) 可以直接 DELETE 这条新流水
    await _record_snapshot("transaction", str(cur.lastrowid), "{}")
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "id": cur.lastrowid}


async def delete_transaction(tx_id: int) -> dict[str, Any]:
    conn = await _conn()
    # 撤销快照：记录删除前的全量旧行，撤回时 INSERT OR REPLACE 恢复
    old = await (
        await conn.execute(
            "SELECT * FROM transactions WHERE user_id=? AND id=?",
            (current_user_id(), int(tx_id)),
        )
    ).fetchone()
    if old is None:
        return {"ok": False, "deleted": 0}
    await _record_snapshot("transaction", str(tx_id), _row_to_json(old))
    cur = await conn.execute(
        "DELETE FROM transactions WHERE user_id=? AND id=?", (current_user_id(), int(tx_id))
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount}


async def update_transaction(
    tx_id: int,
    *,
    date: str | None = None,
    item: str | None = None,
    category: str | None = None,
    amount: float | None = None,
    owner_id: int | str | None = None,
    is_shared: bool | None = None,
) -> dict[str, Any]:
    """编辑一条流水。只传需要改的字段（None 表示不动），金额 0 / NaN 拒绝。"""

    conn = await _conn()
    cur = await conn.execute(
        "SELECT date,item,category,amount,owner_id,is_shared FROM transactions"
        " WHERE user_id=? AND id=?",
        (current_user_id(), int(tx_id)),
    )
    row = await cur.fetchone()
    if row is None:
        raise ValueError(f"流水 {tx_id} 不存在")
    old_date, old_item, old_cat, old_amt = (
        row["date"],
        row["item"],
        row["category"],
        row["amount"],
    )
    old_owner = row["owner_id"]
    old_shared = row["is_shared"]
    # 撤销快照：写入操作前的全量旧行（4 列），撤回时恢复
    await _record_snapshot(
        "transaction",
        str(tx_id),
        json.dumps(
            {
                "id": int(tx_id),
                "date": old_date,
                "item": old_item,
                "category": old_cat,
                "amount": old_amt,
                "owner_id": old_owner,
                "is_shared": old_shared,
            },
            ensure_ascii=False,
        ),
    )

    d = str(date).strip() if date is not None else old_date
    it = str(item).strip()[:80] if item is not None else old_item
    cat = (str(category).strip()[:20] or "其他") if category is not None else old_cat
    amt = float(amount) if amount is not None else old_amt
    own = int(owner_id) if owner_id is not None and owner_id != "" else old_owner
    shr = (1 if is_shared else 0) if is_shared is not None else old_shared

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        raise ValueError(f"日期需为 YYYY-MM-DD：{d!r}")
    try:
        datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"日期不是有效日历日：{d!r}") from None
    if not it:
        it = "未命名"
    if amt == 0 or amt != amt:
        raise ValueError("金额不能为 0 或 NaN")

    await conn.execute(
        "UPDATE transactions SET date=?,item=?,category=?,amount=?,owner_id=?,is_shared=?"
        " WHERE user_id=? AND id=?",
        (d, it, cat, amt, own, shr, current_user_id(), int(tx_id)),
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "id": int(tx_id)}


async def merge_transactions(
    month: str,
    category: str | None = None,
) -> dict[str, Any]:
    """合并同类流水：把指定月份（可选指定分类）下所有流水，按 (date,item,category) 求和合并成一组，
    保留每组最早一条，删其余。返回合并掉的条数。
    """
    m = str(month).strip()
    if not re.fullmatch(r"\d{4}-\d{2}", m):
        raise ValueError("月份需为 YYYY-MM")
    cat = str(category).strip() if category else None

    conn = await _conn()
    if cat:
        cur = await conn.execute(
            "SELECT date,item,category,amount FROM transactions"
            " WHERE user_id=? AND date >= ? AND date < ? AND category=?"
            " ORDER BY date,item",
            (current_user_id(), f"{month}-01", f"{month}-32", cat),
        )
    else:
        cur = await conn.execute(
            "SELECT date,item,category,amount FROM transactions"
            " WHERE user_id=? AND date >= ? AND date < ? ORDER BY date,item,category",
            (current_user_id(), f"{month}-01", f"{month}-32"),
        )
    rows = [
        {"date": r[0], "item": r[1], "category": r[2], "amount": r[3]}
        for r in (await cur.fetchall())
    ]

    # 按 (date, item, category) 分组求和
    groups: dict[tuple[str, str, str], float] = {}
    group_order: list[tuple[str, str, str]] = []
    for r in rows:
        key = (r["date"], r["item"], r["category"])
        if key not in groups:
            groups[key] = 0.0
            group_order.append(key)
        groups[key] += r["amount"]

    merged = 0
    for key, total in groups.items():
        d, it, cat_ = key
        # 找该组最早那条，更新金额为合计
        cur2 = await conn.execute(
            "SELECT id FROM transactions WHERE user_id=? AND date=? AND item=?"
            " AND category=? LIMIT 1",
            (current_user_id(), d, it, cat_),
        )
        first_id = (await cur2.fetchone())[0]
        if total == 0 or total != total:
            # 合计为 0 或 NaN → 整组删掉
            await conn.execute(
                "DELETE FROM transactions WHERE user_id=? AND date=? AND item=?"
                " AND category=?",
                (current_user_id(), d, it, cat_),
            )
            merged += 1
            continue
        await conn.execute(
            "UPDATE transactions SET amount=? WHERE user_id=? AND id=?",
            (total, current_user_id(), first_id),
        )
        # 删该组除最早外的其余记录
        cur3 = await conn.execute(
            "DELETE FROM transactions WHERE user_id=? AND date=? AND item=?"
            " AND category=? AND id<>?",
            (current_user_id(), d, it, cat_, first_id),
        )
        merged += cur3.rowcount

    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "merged": merged}
