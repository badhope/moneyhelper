"""单笔流水增删改：金额/分类校验与回滚快照。"""

from __future__ import annotations

import json
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
)
from .tenant import current_user_id
from .undo import _record_snapshot, _row_to_json


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
    if amt == 0 or not math.isfinite(amt):
        raise ValueError("金额不能为 0、NaN 或无穷")

    await conn.execute(
        "UPDATE transactions SET date=?,item=?,category=?,amount=?,owner_id=?,is_shared=?"
        " WHERE user_id=? AND id=?",
        (d, it, cat, amt, own, shr, current_user_id(), int(tx_id)),
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "id": int(tx_id)}
