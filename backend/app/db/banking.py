"""付款与银行流水（切片 6）。

付款是出纳执行记录，不重复生成总账凭证（报销审批时已生成）。
银行流水按 tenant/bank_account 隔离，金额存整数分；匹配只允许同账户、
同金额、方向为支出的未匹配流水，且一张付款最多匹配一条流水。
"""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import date, datetime
from typing import Any

from ..calculations.gl import to_cents
from ._core import _conn, fetch_all, fetch_one, get_write_lock
from .expenses import expense_get_claim
from .gl import gl_get_account

_PAYMENT_SELECT = (
    "SELECT p.id,p.tenant_id,p.payment_no,p.claim_id,p.payable_id,p.amount_cents,p.payee,"
    "p.bank_account_id,p.method,p.status,p.paid_at,p.gl_entry_id,p.created_by,p.note,"
    "p.created_at,p.updated_at,c.claim_no,c.title AS claim_title,"
    "c.status AS claim_status,ap.payable_no,ap.invoice_no,"
    "ge.entry_no AS gl_entry_no,ge.status AS gl_status,"
    "a.code AS bank_account_code,a.name AS bank_account_name"
    " FROM payments p"
    " LEFT JOIN expense_claims c ON c.id=p.claim_id AND c.tenant_id=p.tenant_id"
    " LEFT JOIN payables ap ON ap.id=p.payable_id AND ap.tenant_id=p.tenant_id"
    " LEFT JOIN gl_entries ge ON ge.id=p.gl_entry_id AND ge.tenant_id=p.tenant_id"
    " LEFT JOIN gl_accounts a ON a.id=p.bank_account_id AND a.tenant_id=p.tenant_id"
)

