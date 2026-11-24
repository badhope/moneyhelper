"""企业预算与资金计划（4.19.0）。

管理口径，不生成凭证、不划转资金：
- 预算按 `YYYY-MM` + 总账收入/费用科目编制，实际数只取 `status=posted` 凭证；
- 资金计划按日期列出预计流入/流出，实际数只取现金科目（1001/1002）已过账分录；
- 期初余额由用户填写，不由系统从历史账套推算；缺期间时明确标记，不按 0 冒充。
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from ..timeutil import new_id, now_iso
from ._core import fetch_all, fetch_one, write_txn
from .gl_accounts import gl_list_accounts, gl_list_periods
from .gl_entries_report import gl_trial_balance

_BUDGET_NAME = "主预算"
_CASH_NAME = "资金计划"
_CASH_CODES = ("1001", "1002")
_CERTAINTY = {"high", "medium", "low"}


def _period_parts(value: str) -> tuple[int, int, str]:
    text = str(value or "").strip()
    try:
        year_s, month_s = text.split("-", 1)
        year, month = int(year_s), int(month_s)
    except (ValueError, TypeError):
        raise ValueError("期间格式必须是 YYYY-MM") from None
    if not 2000 <= year <= 2100 or not 1 <= month <= 12:
        raise ValueError("期间需在 2000-01 到 2100-12 之间")
    return year, month, f"{year:04d}-{month:02d}"


def _clean(value: Any, limit: int = 120) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _cents(value: Any, field: str = "金额") -> int:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        raise ValueError(f"{field}必须是数字") from None
    if not math.isfinite(amount):
        raise ValueError(f"{field}必须是有限数字")
    if amount < 0:
        raise ValueError(f"{field}不能为负")
    return int(round(amount * 100))


def _yuan(cents: int | float | None) -> float:
    return round(float(cents or 0) / 100.0, 2)


async def _plan_periods(tenant_id: int) -> list[str]:
    rows = await fetch_all(
        "SELECT period FROM enterprise_budget_plans WHERE tenant_id=?"
        " UNION SELECT period FROM enterprise_cash_plans WHERE tenant_id=?"
        " UNION SELECT printf('%04d-%02d', year, month) AS period FROM gl_periods"
        " WHERE tenant_id=? ORDER BY period DESC",
        (int(tenant_id), int(tenant_id), int(tenant_id)),
    )
    seen = sorted({str(r["period"]) for r in rows if r.get("period")}, reverse=True)
    current = date.today().strftime("%Y-%m")
    if current not in seen:
        seen = sorted({*seen, current}, reverse=True)
    return seen[:36]


async def _gl_period(tenant_id: int, year: int, month: int) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT id,year,month,status,start_date,end_date,"
        "(SELECT COUNT(*) FROM gl_entries e WHERE e.tenant_id=gl_periods.tenant_id"
        " AND e.period_id=gl_periods.id AND e.status='posted') AS posted_entries,"
        "(SELECT COUNT(*) FROM gl_entries e WHERE e.tenant_id=gl_periods.tenant_id"
        " AND e.period_id=gl_periods.id AND e.status='draft') AS draft_entries"
        " FROM gl_periods WHERE tenant_id=? AND year=? AND month=?",
        (int(tenant_id), int(year), int(month)),
    )
    return dict(row) if row else None


async def _accounts(tenant_id: int) -> dict[str, dict[str, Any]]:
    return {str(a["code"]): a for a in await gl_list_accounts(tenant_id)}


async def _plan_row(tenant_id: int, table: str, period: str, name: str) -> dict[str, Any] | None:
    row = await fetch_one(
        f"SELECT * FROM {table} WHERE tenant_id=? AND period=? AND name=?",
        (int(tenant_id), period, name),
    )
    return dict(row) if row else None


async def budget_plan_get(
    tenant_id: int, period: str, name: str = _BUDGET_NAME
) -> dict[str, Any]:
    year, month, label = _period_parts(period)
    plan = await _plan_row(tenant_id, "enterprise_budget_plans", label, _clean(name, 40) or _BUDGET_NAME)
    lines: list[dict[str, Any]] = []
    if plan is not None:
        rows = await fetch_all(
            "SELECT account_code,account_name,account_type,amount_cents,note"
            " FROM enterprise_budget_lines WHERE tenant_id=? AND plan_id=?"
            " ORDER BY account_code",
            (int(tenant_id), plan["id"]),
        )
        lines = [
            {
                "account_code": str(r["account_code"]),
                "account_name": str(r["account_name"] or ""),
                "account_type": str(r["account_type"] or ""),
                "amount": _yuan(r["amount_cents"]),
                "amount_cents": int(r["amount_cents"] or 0),
                "note": str(r["note"] or ""),
            }
            for r in rows
        ]
    return {
        "period": label,
        "name": _clean(name, 40) or _BUDGET_NAME,
        "exists": plan is not None,
        "plan": None
        if plan is None
        else {
            "id": plan["id"],
            "note": str(plan.get("note") or ""),
            "created_at": str(plan.get("created_at") or ""),
            "updated_at": str(plan.get("updated_at") or ""),
        },
        "lines": lines,
        "accounts": [
            {"code": str(a["code"]), "name": str(a["name"]), "type": str(a["type"])}
            for a in (await _accounts(tenant_id)).values()
            if str(a.get("type")) in {"income", "expense"} and int(a.get("is_active") or 1) == 1
        ],
        "periods": await _plan_periods(tenant_id),
        "boundary": "预算只作管理控制，不生成凭证；实际数只取已过账总账凭证。",
    }


async def budget_plan_save(
    tenant_id: int,
    period: str,
    lines: list[dict[str, Any]],
    name: str = _BUDGET_NAME,
    note: str = "",
    created_by: int | None = None,
) -> dict[str, Any]:
    _, _, label = _period_parts(period)
    plan_name = _clean(name, 40) or _BUDGET_NAME
    if not isinstance(lines, list) or len(lines) > 200:
        raise ValueError("预算行必须是最多 200 条的列表")
    accounts = await _accounts(tenant_id)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, item in enumerate(lines):
        if not isinstance(item, dict):
            raise ValueError(f"第 {idx + 1} 行不是对象")
        code = _clean(item.get("account_code"), 20)
        account = accounts.get(code)
        if account is None:
            raise ValueError(f"第 {idx + 1} 行科目 {code or '(空)'} 不存在")
        if str(account.get("type")) not in {"income", "expense"}:
            raise ValueError(f"第 {idx + 1} 行科目 {code} 不是收入或费用科目")
        if code in seen:
            raise ValueError(f"科目 {code} 重复")
        seen.add(code)
        normalized.append(
            {
                "code": code,
                "name": str(account.get("name") or ""),
                "type": str(account.get("type") or ""),
                "cents": _cents(item.get("amount"), f"第 {idx + 1} 行预算金额"),
                "note": _clean(item.get("note"), 80),
            }
        )
    now = now_iso()
    async with write_txn() as conn:
        existing = await _plan_row(tenant_id, "enterprise_budget_plans", label, plan_name)
        plan_id = existing["id"] if existing else new_id("ebp_")
        if existing:
            await conn.execute(
                "UPDATE enterprise_budget_plans SET note=?,updated_at=? WHERE id=?",
                (_clean(note, 200), now, plan_id),
            )
        else:
            await conn.execute(
                "INSERT INTO enterprise_budget_plans"
                "(id,tenant_id,period,name,note,created_by,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (plan_id, int(tenant_id), label, plan_name, _clean(note, 200),
                 int(created_by or 0), now, now),
            )
        await conn.execute(
            "DELETE FROM enterprise_budget_lines WHERE tenant_id=? AND plan_id=?",
            (int(tenant_id), plan_id),
        )
        for item in normalized:
            await conn.execute(
                "INSERT INTO enterprise_budget_lines"
                "(plan_id,tenant_id,account_code,account_name,account_type,amount_cents,note)"
                " VALUES(?,?,?,?,?,?,?)",
                (plan_id, int(tenant_id), item["code"], item["name"], item["type"],
                 item["cents"], item["note"]),
            )
    return await budget_plan_get(tenant_id, label, plan_name)


async def budget_report(
    tenant_id: int, period: str, name: str = _BUDGET_NAME
) -> dict[str, Any]:
    year, month, label = _period_parts(period)
    plan = await budget_plan_get(tenant_id, label, name)
    period_row = await _gl_period(tenant_id, year, month)
    actual_by_code: dict[str, dict[str, Any]] = {}
    if period_row is not None:
        tb = await gl_trial_balance(tenant_id, int(period_row["id"]))
        for item in tb.get("items") or []:
            acct_type = str(item.get("type") or "")
            if acct_type not in {"income", "expense"}:
                continue
            debit, credit = int(item.get("debit_cents") or 0), int(item.get("credit_cents") or 0)
            actual = credit - debit if acct_type == "income" else debit - credit
            actual_by_code[str(item["code"])] = {
                "name": str(item.get("name") or ""),
                "type": acct_type,
                "actual_cents": int(actual),
            }
    rows: list[dict[str, Any]] = []
    for line in plan["lines"]:
        actual = actual_by_code.pop(line["account_code"], None)
        budget_cents = int(line["amount_cents"])
        actual_cents = int(actual["actual_cents"]) if actual else 0
        acct_type = line["account_type"]
        favorable = actual_cents - budget_cents if acct_type == "income" else budget_cents - actual_cents
        rows.append(
            {
                "account_code": line["account_code"],
                "account_name": line["account_name"],
                "account_type": acct_type,
                "budget": _yuan(budget_cents),
                "budget_cents": budget_cents,
                "actual": _yuan(actual_cents),
                "actual_cents": actual_cents,
                "variance": _yuan(favorable),
                "variance_cents": favorable,
                "pct": round(actual_cents / budget_cents * 100, 1) if budget_cents else 0.0,
                "status": "within" if favorable >= 0 else ("short" if acct_type == "income" else "over"),
                "unbudgeted": False,
            }
        )
    for code, actual in sorted(actual_by_code.items()):
        if int(actual["actual_cents"]) == 0:
            continue
        rows.append(
            {
                "account_code": code,
                "account_name": actual["name"],
                "account_type": actual["type"],
                "budget": 0.0,
                "budget_cents": 0,
                "actual": _yuan(actual["actual_cents"]),
                "actual_cents": int(actual["actual_cents"]),
                "variance": _yuan(actual["actual_cents"] if actual["type"] == "income" else -actual["actual_cents"]),
                "variance_cents": int(actual["actual_cents"]) if actual["type"] == "income" else -int(actual["actual_cents"]),
                "pct": 0.0,
                "status": "unbudgeted",
                "unbudgeted": True,
            }
        )
    budget_income = sum(r["budget_cents"] for r in rows if r["account_type"] == "income" and not r["unbudgeted"])
    actual_income = sum(r["actual_cents"] for r in rows if r["account_type"] == "income")
    budget_expense = sum(r["budget_cents"] for r in rows if r["account_type"] == "expense" and not r["unbudgeted"])
    actual_expense = sum(r["actual_cents"] for r in rows if r["account_type"] == "expense")
    warnings: list[str] = []
    if plan["exists"] is False:
        warnings.append("本期还没有预算，先编制预算再看执行差异")
    if period_row is None:
        warnings.append("本期没有会计期间，实际数暂按 0 展示，不代表已发生")
    elif int(period_row.get("draft_entries") or 0) > 0:
        warnings.append(f"本期还有 {int(period_row['draft_entries'])} 张草稿凭证，未计入实际数")
    if budget_expense and actual_expense > budget_expense:
        warnings.append(f"费用已超出预算 {_yuan(actual_expense - budget_expense):,.2f} 元")
    return {
        "period": label,
        "name": plan["name"],
        "exists": plan["exists"],
        "period_status": str(period_row.get("status") or "missing") if period_row else "missing",
        "posted_entries": int(period_row.get("posted_entries") or 0) if period_row else 0,
        "draft_entries": int(period_row.get("draft_entries") or 0) if period_row else 0,
        "rows": rows,
        "totals": {
            "budget_income": _yuan(budget_income),
            "actual_income": _yuan(actual_income),
            "income_variance": _yuan(actual_income - budget_income),
            "budget_expense": _yuan(budget_expense),
            "actual_expense": _yuan(actual_expense),
            "expense_variance": _yuan(budget_expense - actual_expense),
        },
        "warnings": warnings,
        "boundary": "实际数只取 status=posted 的总账凭证；预算不生成凭证、不改变账本。",
    }


async def cash_plan_get(tenant_id: int, period: str, name: str = _CASH_NAME) -> dict[str, Any]:
    year, month, label = _period_parts(period)
    plan = await _plan_row(tenant_id, "enterprise_cash_plans", label, _clean(name, 40) or _CASH_NAME)
    lines: list[dict[str, Any]] = []
    if plan is not None:
        rows = await fetch_all(
            "SELECT expected_date,direction,account_code,counterparty,amount_cents,certainty,note"
            " FROM enterprise_cash_plan_lines WHERE tenant_id=? AND plan_id=?"
            " ORDER BY expected_date,id",
            (int(tenant_id), plan["id"]),
        )
        lines = [
            {
                "expected_date": str(r["expected_date"]),
                "direction": str(r["direction"]),
                "account_code": str(r["account_code"] or "1001"),
                "counterparty": str(r["counterparty"] or ""),
                "amount": _yuan(r["amount_cents"]),
                "amount_cents": int(r["amount_cents"] or 0),
                "certainty": str(r["certainty"] or "medium"),
                "note": str(r["note"] or ""),
            }
            for r in rows
        ]
    return {
        "period": label,
        "name": _clean(name, 40) or _CASH_NAME,
        "exists": plan is not None,
        "plan": None
        if plan is None
        else {
            "id": plan["id"],
            "opening": _yuan(plan["opening_cents"]),
            "opening_cents": int(plan["opening_cents"] or 0),
            "target_min": _yuan(plan["target_min_cents"]),
            "target_min_cents": int(plan["target_min_cents"] or 0),
            "note": str(plan.get("note") or ""),
            "created_at": str(plan.get("created_at") or ""),
            "updated_at": str(plan.get("updated_at") or ""),
        },
        "lines": lines,
        "accounts": [{"code": c, "name": "银行存款" if c == "1001" else "库存现金"} for c in _CASH_CODES],
        "periods": await _plan_periods(tenant_id),
        "boundary": "资金计划是管理推演，不是银行余额，不代任何资金划转。",
    }


async def cash_plan_save(
    tenant_id: int,
    period: str,
    lines: list[dict[str, Any]],
    name: str = _CASH_NAME,
    opening: float = 0,
    target_min: float = 0,
    note: str = "",
    created_by: int | None = None,
) -> dict[str, Any]:
    year, month, label = _period_parts(period)
    plan_name = _clean(name, 40) or _CASH_NAME
    if not isinstance(lines, list) or len(lines) > 200:
        raise ValueError("资金计划行必须是最多 200 条的列表")
    opening_cents = _cents(opening, "期初余额")
    target_cents = _cents(target_min, "最低目标余额")
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(lines):
        if not isinstance(item, dict):
            raise ValueError(f"第 {idx + 1} 行不是对象")
        raw_date = _clean(item.get("expected_date"), 10)
        try:
            day = date.fromisoformat(raw_date)
        except ValueError:
            raise ValueError(f"第 {idx + 1} 行日期必须是 YYYY-MM-DD") from None
        if day.year != year or day.month != month:
            raise ValueError(f"第 {idx + 1} 行日期必须落在 {label}")
        direction = _clean(item.get("direction"), 10)
        if direction not in {"in", "out"}:
            raise ValueError(f"第 {idx + 1} 行方向必须是 in 或 out")
        code = _clean(item.get("account_code"), 20) or "1001"
        if code not in _CASH_CODES:
            raise ValueError(f"第 {idx + 1} 行现金科目只能是 1001 或 1002")
        amount_cents = _cents(item.get("amount"), f"第 {idx + 1} 行计划金额")
        if amount_cents <= 0:
            raise ValueError(f"第 {idx + 1} 行计划金额必须大于 0")
        certainty = _clean(item.get("certainty"), 12) or "medium"
        if certainty not in _CERTAINTY:
            raise ValueError(f"第 {idx + 1} 行确定性必须是 high/medium/low")
        normalized.append(
            {
                "date": day.isoformat(),
                "direction": direction,
                "code": code,
                "counterparty": _clean(item.get("counterparty"), 80),
                "cents": amount_cents,
                "certainty": certainty,
                "note": _clean(item.get("note"), 80),
            }
        )
    now = now_iso()
    async with write_txn() as conn:
        existing = await _plan_row(tenant_id, "enterprise_cash_plans", label, plan_name)
        plan_id = existing["id"] if existing else new_id("ecp_")
        if existing:
            await conn.execute(
                "UPDATE enterprise_cash_plans SET opening_cents=?,target_min_cents=?,"
                "note=?,updated_at=? WHERE id=?",
                (opening_cents, target_cents, _clean(note, 200), now, plan_id),
            )
        else:
            await conn.execute(
                "INSERT INTO enterprise_cash_plans"
                "(id,tenant_id,period,name,opening_cents,target_min_cents,note,"
                "created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (plan_id, int(tenant_id), label, plan_name, opening_cents, target_cents,
                 _clean(note, 200), int(created_by or 0), now, now),
            )
        await conn.execute(
            "DELETE FROM enterprise_cash_plan_lines WHERE tenant_id=? AND plan_id=?",
            (int(tenant_id), plan_id),
        )
        for item in normalized:
            await conn.execute(
                "INSERT INTO enterprise_cash_plan_lines"
                "(plan_id,tenant_id,expected_date,direction,account_code,counterparty,"
                "amount_cents,certainty,note) VALUES(?,?,?,?,?,?,?,?,?)",
                (plan_id, int(tenant_id), item["date"], item["direction"], item["code"],
                 item["counterparty"], item["cents"], item["certainty"], item["note"]),
            )
    return await cash_plan_get(tenant_id, label, plan_name)


async def _cash_actual(tenant_id: int, year: int, month: int) -> dict[str, dict[str, int]]:
    start, end = f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-31"
    rows = await fetch_all(
        "SELECT e.entry_date AS day,"
        " COALESCE(SUM(l.debit_cents-l.credit_cents),0) AS net_cents"
        " FROM gl_entries e JOIN gl_entry_lines l ON l.tenant_id=e.tenant_id AND l.entry_id=e.id"
        " JOIN gl_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id"
        " WHERE e.tenant_id=? AND e.status='posted' AND e.entry_date BETWEEN ? AND ?"
        " AND a.code IN ('1001','1002') GROUP BY e.entry_date ORDER BY e.entry_date",
        (int(tenant_id), start, end),
    )
    return {
        str(r["day"]): {"net_cents": int(r["net_cents"] or 0)} for r in rows
    }


async def cash_report(tenant_id: int, period: str, name: str = _CASH_NAME) -> dict[str, Any]:
    year, month, label = _period_parts(period)
    plan = await cash_plan_get(tenant_id, label, name)
    period_row = await _gl_period(tenant_id, year, month)
    actual = await _cash_actual(tenant_id, year, month)
    opening_cents = int((plan.get("plan") or {}).get("opening_cents") or 0)
    target_cents = int((plan.get("plan") or {}).get("target_min_cents") or 0)
    planned_by_day: dict[str, dict[str, int]] = {}
    for line in plan["lines"]:
        bucket = planned_by_day.setdefault(line["expected_date"], {"in": 0, "out": 0})
        bucket["in" if line["direction"] == "in" else "out"] += int(line["amount_cents"])
    planned_total = sum(b["in"] - b["out"] for b in planned_by_day.values())
    today = date.today()
    if (today.year, today.month) == (year, month):
        as_of = today.isoformat()
    elif (year, month) < (today.year, today.month):
        as_of = f"{year:04d}-{month:02d}-31"
    else:
        as_of = f"{year:04d}-{month:02d}-01"
    dates = sorted(set(planned_by_day) | set(actual))
    planned_balance = opening_cents
    actual_balance = opening_cents
    series: list[dict[str, Any]] = []
    planned_to_date = opening_cents
    actual_to_date = opening_cents
    for day in dates:
        p = planned_by_day.get(day, {"in": 0, "out": 0})
        a = int(actual.get(day, {}).get("net_cents") or 0)
        planned_balance += p["in"] - p["out"]
        actual_balance += a
        if day <= as_of:
            planned_to_date += p["in"] - p["out"]
            actual_to_date += a
        series.append(
            {
                "date": day,
                "planned_in": _yuan(p["in"]),
                "planned_out": _yuan(p["out"]),
                "planned_net": _yuan(p["in"] - p["out"]),
                "planned_balance": _yuan(planned_balance),
                "actual_net": _yuan(a),
                "actual_balance": _yuan(actual_balance),
            }
        )
    projected_end = opening_cents + planned_total
    warnings: list[str] = []
    if not plan["exists"]:
        warnings.append("本期还没有资金计划，先编制再看执行差异")
    if period_row is None:
        warnings.append("本期没有会计期间，实际现金流暂按 0 展示")
    elif int(period_row.get("draft_entries") or 0) > 0:
        warnings.append(f"本期还有 {int(period_row['draft_entries'])} 张草稿凭证，未计入实际数")
    if plan["exists"] and target_cents > 0 and projected_end < target_cents:
        warnings.append(f"计划最低余额 {_yuan(target_cents):,.2f} 元，预计期末低 {_yuan(target_cents - projected_end):,.2f} 元")
    variance = actual_to_date - planned_to_date
    if plan["exists"] and planned_to_date != 0 and abs(variance) / max(1, abs(planned_to_date)) > 0.05:
        warnings.append(f"截至 {as_of} 实际与计划差 {_yuan(variance):+,.2f} 元，需核对回款/付款进度")
    return {
        "period": label,
        "name": plan["name"],
        "exists": plan["exists"],
        "as_of": as_of,
        "opening": _yuan(opening_cents),
        "target_min": _yuan(target_cents),
        "projected_end": _yuan(projected_end),
        "actual_to_date": _yuan(actual_to_date),
        "planned_to_date": _yuan(planned_to_date),
        "variance_to_date": _yuan(variance),
        "series": series,
        "warnings": warnings,
        "boundary": "期初余额由用户填写；实际数只取 1001/1002 已过账分录；不代资金划转。",
    }


__all__ = [
    "budget_plan_get",
    "budget_plan_save",
    "budget_report",
    "cash_plan_get",
    "cash_plan_save",
    "cash_report",
    "plan_periods",
]


async def plan_periods(tenant_id: int) -> list[str]:
    return await _plan_periods(tenant_id)
