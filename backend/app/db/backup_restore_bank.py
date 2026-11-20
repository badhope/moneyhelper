"""备份恢复·银行域：银行流水与银行对账（重映射付款/科目/期间）。"""

from __future__ import annotations

from typing import Any

import aiosqlite


async def _restore_bank_transactions(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    payment_map: dict[int, int],
    account_map: dict[int, int],
) -> dict[str, int]:
    raw = data.get("bank_transactions") or []
    if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
        raise ValueError("bank_transactions 备份格式不正确")
    await conn.execute(
        "DELETE FROM bank_transactions WHERE tenant_id=?", (int(tenant_id),)
    )
    for b in raw:
        account_id = account_map.get(int(b.get("bank_account_id") or 0))
        if account_id is None:
            raise ValueError("银行流水关联的银行科目引用缺失")
        old_payment = b.get("payment_id")
        new_payment = None
        if old_payment is not None:
            new_payment = payment_map.get(int(old_payment))
            if new_payment is None:
                raise ValueError("银行流水关联的付款引用缺失")
        await conn.execute(
            "INSERT INTO bank_transactions(tenant_id,bank_account_id,txn_date,direction,"
            "amount_cents,counterparty,memo,bank_ref,status,payment_id,matched_by,"
            "matched_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                account_id,
                str(b.get("txn_date") or ""),
                str(b.get("direction") or ""),
                int(b.get("amount_cents") or 0),
                str(b.get("counterparty") or ""),
                str(b.get("memo") or ""),
                str(b.get("bank_ref") or ""),
                str(b.get("status") or "unmatched"),
                new_payment,
                b.get("matched_by"),
                str(b.get("matched_at") or ""),
                str(b.get("created_at") or ""),
                str(b.get("updated_at") or ""),
            ),
        )
    return {"bank_transactions": len(raw)}

async def _restore_bank_reconciliations(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    account_map: dict[int, int],
    period_map: dict[int, int],
) -> dict[str, int]:
    raw = data.get("bank_reconciliations") or []
    if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
        raise ValueError("bank_reconciliations 备份格式不正确")
    await conn.execute(
        "DELETE FROM bank_reconciliations WHERE tenant_id=?", (int(tenant_id),)
    )
    for r in raw:
        account_id = account_map.get(int(r.get("bank_account_id") or 0))
        period_id = period_map.get(int(r.get("period_id") or 0))
        if account_id is None or period_id is None:
            raise ValueError("对账记录的账户或期间引用缺失")
        await conn.execute(
            "INSERT INTO bank_reconciliations(tenant_id,bank_account_id,period_id,"
            "statement_balance_cents,book_balance_cents,difference_cents,status,note,"
            "created_by,created_at,closed_by,closed_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                account_id,
                period_id,
                int(r.get("statement_balance_cents") or 0),
                int(r.get("book_balance_cents") or 0),
                int(r.get("difference_cents") or 0),
                str(r.get("status") or "open"),
                str(r.get("note") or ""),
                r.get("created_by"),
                str(r.get("created_at") or ""),
                r.get("closed_by"),
                str(r.get("closed_at") or ""),
            ),
        )
    return {"bank_reconciliations": len(raw)}
