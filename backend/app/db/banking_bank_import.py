"""银行流水 · CSV 导入：解析、去重、生成总账草稿与绑定。"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

from ..calculations.chart import pick_account_code
from ..calculations.gl import to_cents
from ..timeutil import now_str as _now
from ._core import _conn, get_write_lock
from .banking_bank_query import _assert_bank_account
from .gl import gl_bootstrap, gl_create_entry, gl_list_accounts


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
    tenant_id: int, bank_account_id: int, csv_text: str, auto_entry: bool = True
) -> dict[str, Any]:
    """导入银行流水；auto_entry=True 时顺手把每条流水转成一张草稿凭证。

    定位是"全托管"：用户只负责把流水弄进来，分录由系统按规则生成（借方费用/资产、
    贷方银行，或反向），生成的只是草稿——报表页的"一键出报表"会代过账。这样
    "导入流水 → 出报表"整条链路没有任何需要用户懂会计的环节。
    """
    await _assert_bank_account(tenant_id, bank_account_id)
    rows = _parse_csv_rows(csv_text)
    if not rows:
        raise ValueError("CSV 没有数据行")
    conn = await _conn()
    inserted: list[dict[str, Any]] = []
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            for r in rows:
                cur = await conn.execute(
                    "INSERT INTO bank_transactions(tenant_id,bank_account_id,txn_date,direction,"
                    "amount_cents,counterparty,memo,bank_ref,status,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,'unmatched',?,?)",
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
                    ),
                )
                inserted.append({**r, "id": int(cur.lastrowid)})
            await conn.execute("COMMIT")
        except BaseException:
            await conn.execute("ROLLBACK")
            raise

    result: dict[str, Any] = {"imported": len(inserted), "entries_created": 0}
    if auto_entry and inserted:
        result["entries_created"] = await _entries_for_import(tenant_id, bank_account_id, inserted)
    return result


async def _entries_for_import(
    tenant_id: int, bank_account_id: int, rows: list[dict[str, Any]]
) -> int:
    """给刚导入的流水批量生成草稿凭证，返回成功条数。

    任何一条失败（期间已关账、科目被删等）都不影响其余流水，也不影响导入本身——
    导入的数据是事实，凭证是可重建的派生物。
    """
    # 不同月份可能跨期，按"年月"各自建账一次
    booted: set[tuple[int, int]] = set()
    accounts = {str(a.get("code")): int(a["id"]) for a in await gl_list_accounts(tenant_id)}
    made = 0
    for r in rows:
        day = date.fromisoformat(str(r["txn_date"]))
        if (day.year, day.month) not in booted:
            await gl_bootstrap(tenant_id, str(r["txn_date"]))
            accounts = {str(a.get("code")): int(a["id"]) for a in await gl_list_accounts(tenant_id)}
            booted.add((day.year, day.month))
        code = pick_account_code(
            str(r["direction"]), str(r.get("memo", "")), str(r.get("counterparty", ""))
        )
        contra = accounts.get(code)
        if contra is None:
            continue
        amount = round(int(r["amount_cents"]) / 100, 2)
        if amount <= 0:
            continue
        bank_side = {"account_id": int(bank_account_id), "debit": 0.0, "credit": 0.0}
        other_side = {"account_id": contra, "debit": 0.0, "credit": 0.0}
        if str(r["direction"]) == "out":
            other_side["debit"], bank_side["credit"] = amount, amount
        else:
            bank_side["debit"], other_side["credit"] = amount, amount
        label = " ".join(x for x in (str(r.get("counterparty", "")), str(r.get("memo", ""))) if x).strip()
        try:
            entry = await gl_create_entry(
                tenant_id, str(r["txn_date"]), label or "银行流水", [other_side, bank_side], 0
            )
        except (TypeError, ValueError):
            continue
        await _bind_entry(tenant_id, int(r["id"]), int(entry["id"]))
        made += 1
    return made


async def _bind_entry(tenant_id: int, txn_id: int, entry_id: int) -> None:
    conn = await _conn()
    await conn.execute(
        "UPDATE bank_transactions SET gl_entry_id=?,updated_at=? WHERE tenant_id=? AND id=?",
        (int(entry_id), _now(), int(tenant_id), int(txn_id)),
    )
    await conn.commit()