_BANK_SELECT = (
    "SELECT b.id,b.tenant_id,b.bank_account_id,b.txn_date,b.direction,b.amount_cents,"
    "b.counterparty,b.memo,b.bank_ref,b.status,b.payment_id,b.matched_by,b.matched_at,"
    "b.created_at,b.updated_at,p.payment_no,a.code AS bank_account_code,"
    "a.name AS bank_account_name"
    " FROM bank_transactions b"
    " LEFT JOIN payments p ON p.id=b.payment_id AND p.tenant_id=b.tenant_id"
    " LEFT JOIN gl_accounts a ON a.id=b.bank_account_id AND a.tenant_id=b.tenant_id"
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _money(row: Any, key: str = "amount_cents") -> dict[str, Any]:
    data = dict(row)
    data["amount"] = round(int(data.get(key) or 0) / 100, 2)
    return data


def _payment(row: Any) -> dict[str, Any]:
    return _money(row)


def _bank(row: Any) -> dict[str, Any]:
    return _money(row)


async def payment_get(tenant_id: int, payment_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        _PAYMENT_SELECT + " WHERE p.tenant_id=? AND p.id=?",
        (int(tenant_id), int(payment_id)),
    )
    return _payment(row) if row is not None else None


async def payment_list(tenant_id: int) -> list[dict[str, Any]]:
    return [
        _payment(r)
        for r in await fetch_all(
            _PAYMENT_SELECT + " WHERE p.tenant_id=? ORDER BY p.id DESC LIMIT 500",
            (int(tenant_id),),
        )
    ]


async def payment_create(
    tenant_id: int,
    claim_id: int,
    bank_account_id: int,
    created_by: int,
    note: str = "",
) -> dict[str, Any]:
    claim = await expense_get_claim(tenant_id, claim_id)
    if claim is None:
        raise ValueError("报销单不存在")
    if claim["status"] != "approved":
        raise ValueError("只有已通过的报销单可以付款")
    account = await gl_get_account(tenant_id, bank_account_id)
    if account is None or not account["is_active"] or account["type"] != "asset":
        raise ValueError("付款账户必须是启用的资产类科目")
    existing = await fetch_one(
        "SELECT id FROM payments WHERE tenant_id=? AND claim_id=?",
        (int(tenant_id), int(claim_id)),
    )
    if existing is not None:
        raise ValueError("该报销单已经登记过付款")
    now = _now()
    month = datetime.now().strftime("%Y%m")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            row = await (
                await conn.execute(
                    "SELECT COUNT(*) AS n FROM payments"
                    " WHERE tenant_id=? AND payment_no LIKE ?",
                    (int(tenant_id), f"PAY-{month}-%"),
                )
            ).fetchone()
            seq = int(row["n"]) + 1 if row else 1
            payment_no = f"PAY-{month}-{seq:04d}"
            cur = await conn.execute(
                "INSERT INTO payments(tenant_id,payment_no,claim_id,amount_cents,payee,"
                "bank_account_id,method,status,paid_at,created_by,note,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?, 'bank','paid',?,?,?,?,?)",
                (
                    int(tenant_id),
                    payment_no,
                    int(claim_id),
                    int(claim["amount_cents"]),
                    str(claim.get("applicant_name") or claim["title"])[:120],
                    int(bank_account_id),
                    now,
                    int(created_by),
                    str(note or "")[:300],
                    now,
                    now,
                ),
            )
            payment_id = int(cur.lastrowid)
            await conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            await conn.execute("ROLLBACK")
            raise ValueError("付款单号或报销单已被占用") from exc
        except BaseException:
            await conn.execute("ROLLBACK")
            raise
    created = await payment_get(tenant_id, payment_id)
    assert created is not None
    return created


async def bank_get(tenant_id: int, txn_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        _BANK_SELECT + " WHERE b.tenant_id=? AND b.id=?",
        (int(tenant_id), int(txn_id)),
    )
    return _bank(row) if row is not None else None


async def bank_list(
    tenant_id: int,
    status: str | None = None,
    bank_account_id: int | None = None,
) -> list[dict[str, Any]]:
    sql = _BANK_SELECT + " WHERE b.tenant_id=?"
    params: list[Any] = [int(tenant_id)]
    if status:
        sql += " AND b.status=?"
        params.append(str(status))
    if bank_account_id is not None:
        sql += " AND b.bank_account_id=?"
        params.append(int(bank_account_id))
    sql += " ORDER BY b.txn_date DESC,b.id DESC LIMIT 500"
    return [_bank(r) for r in await fetch_all(sql, tuple(params))]


async def _assert_bank_account(tenant_id: int, account_id: int) -> dict[str, Any]:
    account = await gl_get_account(tenant_id, account_id)
    if account is None or not account["is_active"] or account["type"] != "asset":
        raise ValueError("银行账户必须是启用的资产类科目")
    return account


async def bank_create(
    tenant_id: int,
    bank_account_id: int,
    txn_date: str,
    direction: str,
    amount: Any,
    counterparty: str = "",
    memo: str = "",
    bank_ref: str = "",
) -> dict[str, Any]:
    await _assert_bank_account(tenant_id, bank_account_id)
    try:
        d = date.fromisoformat(str(txn_date or "").strip())
    except ValueError:
        raise ValueError("交易日期需为 YYYY-MM-DD") from None
    if direction not in ("in", "out"):
        raise ValueError("direction 只能是 in / out")
    amount_cents = to_cents(amount)
    if amount_cents <= 0:
        raise ValueError("交易金额必须大于 0")
    conn = await _conn()
    cur = await conn.execute(
        "INSERT INTO bank_transactions(tenant_id,bank_account_id,txn_date,direction,"
        "amount_cents,counterparty,memo,bank_ref,status,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,'unmatched',?,?)",
        (
            int(tenant_id),
            int(bank_account_id),
            d.isoformat(),
            direction,
            amount_cents,
            str(counterparty or "")[:120],
            str(memo or "")[:200],
            str(bank_ref or "")[:120],
            _now(),
            _now(),
        ),
    )
    await conn.commit()
    created = await bank_get(tenant_id, int(cur.lastrowid))
    assert created is not None
    return created


def _parse_csv_rows(csv_text: str) -> list[dict[str, Any]]:
    text = str(csv_text or "").lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV 缺少表头")
    field_map = {str(x).strip().lower(): x for x in reader.fieldnames if x}
    required = {"date", "amount"}
    if not required.issubset(field_map):
        raise ValueError("CSV 至少需要 date,amount 两列")
    out: list[dict[str, Any]] = []
    for idx, raw in enumerate(reader, 2):
        def get(name: str, row: dict[str, Any] = raw) -> str:
            key = field_map.get(name)
            return str(row.get(key) or "").strip() if key else ""

        amount_text = get("amount")
        if not amount_text:
            raise ValueError(f"第 {idx} 行金额为空")
        negative = amount_text.startswith("-")
        amount_abs = amount_text.lstrip("+-")
        amount_cents = to_cents(amount_abs)
        if amount_cents <= 0:
            raise ValueError(f"第 {idx} 行金额必须大于 0")
        direction = get("direction").lower()
        if direction not in ("in", "out"):
            direction = "out" if negative else "in"
        try:
            d = date.fromisoformat(get("date"))
        except ValueError:
            raise ValueError(f"第 {idx} 行日期需为 YYYY-MM-DD") from None
        out.append(
            {
                "txn_date": d.isoformat(),
                "direction": direction,
                "amount_cents": amount_cents,
                "counterparty": get("counterparty")[:120],
                "memo": get("memo")[:200],
                "bank_ref": get("ref")[:120],
            }
        )
    return out


async def bank_import_csv(
    tenant_id: int, bank_account_id: int, csv_text: str
) -> dict[str, Any]:
    await _assert_bank_account(tenant_id, bank_account_id)
    rows = _parse_csv_rows(csv_text)
    if not rows:
        raise ValueError("CSV 没有数据行")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            await conn.executemany(
                "INSERT INTO bank_transactions(tenant_id,bank_account_id,txn_date,direction,"
                "amount_cents,counterparty,memo,bank_ref,status,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,'unmatched',?,?)",
                [
                    (
                        int(tenant_id),
                        int(bank_account_id),
                        r["txn_date"],
                        r["direction"],
                        int(r["amount_cents"]),
                        r["counterparty"],
                        r["memo"],
                        r["bank_ref"],
                        _now(),
                        _now(),
                    )
                    for r in rows
                ],
            )
            await conn.execute("COMMIT")
        except BaseException:
            await conn.execute("ROLLBACK")
            raise
    return {"imported": len(rows)}


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
        await conn.execute("ROLLBACK")
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


_RECON_SELECT = (
    "SELECT r.id,r.tenant_id,r.bank_account_id,r.period_id,"
    "r.statement_balance_cents,r.book_balance_cents,r.difference_cents,"
    "r.status,r.note,r.created_by,r.created_at,r.closed_by,r.closed_at,"
    "a.code AS bank_account_code,a.name AS bank_account_name,"
    "p.year,p.month,p.start_date,p.end_date,p.status AS period_status"
    " FROM bank_reconciliations r"
    " LEFT JOIN gl_accounts a ON a.id=r.bank_account_id AND a.tenant_id=r.tenant_id"
    " LEFT JOIN gl_periods p ON p.id=r.period_id AND p.tenant_id=r.tenant_id"
)


def _recon(row: Any) -> dict[str, Any]:
    data = dict(row)
    for key in ("statement_balance_cents", "book_balance_cents", "difference_cents"):
        data[key.replace("_cents", "")] = round(int(data.get(key) or 0) / 100, 2)
    return data


async def reconciliation_get(tenant_id: int, recon_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        _RECON_SELECT + " WHERE r.tenant_id=? AND r.id=?",
        (int(tenant_id), int(recon_id)),
    )
    return _recon(row) if row is not None else None


async def reconciliation_list(tenant_id: int) -> list[dict[str, Any]]:
    return [
        _recon(r)
        for r in await fetch_all(
            _RECON_SELECT + " WHERE r.tenant_id=? ORDER BY r.id DESC LIMIT 200",
            (int(tenant_id),),
        )
    ]


async def _book_balance_cents(
    tenant_id: int, bank_account_id: int, end_date: str
) -> int:
    row = await fetch_one(
        "SELECT COALESCE(SUM(l.debit_cents-l.credit_cents),0) AS bal"
        " FROM gl_entry_lines l"
        " JOIN gl_entries e ON e.id=l.entry_id AND e.tenant_id=l.tenant_id"
        " WHERE l.tenant_id=? AND l.account_id=? AND e.status='posted'"
        " AND e.entry_date<=?",
        (int(tenant_id), int(bank_account_id), str(end_date)),
    )
    return int(row["bal"]) if row is not None else 0


async def _unmatched_bank_count(
    tenant_id: int, bank_account_id: int, start_date: str, end_date: str
) -> int:
    row = await fetch_one(
        "SELECT COUNT(*) AS n FROM bank_transactions"
        " WHERE tenant_id=? AND bank_account_id=? AND status='unmatched'"
        " AND txn_date>=? AND txn_date<=?",
        (int(tenant_id), int(bank_account_id), str(start_date), str(end_date)),
    )
    return int(row["n"]) if row is not None else 0


async def reconciliation_create(
    tenant_id: int,
    bank_account_id: int,
    period_id: int,
    statement_balance: Any,
    created_by: int,
    note: str = "",
) -> dict[str, Any]:
    await _assert_bank_account(tenant_id, bank_account_id)
    from .gl import gl_get_period

    period = await gl_get_period(tenant_id, period_id)
    if period is None:
        raise ValueError("会计期间不存在")
    statement_cents = to_cents(statement_balance)
    book_cents = await _book_balance_cents(
        tenant_id, bank_account_id, period["end_date"]
    )
    difference = statement_cents - book_cents
    existing = await fetch_one(
        "SELECT id,status FROM bank_reconciliations"
        " WHERE tenant_id=? AND bank_account_id=? AND period_id=?",
        (int(tenant_id), int(bank_account_id), int(period_id)),
    )
    now = _now()
    conn = await _conn()
    if existing is not None:
        if str(existing["status"]) != "open":
            raise ValueError("该账户本期已签核，不能修改")
        await conn.execute(
            "UPDATE bank_reconciliations SET statement_balance_cents=?,"
            "book_balance_cents=?,difference_cents=?,note=?,created_by=?"
            " WHERE tenant_id=? AND id=?",
            (
                statement_cents,
                book_cents,
                difference,
                str(note or "")[:300],
                int(created_by),
                int(tenant_id),
                int(existing["id"]),
            ),
        )
        await conn.commit()
        created = await reconciliation_get(tenant_id, int(existing["id"]))
        assert created is not None
        return created
    cur = await conn.execute(
        "INSERT INTO bank_reconciliations(tenant_id,bank_account_id,period_id,"
        "statement_balance_cents,book_balance_cents,difference_cents,status,note,"
        "created_by,created_at) VALUES(?,?,?,?,?,?, 'open',?,?,?)",
        (
            int(tenant_id),
            int(bank_account_id),
            int(period_id),
            statement_cents,
            book_cents,
            difference,
            str(note or "")[:300],
            int(created_by),
            now,
        ),
    )
    await conn.commit()
    created = await reconciliation_get(tenant_id, int(cur.lastrowid))
    assert created is not None
    return created


async def reconciliation_close(
    tenant_id: int, recon_id: int, closed_by: int
) -> dict[str, Any]:
    recon = await reconciliation_get(tenant_id, recon_id)
    if recon is None:
        raise ValueError("对账记录不存在")
    if recon["status"] != "open":
        return recon
    period = {
        "start_date": recon["start_date"],
        "end_date": recon["end_date"],
    }
    book_cents = await _book_balance_cents(
        tenant_id, int(recon["bank_account_id"]), period["end_date"]
    )
    statement_cents = int(recon["statement_balance_cents"])
    difference = statement_cents - book_cents
    if difference != 0:
        raise ValueError(
            f"账面与对账单差额 {difference / 100:.2f} 元，先通过总账调整凭证后再签核"
        )
    unmatched = await _unmatched_bank_count(
        tenant_id,
        int(recon["bank_account_id"]),
        period["start_date"],
        period["end_date"],
    )
    if unmatched > 0:
        raise ValueError(f"本期仍有 {unmatched} 条未匹配流水，先完成匹配")
    conn = await _conn()
    await conn.execute(
        "UPDATE bank_reconciliations SET status='closed',book_balance_cents=?,"
        "difference_cents=0,closed_by=?,closed_at=? WHERE tenant_id=? AND id=?",
        (book_cents, int(closed_by), _now(), int(tenant_id), int(recon_id)),
    )
    await conn.commit()
    closed = await reconciliation_get(tenant_id, recon_id)
    assert closed is not None
    return closed


async def bank_summary(
    tenant_id: int, bank_account_id: int | None = None
) -> dict[str, Any]:
    payment_row = await fetch_one(
        "SELECT COUNT(*) AS n,COALESCE(SUM(amount_cents),0) AS total"
        " FROM payments WHERE tenant_id=?",
        (int(tenant_id),),
    )
    bank_params: list[Any] = [int(tenant_id)]
    bank_where = " WHERE tenant_id=?"
    if bank_account_id is not None:
        bank_where += " AND bank_account_id=?"
        bank_params.append(int(bank_account_id))
    bank_row = await fetch_one(
        "SELECT"
        " COALESCE(SUM(CASE WHEN direction='out' THEN amount_cents ELSE 0 END),0) AS out_total,"
        " COALESCE(SUM(CASE WHEN direction='in' THEN amount_cents ELSE 0 END),0) AS in_total,"
        " COALESCE(SUM(CASE WHEN status='unmatched' AND direction='out'"
        " THEN amount_cents ELSE 0 END),0) AS unmatched_out_total,"
        " COALESCE(SUM(CASE WHEN status='unmatched' THEN 1 ELSE 0 END),0) AS unmatched_count,"
        " COALESCE(SUM(CASE WHEN status='matched' THEN 1 ELSE 0 END),0) AS matched_count"
        " FROM bank_transactions" + bank_where,
        tuple(bank_params),
    )
    payments_count = int(payment_row["n"]) if payment_row else 0
    payments_total = int(payment_row["total"]) if payment_row else 0
    return {
        "payments_count": payments_count,
        "payments_total": round(payments_total / 100, 2),
        "payments_total_cents": payments_total,
        "bank_in_total": round(int(bank_row["in_total"]) / 100, 2) if bank_row else 0,
        "bank_out_total": round(int(bank_row["out_total"]) / 100, 2) if bank_row else 0,
        "unmatched_count": int(bank_row["unmatched_count"]) if bank_row else 0,
        "unmatched_out_total": round(
            int(bank_row["unmatched_out_total"]) / 100, 2
        ) if bank_row else 0,
        "matched_count": int(bank_row["matched_count"]) if bank_row else 0,
        "balanced": bool(bank_row and int(bank_row["unmatched_count"]) == 0),
    }
