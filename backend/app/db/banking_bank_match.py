"""银行流水 · 匹配：与总账草稿/账户科目对账绑单与撤销绑定。"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from ..timeutil import now_str as _now
from ._core import _conn, fetch_all, fetch_one
from .banking_bank_query import bank_get
from .banking_payments import payment_get
from .db_write_txn import write_txn


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


def _within_days(left: str, right: str, window_days: int) -> bool:
    """只比较日期部分；解析失败按不匹配处理，绝不放过脏日期。"""
    try:
        return abs(
            (date.fromisoformat(str(left)[:10]) - date.fromisoformat(str(right)[:10])).days
        ) <= int(window_days)
    except ValueError:
        return False


async def bank_match_candidates(
    tenant_id: int,
    start_date: str,
    end_date: str,
    *,
    window_days: int = 3,
    limit: int = 100,
) -> dict[str, Any]:
    """列出账期内可唯一匹配的支出流水与付款。

    匹配条件是同租户、同银行账户、同金额、付款已付款，且日期相差不超过
    `window_days`。同一流水命中多笔付款、或同一付款命中多条流水时，
    整组视为歧义，不进入候选——宁可留给人工，也不猜。
    """
    window_days = max(0, int(window_days))
    limit = max(1, min(100, int(limit)))
    total_row = await fetch_one(
        "SELECT COUNT(*) AS n FROM bank_transactions"
        " WHERE tenant_id=? AND status='unmatched' AND direction='out'"
        " AND txn_date>=? AND txn_date<?",
        (int(tenant_id), str(start_date), str(end_date)),
    )
    total = int(total_row["n"]) if total_row else 0
    rows = await fetch_all(
        "SELECT b.id AS transaction_id,b.txn_date,b.amount_cents,b.counterparty,"
        "b.memo,b.bank_account_id,a.code AS bank_account_code,"
        "a.name AS bank_account_name,p.id AS payment_id,p.payment_no,p.payee,p.paid_at"
        " FROM bank_transactions b"
        " JOIN payments p ON p.tenant_id=b.tenant_id"
        " AND p.bank_account_id=b.bank_account_id"
        " AND p.amount_cents=b.amount_cents"
        " AND p.status='paid'"
        " JOIN gl_accounts a ON a.id=b.bank_account_id AND a.tenant_id=b.tenant_id"
        " WHERE b.tenant_id=? AND b.status='unmatched' AND b.direction='out'"
        " AND b.txn_date>=? AND b.txn_date<?"
        " AND p.paid_at<>''"
        " AND NOT EXISTS (SELECT 1 FROM bank_transactions x"
        "   WHERE x.tenant_id=b.tenant_id AND x.payment_id=p.id)"
        " ORDER BY b.txn_date,b.id,p.id",
        (int(tenant_id), str(start_date), str(end_date)),
    )
    by_txn: dict[int, list[Any]] = {}
    by_payment: dict[int, list[Any]] = {}
    for row in rows:
        try:
            if not _within_days(row["txn_date"], row["paid_at"], window_days):
                continue
        except (TypeError, ValueError):
            continue
        by_txn.setdefault(int(row["transaction_id"]), []).append(row)
        by_payment.setdefault(int(row["payment_id"]), []).append(row)

    unique = []
    ambiguous_txns: set[int] = set()
    for txn_id, candidates in by_txn.items():
        if len(candidates) != 1:
            ambiguous_txns.add(txn_id)
            continue
        row = candidates[0]
        if len(by_payment[int(row["payment_id"])]) != 1:
            ambiguous_txns.add(txn_id)
            continue
        unique.append(
            {
                "transaction_id": int(row["transaction_id"]),
                "txn_date": str(row["txn_date"]),
                "amount": round(int(row["amount_cents"]) / 100, 2),
                "amount_cents": int(row["amount_cents"]),
                "counterparty": str(row["counterparty"] or ""),
                "memo": str(row["memo"] or ""),
                "bank_account_id": int(row["bank_account_id"]),
                "bank_account_code": str(row["bank_account_code"] or ""),
                "bank_account_name": str(row["bank_account_name"] or ""),
                "payment_id": int(row["payment_id"]),
                "payment_no": str(row["payment_no"] or ""),
                "payee": str(row["payee"] or ""),
                "paid_at": str(row["paid_at"] or ""),
            }
        )
    return {
        "items": unique[:limit],
        "matched_total": len(unique),
        "pending": max(0, len(unique) - limit),
        "unmatched_total": total,
        "skipped": max(0, total - len(unique)),
        "ambiguous": len(ambiguous_txns),
        "window_days": window_days,
    }


async def bank_match_batch(
    tenant_id: int,
    pairs: list[dict[str, Any]],
    matched_by: int,
    *,
    window_days: int = 3,
) -> list[dict[str, Any]]:
    """单事务批量匹配；任何一笔不满足条件都整批回滚。"""
    if not pairs:
        return []
    if len(pairs) > 100:
        raise ValueError("单次最多匹配 100 笔流水")
    payment_ids = [int(item.get("payment_id") or 0) for item in pairs]
    if len(set(payment_ids)) != len(payment_ids):
        raise ValueError("同一付款不能重复匹配")
    now = _now()
    matched_ids: list[int] = []
    async with write_txn() as conn:
        for item in pairs:
            txn_id = int(item.get("transaction_id") or 0)
            payment_id = int(item.get("payment_id") or 0)
            row = await (
                await conn.execute(
                    "SELECT status,direction,amount_cents,bank_account_id,payment_id,txn_date"
                    " FROM bank_transactions WHERE tenant_id=? AND id=?",
                    (int(tenant_id), txn_id),
                )
            ).fetchone()
            if row is None:
                raise ValueError("银行流水不存在")
            if row["status"] != "unmatched" or row["direction"] != "out":
                raise ValueError("只有未匹配的支出流水可以批量匹配")
            if row["payment_id"] is not None:
                raise ValueError("流水已经匹配过付款")
            payment = await (
                await conn.execute(
                    "SELECT status,amount_cents,bank_account_id,paid_at"
                    " FROM payments WHERE tenant_id=? AND id=?",
                    (int(tenant_id), payment_id),
                )
            ).fetchone()
            if payment is None:
                raise ValueError("付款记录不存在")
            if payment["status"] != "paid":
                raise ValueError("只有已付款的记录可以匹配流水")
            if int(payment["amount_cents"]) != int(row["amount_cents"]):
                raise ValueError("流水金额与付款金额不一致")
            if int(payment["bank_account_id"]) != int(row["bank_account_id"]):
                raise ValueError("流水账户与付款账户不一致")
            if not _within_days(row["txn_date"], payment["paid_at"], window_days):
                raise ValueError("流水日期与付款日期相差超过窗口")
            existing = await (
                await conn.execute(
                    "SELECT id FROM bank_transactions"
                    " WHERE tenant_id=? AND payment_id=?",
                    (int(tenant_id), payment_id),
                )
            ).fetchone()
            if existing is not None:
                raise ValueError("该付款已经匹配过流水")
            cur = await conn.execute(
                "UPDATE bank_transactions SET status='matched',payment_id=?,"
                "matched_by=?,matched_at=?,updated_at=?"
                " WHERE tenant_id=? AND id=? AND status='unmatched'",
                (
                    payment_id,
                    int(matched_by),
                    now,
                    now,
                    int(tenant_id),
                    txn_id,
                ),
            )
            if not cur.rowcount:
                raise ValueError("流水已被处理")
            matched_ids.append(txn_id)
    return [
        item
        for txn_id in matched_ids
        if (item := await bank_get(int(tenant_id), txn_id)) is not None
    ]
