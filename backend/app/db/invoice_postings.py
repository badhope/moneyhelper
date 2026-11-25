"""发票批量入账：一张已确认发票生成一张已过账凭证。

设计口径：
- 发票仍是 `user_id` 维度的文件台账，凭证落到当前 `tenant_id` 的总账；
  两边都在同一事务里校验，避免跨主体入账。
- 只处理费用票：借费用、借进项税、贷应付账款。采购应付有自己的发票与
  付款流程，不从这里重复生成。
- 幂等由 `invoice_postings(user_id, invoice_id)` 唯一键保证；整批一个事务，
  任何一张金额变化、状态回退或重复入账都会让整批回滚。
"""

from __future__ import annotations

from typing import Any

from ..calculations.gl import to_cents
from ..timeutil import now_iso
from ._core import _conn, fetch_all, get_write_lock
from .gl_accounts import _open_period_for_date
from .gl_entries_validate import _validate_lines
from .gl_entries_write import _insert_entry_locked

INVOICE_POST_MAX = 100


async def invoice_posted_ids(user_id: int, invoice_ids: list[str]) -> set[str]:
    if not invoice_ids:
        return set()
    placeholders = ",".join("?" * len(invoice_ids))
    rows = await fetch_all(
        f"SELECT invoice_id FROM invoice_postings"
        f" WHERE user_id=? AND invoice_id IN ({placeholders})",
        (int(user_id), *invoice_ids),
    )
    return {str(row["invoice_id"]) for row in rows}


async def invoice_numbers_in_payables(
    tenant_id: int, invoice_numbers: list[str]
) -> set[str]:
    """采购应付已登记过的发票号：审批时会写总账，这里必须跳过，避免重复入账。"""
    wanted = [str(n or "").strip() for n in invoice_numbers if str(n or "").strip()]
    if not wanted:
        return set()
    placeholders = ",".join("?" * len(wanted))
    rows = await fetch_all(
        f"SELECT invoice_no FROM payables WHERE tenant_id=? AND invoice_no IN ({placeholders})",
        (int(tenant_id), *wanted),
    )
    return {str(row["invoice_no"]) for row in rows}


