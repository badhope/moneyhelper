"""同类流水合并：按 (date,item,category) 求和，保留最早一条。"""

from __future__ import annotations

import re
from typing import Any

from ._core import (
    _mark_user_data,
)
from .tenant import current_user_id


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

    from ._core import write_txn

    async with write_txn() as conn:
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
        return {"ok": True, "merged": merged}
