"""银行流水 · 匹配：与总账草稿/账户科目对账绑单与撤销绑定。"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..timeutil import now_str as _now
from ._core import _conn, fetch_one
from .banking_bank_query import bank_get
from .banking_payments import payment_get


async def bank_match(
    tenant_id: int, txn_id: int, payment_id: int, matched_by: int
) -> dict[str, Any]:
    txn = await bank_get(tenant_id, txn_id)
    if txn is None:
        raise ValueError("银行流水不存在")
    if txn["status"] != "unmatched":
        raise ValueError("只有未匹配流水可以匹配")
    payment = await payment_get(tenant_id, payment_id)
    if payment is None:
        raise ValueError("付款记录不存在")
    if txn["direction"] != "out":
        raise ValueError("只有支出流水可以匹配付款")
    if int(txn["amount_cents"]) != int(payment["amount_cents"]):
        raise ValueError("流水金额与付款金额不一致")
    if int(txn["bank_account_id"]) != int(payment["bank_account_id"]):
        raise ValueError("流水账户与付款账户不一致")
    existing = await fetch_one(
        "SELECT id FROM bank_transactions WHERE tenant_id=? AND payment_id=?",
        (int(tenant_id), int(payment_id)),
    )
    if existing is not None:
        raise ValueError("该付款已经匹配过流水")
    conn = await _conn()
    try:
        cur = await conn.execute(
            "UPDATE bank_transactions SET status='matched',payment_id=?,matched_by=?,"
            "matched_at=?,updated_at=? WHERE tenant_id=? AND id=? AND status='unmatched'",
            (
                int(payment_id),
                int(matched_by),
                _now(),
                _now(),
                int(tenant_id),
                int(txn_id),
            ),
        )
        await conn.commit()
    except sqlite3.IntegrityError as exc:
        # 连接是 autocommit：失败的 UPDATE 本身不会落地，无需再发 ROLLBACK
        # （无活动事务时 ROLLBACK 会抛 OperationalError，把真正的冲突原因盖掉）。
        raise ValueError("该付款已经匹配过流水") from exc
    if not cur.rowcount:
        raise ValueError("流水已被处理")
    matched = await bank_get(tenant_id, txn_id)
    assert matched is not None
    return matched


async def bank_unmatch(tenant_id: int, txn_id: int) -> dict[str, Any]:
    txn = await bank_get(tenant_id, txn_id)
    if txn is None:
        raise ValueError("银行流水不存在")
    if txn["status"] != "matched":
        raise ValueError("只有已匹配流水可以取消匹配")
    conn = await _conn()
    await conn.execute(
        "UPDATE bank_transactions SET status='unmatched',payment_id=NULL,matched_by=NULL,"
        "matched_at='',updated_at=? WHERE tenant_id=? AND id=? AND status='matched'",
        (_now(), int(tenant_id), int(txn_id)),
    )
    await conn.commit()
    updated = await bank_get(tenant_id, txn_id)
    assert updated is not None
    return updated
