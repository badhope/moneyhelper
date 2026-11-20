"""应付审批与付款：审批通过即生成总账分录，付款核销。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from ..money import yuan_str as _yuan_str
from ..timeutil import now_str as _now
from ._core import _conn, get_write_lock
from .gl import gl_create_entry, gl_delete_draft_entry, gl_get_account
from .procurement_payable_query import _assert_payable_accounts, payable_get


async def payable_submit(tenant_id: int, payable_id: int) -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE payables SET status='submitted',updated_at=?"
        " WHERE tenant_id=? AND id=? AND status='draft'",
        (_now(), int(tenant_id), int(payable_id)),
    )
    await conn.commit()
    if not cur.rowcount:
        raise ValueError("只有草稿应付单可以提交")
    payable = await payable_get(tenant_id, payable_id)
    assert payable is not None
    return payable


async def payable_approve(
    tenant_id: int, payable_id: int, approved_by: int
) -> dict[str, Any]:
    payable = await payable_get(tenant_id, payable_id)
    if payable is None:
        raise ValueError("应付单不存在")
    if payable["status"] != "submitted":
        raise ValueError("只有已提交应付单可以审核")
    await _assert_payable_accounts(
        tenant_id,
        int(payable["expense_account_id"]),
        int(payable["payable_account_id"]),
    )
    # 抢占式状态：避免两个审批人同时通过、重复生成凭证。
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE payables SET status='approving',updated_at=?"
        " WHERE tenant_id=? AND id=? AND status='submitted'",
        (_now(), int(tenant_id), int(payable_id)),
    )
    await conn.commit()
    if not cur.rowcount:
        raise ValueError("应付单已被处理")

    amount = _yuan_str(payable['amount_cents'])
    try:
        entry = await gl_create_entry(
            tenant_id,
            str(payable["invoice_date"]),
            f"应付 {payable['payable_no']} {payable['vendor_name'] or ''}".strip(),
            [
                {
                    "account_id": int(payable["expense_account_id"]),
                    "debit": amount,
                    "credit": 0,
                    "memo": payable["invoice_no"] or "采购应付",
                },
                {
                    "account_id": int(payable["payable_account_id"]),
                    "debit": 0,
                    "credit": amount,
                    "memo": payable["vendor_name"] or "",
                },
            ],
            approved_by,
        )
    except Exception:
        await conn.execute(
            "UPDATE payables SET status='submitted',updated_at=?"
            " WHERE tenant_id=? AND id=?",
            (_now(), int(tenant_id), int(payable_id)),
        )
        await conn.commit()
        raise

    try:
        await conn.execute(
            "UPDATE payables SET status='approved',approved_by=?,approved_at=?,"
            "gl_entry_id=?,updated_at=? WHERE tenant_id=? AND id=?",
            (
                int(approved_by),
                _now(),
                int(entry["id"]),
                _now(),
                int(tenant_id),
                int(payable_id),
            ),
        )
        await conn.commit()
    except BaseException:
        await conn.execute(
            "UPDATE payables SET status='submitted',updated_at=?"
            " WHERE tenant_id=? AND id=?",
            (_now(), int(tenant_id), int(payable_id)),
        )
        await conn.commit()
        try:
            await gl_delete_draft_entry(tenant_id, int(entry["id"]))
        except Exception:  # noqa: BLE001
            pass
        raise
    approved = await payable_get(tenant_id, payable_id)
    assert approved is not None
    return approved


async def payable_pay(
    tenant_id: int,
    payable_id: int,
    bank_account_id: int,
    created_by: int,
    note: str = "",
) -> dict[str, Any]:
    payable = await payable_get(tenant_id, payable_id)
    if payable is None:
        raise ValueError("应付单不存在")
    if payable["status"] != "approved":
        raise ValueError("只有已审核应付单可以付款")
    if payable["payment_id"]:
        raise ValueError("该应付单已经付款")
    bank = await gl_get_account(tenant_id, bank_account_id)
    if bank is None or not bank["is_active"] or bank["type"] != "asset":
        raise ValueError("付款账户必须是启用的资产类科目")
    amount = _yuan_str(payable['amount_cents'])
    entry = await gl_create_entry(
        tenant_id,
        datetime.now().date().isoformat(),
        f"付款 {payable['payable_no']} {payable['vendor_name'] or ''}".strip(),
        [
            {
                "account_id": int(payable["payable_account_id"]),
                "debit": amount,
                "credit": 0,
                "memo": "应付付款",
            },
            {
                "account_id": int(bank_account_id),
                "debit": 0,
                "credit": amount,
                "memo": "",
            },
        ],
        created_by,
    )
    month = datetime.now().strftime("%Y%m")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            row = await (
                await conn.execute(
                    "SELECT COUNT(*) AS n FROM payments WHERE tenant_id=? AND payment_no LIKE ?",
                    (int(tenant_id), f"PAY-{month}-%"),
                )
            ).fetchone()
            seq = int(row["n"]) + 1 if row else 1
            payment_no = f"PAY-{month}-{seq:04d}"
            cur = await conn.execute(
                "INSERT INTO payments(tenant_id,payment_no,claim_id,payable_id,amount_cents,"
                "payee,bank_account_id,method,status,paid_at,gl_entry_id,created_by,note,"
                "created_at,updated_at) VALUES(?,?,0,?,?,?,?, 'bank','paid',?,?,?,?,?,?)",
                (
                    int(tenant_id),
                    payment_no,
                    int(payable_id),
                    int(payable["amount_cents"]),
                    str(payable["vendor_name"] or payable["payable_no"])[:120],
                    int(bank_account_id),
                    _now(),
                    int(entry["id"]),
                    int(created_by),
                    str(note or "")[:300],
                    _now(),
                    _now(),
                ),
            )
            payment_id = int(cur.lastrowid)
            await conn.execute(
                "UPDATE payables SET status='paid',payment_id=?,updated_at=?"
                " WHERE tenant_id=? AND id=?",
                (payment_id, _now(), int(tenant_id), int(payable_id)),
            )
            await conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            await conn.execute("ROLLBACK")
            try:
                await gl_delete_draft_entry(tenant_id, int(entry["id"]))
            except Exception:  # noqa: BLE001
                pass
            raise ValueError("该应付单已经付款") from exc
        except BaseException:
            await conn.execute("ROLLBACK")
            try:
                await gl_delete_draft_entry(tenant_id, int(entry["id"]))
            except Exception:  # noqa: BLE001
                pass
            raise
    paid = await payable_get(tenant_id, payable_id)
    assert paid is not None
    return paid