async def invoice_post_batch(
    tenant_id: int,
    user_id: int,
    items: list[dict[str, Any]],
    *,
    period: str,
) -> list[dict[str, Any]]:
    """把一批发票写成已过账凭证；整批原子，失败全部回滚。"""
    if not items:
        return []
    if len(items) > INVOICE_POST_MAX:
        raise ValueError(f"单批最多入账 {INVOICE_POST_MAX} 张发票")
    month = str(period or "").strip()
    if len(month) != 7 or month[4] != "-":
        raise ValueError("账期需为 YYYY-MM")

    prepared: list[dict[str, Any]] = []
    for item in items:
        invoice_id = str(item.get("invoice_id") or "")
        if not invoice_id:
            raise ValueError("发票 id 不能为空")
        entry_date = str(item.get("invoice_date") or "")[:10]
        if not entry_date.startswith(month):
            raise ValueError("发票日期不在当前账期")
        total_cents = to_cents(item.get("total_amount"))
        tax_cents = to_cents(item.get("tax_amount", 0))
        if total_cents <= 0 or tax_cents < 0 or tax_cents > total_cents:
            raise ValueError(f"发票 {invoice_id} 金额无效")
        debit_id = int(item.get("debit_account_id") or 0)
        tax_id = int(item.get("tax_account_id") or 0)
        credit_id = int(item.get("credit_account_id") or 0)
        if not debit_id or not credit_id:
            raise ValueError(f"发票 {invoice_id} 缺少入账科目")
        lines: list[dict[str, Any]] = []
        base_cents = total_cents - tax_cents
        memo = f"发票 {item.get('invoice_number') or invoice_id} {item.get('seller') or ''}".strip()
        if base_cents > 0:
            lines.append(
                {
                    "account_id": debit_id,
                    "debit": base_cents / 100,
                    "credit": 0,
                    "memo": f"{memo} 费用",
                }
            )
        if tax_cents > 0:
            if not tax_id:
                raise ValueError(f"发票 {invoice_id} 有税额但未配置进项税科目")
            lines.append(
                {
                    "account_id": tax_id,
                    "debit": tax_cents / 100,
                    "credit": 0,
                    "memo": f"{memo} 进项税",
                }
            )
        lines.append(
            {
                "account_id": credit_id,
                "debit": 0,
                "credit": total_cents / 100,
                "memo": f"{memo} 应付",
            }
        )
        normalized, _total = await _validate_lines(tenant_id, lines)
        prepared.append(
            {
                "invoice_id": invoice_id,
                "entry_date": entry_date,
                "total_cents": total_cents,
                "tax_cents": tax_cents,
                "normalized": normalized,
                "description": f"发票入账 {memo}"[:300],
            }
        )

    period_row = await _open_period_for_date(tenant_id, prepared[0]["entry_date"])
    period_id = int(period_row["id"])
    for item in prepared:
        if not item["entry_date"].startswith(month):
            raise ValueError("发票日期不在当前账期")

    written: list[dict[str, Any]] = []
    async with get_write_lock():
        conn = await _conn()
        await conn.execute("BEGIN IMMEDIATE")
        try:
            status_row = await (
                await conn.execute(
                    "SELECT status FROM gl_periods WHERE tenant_id=? AND id=?",
                    (int(tenant_id), period_id),
                )
            ).fetchone()
            if not status_row or str(status_row["status"]) != "open":
                raise ValueError("当前账期已关闭，不能入账")

            for item in prepared:
                row = await (
                    await conn.execute(
                        "SELECT id,status,invoice_date,total_amount,tax_amount,"
                        "invoice_number,seller FROM invoices"
                        " WHERE user_id=? AND id=?",
                        (int(user_id), item["invoice_id"]),
                    )
                ).fetchone()
                if row is None:
                    raise ValueError(f"发票 {item['invoice_id']} 不存在")
                if str(row["status"]) != "confirmed":
                    raise ValueError(
                        f"发票 {item['invoice_id']} 不是已确认状态"
                    )
                if str(row["invoice_date"])[:10] != item["entry_date"]:
                    raise ValueError(
                        f"发票 {item['invoice_id']} 日期已变化，请重新评估"
                    )
                total_now = to_cents(row["total_amount"])
                tax_now = to_cents(row["tax_amount"] or 0)
                if (
                    total_now != item["total_cents"]
                    or tax_now != item["tax_cents"]
                ):
                    raise ValueError(
                        f"发票 {item['invoice_id']} 金额已变化，请重新评估"
                    )
                existing = await (
                    await conn.execute(
                        "SELECT 1 FROM invoice_postings WHERE user_id=? AND invoice_id=?",
                        (int(user_id), item["invoice_id"]),
                    )
                ).fetchone()
                if existing:
                    raise ValueError(f"发票 {item['invoice_id']} 已入账，整批回滚")

                entry_id = await _insert_entry_locked(
                    conn,
                    tenant_id,
                    item["entry_date"],
                    period_id,
                    item["description"],
                    item["normalized"],
                    status="posted",
                    source="invoice",
                    created_by=user_id,
                )
                await conn.execute(
                    "INSERT INTO invoice_postings(user_id,invoice_id,tenant_id,entry_id,"
                    "period,amount_cents,tax_cents,created_at)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (
                        int(user_id),
                        item["invoice_id"],
                        int(tenant_id),
                        entry_id,
                        month,
                        item["total_cents"],
                        item["tax_cents"],
                        now_iso(),
                    ),
                )
                written.append(
                    {
                        "invoice_id": item["invoice_id"],
                        "entry_id": entry_id,
                        "amount": round(item["total_cents"] / 100, 2),
                        "tax": round(item["tax_cents"] / 100, 2),
                    }
                )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
    return written
