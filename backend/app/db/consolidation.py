"""多主体管理合并（4.18.0）：集团范围、主体、抵销分录与合并报表。

明确口径：
- 只读各主体已过账凭证，不替主体改账；
- `full` 仅用于 100% 持股，`proportional` 按持股比例折算；
- 不做法定合并、不做少数股东权益、不自动匹配内部交易。
"""

from __future__ import annotations

import math
import sqlite3
from typing import Any

from ..calculations import analyze_statements
from ..calculations.report_from_gl import statements_from_trial_balance
from ..timeutil import new_id, now_iso
from ._core import fetch_all, fetch_one, write_txn
from .gl_accounts import gl_bootstrap, gl_list_periods
from .gl_entries_report import gl_trial_balance
from .org_tenant import get_tenant, org_role

MAX_ENTITIES = 20
MAX_LINES = 8
METHODS = {"full", "proportional"}


def _text(value: Any, field: str, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        raise ValueError(f"{field}不能为空")
    if len(text) > limit:
        raise ValueError(f"{field}不能超过 {limit} 个字")
    if any(ord(ch) < 32 for ch in text):
        raise ValueError(f"{field}不能包含控制字符")
    return text


def _period_parts(period: str) -> tuple[int, int]:
    text = " ".join(str(period or "").split()).strip()
    try:
        year_s, month_s = text.split("-", 1)
        year, month = int(year_s), int(month_s)
    except (TypeError, ValueError):
        raise ValueError("期间格式必须是 YYYY-MM") from None
    if not 2000 <= year <= 2100 or not 1 <= month <= 12:
        raise ValueError("期间需在 2000-01 到 2100-12 之间")
    return year, month


def _period_label(year: int, month: int) -> str:
    return f"{int(year):04d}-{int(month):02d}"


def _percent(value: Any) -> float:
    try:
        pct = float(value)
    except (TypeError, ValueError):
        raise ValueError("持股比例必须是数字") from None
    if not math.isfinite(pct) or pct <= 0 or pct > 100:
        raise ValueError("持股比例需在 (0, 100] 之间")
    return round(pct, 4)


def _method(value: Any, pct: float) -> str:
    method = str(value or "full").strip()
    if method not in METHODS:
        raise ValueError("纳入方式只能是 full 或 proportional")
    if method == "full" and pct != 100:
        raise ValueError("100% 持股才可用 full；部分持股请用 proportional（按比例折算）")
    return method


async def _group(group_id: str, user_id: int) -> dict[str, Any]:
    row = await fetch_one(
        "SELECT id,name,owner_user_id,status,created_at,updated_at"
        " FROM tenant_groups WHERE id=? AND owner_user_id=? AND status='active'",
        (str(group_id), int(user_id)),
    )
    if row is None:
        raise ValueError("集团不存在或无权访问")
    return dict(row)


async def _members(group_id: str, user_id: int) -> list[dict[str, Any]]:
    await _group(group_id, user_id)
    return await fetch_all(
        "SELECT g.tenant_id,g.ownership_pct,g.method,g.sort_order,g.created_at,"
        "t.name AS tenant_name,t.kind AS tenant_kind,t.status AS tenant_status"
        " FROM tenant_group_entities g"
        " JOIN tenants t ON t.id=g.tenant_id"
        " WHERE g.group_id=? ORDER BY g.sort_order,g.tenant_id",
        (str(group_id),),
    )


async def list_groups(user_id: int) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT g.id,g.name,g.owner_user_id,g.status,g.created_at,g.updated_at,"
        " COUNT(e.tenant_id) AS entity_count"
        " FROM tenant_groups g"
        " LEFT JOIN tenant_group_entities e ON e.group_id=g.id"
        " WHERE g.owner_user_id=? AND g.status='active'"
        " GROUP BY g.id ORDER BY g.created_at DESC,g.id",
        (int(user_id),),
    )
    return [dict(r) for r in rows]


async def group_detail(user_id: int, group_id: str) -> dict[str, Any]:
    group = await _group(group_id, user_id)
    members = await _members(group_id, user_id)
    periods = await available_periods(group_id, user_id)
    catalog = await account_catalog(group_id, user_id)
    return {
        "group": group,
        "entities": members,
        "periods": periods,
        "accounts": catalog["accounts"],
        "account_conflicts": catalog["conflicts"],
        "boundary": (
            "集团范围只属于创建者；主体必须是当前用户的有效成员租户。"
            "合并只读总账，不做法定合并。"
        ),
    }


async def create_group(user_id: int, name: Any) -> dict[str, Any]:
    clean = _text(name, "集团名称", 60)
    now = now_iso()
    group_id = new_id("grp_")
    try:
        async with write_txn() as conn:
            await conn.execute(
                "INSERT INTO tenant_groups(id,name,owner_user_id,status,created_at,updated_at)"
                " VALUES(?,?,?,'active',?,?)",
                (group_id, clean, int(user_id), now, now),
            )
    except sqlite3.IntegrityError:
        raise ValueError("已有同名集团，请换一个名称") from None
    return {
        "id": group_id, "name": clean, "owner_user_id": int(user_id),
        "status": "active", "entity_count": 0, "created_at": now, "updated_at": now,
    }


async def delete_group(group_id: str, user_id: int) -> dict[str, Any]:
    await _group(group_id, user_id)
    async with write_txn() as conn:
        await conn.execute(
            "DELETE FROM consolidation_adjustments WHERE group_id=?", (str(group_id),)
        )
        await conn.execute(
            "DELETE FROM tenant_group_entities WHERE group_id=?", (str(group_id),)
        )
        await conn.execute(
            "UPDATE tenant_groups SET status='deleted',updated_at=?"
            " WHERE id=? AND owner_user_id=?",
            (now_iso(), str(group_id), int(user_id)),
        )
    return {"ok": True, "group_id": str(group_id)}


async def entity_tenants(user_id: int, group_id: str | None = None) -> list[dict[str, Any]]:
    """当前用户可进入、尚未纳入指定集团的主体。"""
    used: set[int] = set()
    if group_id:
        await _group(group_id, user_id)
        rows = await fetch_all(
            "SELECT tenant_id FROM tenant_group_entities WHERE group_id=?", (str(group_id),)
        )
        used = {int(r["tenant_id"]) for r in rows}
    rows = await fetch_all(
        "SELECT t.id,t.name,t.kind,t.status,m.role"
        " FROM tenants t JOIN org_memberships m ON m.tenant_id=t.id"
        " WHERE m.user_id=? AND m.status='active' AND t.status='active'"
        " ORDER BY CASE t.kind WHEN 'personal' THEN 0 ELSE 1 END,t.id",
        (int(user_id),),
    )
    return [dict(r) for r in rows if int(r["id"]) not in used]


async def add_entity(
    user_id: int,
    group_id: str,
    *,
    tenant_id: int,
    ownership_pct: Any = 100,
    method: Any = "full",
) -> dict[str, Any]:
    await _group(group_id, user_id)
    try:
        tid = int(tenant_id)
    except (TypeError, ValueError):
        raise ValueError("主体 id 必须是整数") from None
    if tid < 0:
        raise ValueError("主体 id 不能为负数")
    pct = _percent(ownership_pct)
    method_s = _method(method, pct)
    tenant = await get_tenant(tid)
    if tenant is None or str(tenant.get("status") or "") != "active":
        raise ValueError("主体不存在或已停用")
    role = await org_role(tid, int(user_id))
    if role is None and not (int(user_id) == 0 and tid == 0):
        raise ValueError("你不在该主体的有效成员范围内")
    member_count = await fetch_one(
        "SELECT COUNT(*) AS n FROM tenant_group_entities WHERE group_id=?", (str(group_id),)
    )
    if member_count and int(member_count["n"]) >= MAX_ENTITIES:
        raise ValueError(f"一个集团最多纳入 {MAX_ENTITIES} 个主体")
    now = now_iso()
    try:
        async with write_txn() as conn:
            await conn.execute(
                "INSERT INTO tenant_group_entities"
                "(group_id,tenant_id,ownership_pct,method,sort_order,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (
                    str(group_id), tid, pct, method_s,
                    int(member_count["n"]) if member_count else 0, now,
                ),
            )
    except sqlite3.IntegrityError:
        raise ValueError("该主体已在合并范围内") from None
    return {
        "group_id": str(group_id), "tenant_id": tid, "tenant_name": tenant["name"],
        "ownership_pct": pct, "method": method_s, "created_at": now,
    }


async def create_entity(
    user_id: int,
    group_id: str,
    *,
    name: Any,
    ownership_pct: Any = 100,
    method: Any = "full",
) -> dict[str, Any]:
    """在当前集团下新建一个企业主体，并自动铺默认科目表。"""
    await _group(group_id, user_id)
    clean = _text(name, "主体名称", 60)
    pct = _percent(ownership_pct)
    method_s = _method(method, pct)
    member_count = await fetch_one(
        "SELECT COUNT(*) AS n FROM tenant_group_entities WHERE group_id=?", (str(group_id),)
    )
    if member_count and int(member_count["n"]) >= MAX_ENTITIES:
        raise ValueError(f"一个集团最多纳入 {MAX_ENTITIES} 个主体")
    now = now_iso()
    async with write_txn() as conn:
        cur = await conn.execute(
            "INSERT INTO tenants(name,kind,owner_user_id,status,created_at)"
            " VALUES(?,?,?,'active',?)",
            (clean, "enterprise", int(user_id), now),
        )
        tid = int(cur.lastrowid)
        await conn.execute(
            "INSERT INTO org_memberships(tenant_id,user_id,role,status,created_at)"
            " VALUES(?,?,'owner','active',?)",
            (tid, int(user_id), now),
        )
        await conn.execute(
            "INSERT INTO tenant_group_entities"
            "(group_id,tenant_id,ownership_pct,method,sort_order,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (
                str(group_id), tid, pct, method_s,
                int(member_count["n"]) if member_count else 0, now,
            ),
        )
    bootstrap = await gl_bootstrap(tid)
    return {
        "group_id": str(group_id), "tenant_id": tid, "tenant_name": clean,
        "ownership_pct": pct, "method": method_s, "created_at": now,
        "bootstrap": {
            "accounts_created": bootstrap["accounts_created"],
            "period": _period_label(bootstrap["period"]["year"], bootstrap["period"]["month"]),
        },
    }


async def remove_entity(user_id: int, group_id: str, tenant_id: int) -> dict[str, Any]:
    await _group(group_id, user_id)
    async with write_txn() as conn:
        cur = await conn.execute(
            "DELETE FROM tenant_group_entities WHERE group_id=? AND tenant_id=?",
            (str(group_id), int(tenant_id)),
        )
    if not cur.rowcount:
        raise ValueError("该主体不在合并范围内")
    return {"ok": True, "group_id": str(group_id), "tenant_id": int(tenant_id)}


async def account_catalog(group_id: str, user_id: int) -> dict[str, Any]:
    members = await _members(group_id, user_id)
    tids = [int(m["tenant_id"]) for m in members]
    if not tids:
        return {"accounts": [], "conflicts": []}
    placeholders = ",".join("?" for _ in tids)
    rows = await fetch_all(
        "SELECT code,name,type FROM gl_accounts WHERE tenant_id IN"
        f" ({placeholders}) AND is_active=1 ORDER BY code",
        tuple(tids),
    )
    seen: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for row in rows:
        code = str(row["code"])
        item = {"code": code, "name": str(row["name"]), "type": str(row["type"])}
        if code not in seen:
            seen[code] = item
        elif seen[code]["type"] != item["type"] or seen[code]["name"] != item["name"]:
            conflicts.append(item)
    return {"accounts": sorted(seen.values(), key=lambda x: x["code"]), "conflicts": conflicts}


async def available_periods(group_id: str, user_id: int) -> list[dict[str, Any]]:
    members = await _members(group_id, user_id)
    tids = [int(m["tenant_id"]) for m in members]
    if not tids:
        return []
    placeholders = ",".join("?" for _ in tids)
    rows = await fetch_all(
        "SELECT year,month,COUNT(DISTINCT tenant_id) AS entities"
        " FROM gl_periods WHERE tenant_id IN"
        f" ({placeholders})"
        " GROUP BY year,month ORDER BY year DESC,month DESC",
        tuple(tids),
    )
    return [
        {
            "period": _period_label(r["year"], r["month"]),
            "year": int(r["year"]), "month": int(r["month"]),
            "entities": int(r["entities"]),
        }
        for r in rows
    ]


async def create_adjustment(
    user_id: int,
    group_id: str,
    *,
    period: Any,
    description: Any,
    lines: Any,
) -> dict[str, Any]:
    await _group(group_id, user_id)
    year, month = _period_parts(str(period or ""))
    label = _period_label(year, month)
    desc = _text(description, "抵销摘要", 120)
    if not isinstance(lines, list) or len(lines) < 2 or len(lines) > MAX_LINES:
        raise ValueError(f"抵销分录需 2-{MAX_LINES} 行")
    catalog = await account_catalog(group_id, user_id)
    by_code = {a["code"]: a for a in catalog["accounts"]}
    prepared: list[dict[str, Any]] = []
    total_debit = total_credit = 0
    for idx, raw in enumerate(lines):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {idx + 1} 行格式错误")
        code = str(raw.get("account_code") or "").strip()
        if code not in by_code:
            raise ValueError(f"第 {idx + 1} 行科目不在合并科目表：{code or '空'}")
        try:
            raw_debit = raw.get("debit_cents") or 0
            raw_credit = raw.get("credit_cents") or 0
            if float(raw_debit) != int(raw_debit) or float(raw_credit) != int(raw_credit):
                raise ValueError
            debit = int(raw_debit)
            credit = int(raw_credit)
        except (TypeError, ValueError):
            raise ValueError(f"第 {idx + 1} 行金额必须是整数分") from None
        if debit < 0 or credit < 0 or (debit == 0 and credit == 0):
            raise ValueError(f"第 {idx + 1} 行金额必须大于 0")
        if debit and credit:
            raise ValueError(f"第 {idx + 1} 行不能同时有借方和贷方")
        total_debit += debit
        total_credit += credit
        prepared.append({
            "account_code": code,
            "account_name": by_code[code]["name"],
            "account_type": by_code[code]["type"],
            "debit_cents": debit,
            "credit_cents": credit,
            "memo": _text(raw.get("memo") or desc, "分录备注", 120),
        })
    if total_debit != total_credit:
        raise ValueError(
            f"抵销分录借贷不平衡：借方 {total_debit} 分，贷方 {total_credit} 分"
        )
    if total_debit <= 0:
        raise ValueError("抵销金额必须大于 0")
    voucher_id = new_id("adj_")
    now = now_iso()
    async with write_txn() as conn:
        for idx, line in enumerate(prepared):
            await conn.execute(
                "INSERT INTO consolidation_adjustments"
                "(id,group_id,period,voucher_id,line_no,description,account_code,"
                "account_name,account_type,debit_cents,credit_cents,memo,created_by,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id("cal_"), str(group_id), label, voucher_id, idx + 1, desc,
                    line["account_code"], line["account_name"], line["account_type"],
                    line["debit_cents"], line["credit_cents"], line["memo"],
                    int(user_id), now,
                ),
            )
    return {
        "voucher_id": voucher_id, "group_id": str(group_id), "period": label,
        "description": desc, "debit_cents": total_debit, "credit_cents": total_credit,
        "lines": prepared, "created_at": now,
    }


async def list_adjustments(
    user_id: int, group_id: str, period: str | None = None
) -> list[dict[str, Any]]:
    await _group(group_id, user_id)
    label = _period_label(*_period_parts(period)) if period else ""
    sql = (
        "SELECT id,period,voucher_id,line_no,description,account_code,account_name,"
        "account_type,debit_cents,credit_cents,memo,created_at"
        " FROM consolidation_adjustments WHERE group_id=?"
    )
    args: list[Any] = [str(group_id)]
    if label:
        sql += " AND period=?"
        args.append(label)
    sql += " ORDER BY created_at DESC,voucher_id,line_no"
    rows = await fetch_all(sql, tuple(args))
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        vid = str(row["voucher_id"])
        bucket = grouped.setdefault(
            vid,
            {
                "voucher_id": vid, "period": row["period"], "description": row["description"],
                "created_at": row["created_at"], "debit_cents": 0, "credit_cents": 0,
                "lines": [],
            },
        )
        bucket["debit_cents"] += int(row["debit_cents"] or 0)
        bucket["credit_cents"] += int(row["credit_cents"] or 0)
        bucket["lines"].append(dict(row))
    return list(grouped.values())


async def delete_adjustment(user_id: int, group_id: str, voucher_id: str) -> dict[str, Any]:
    await _group(group_id, user_id)
    async with write_txn() as conn:
        cur = await conn.execute(
            "DELETE FROM consolidation_adjustments WHERE group_id=? AND voucher_id=?",
            (str(group_id), str(voucher_id)),
        )
    if not cur.rowcount:
        raise ValueError("抵销分录不存在")
    return {"ok": True, "voucher_id": str(voucher_id)}


def _scale_items(items: list[dict[str, Any]], factor: float) -> tuple[list[dict[str, Any]], int]:
    scaled: list[dict[str, Any]] = []
    diff = 0
    for item in items:
        debit = round(int(item.get("debit_cents") or 0) * factor)
        credit = round(int(item.get("credit_cents") or 0) * factor)
        diff += debit - credit
        scaled.append({**item, "debit_cents": debit, "credit_cents": credit})
    return scaled, diff


def _merge_item(
    target: dict[str, dict[str, Any]], item: dict[str, Any], *, conflict: list[str]
) -> None:
    code = str(item.get("code") or "")
    if not code:
        return
    if code not in target:
        target[code] = {
            "account_id": int(item.get("account_id") or 0),
            "code": code,
            "name": str(item.get("name") or ""),
            "type": str(item.get("type") or ""),
            "debit_cents": 0,
            "credit_cents": 0,
        }
    elif target[code]["type"] != str(item.get("type") or ""):
        conflict.append(code)
    target[code]["debit_cents"] += int(item.get("debit_cents") or 0)
    target[code]["credit_cents"] += int(item.get("credit_cents") or 0)


def _summary(payload: dict[str, Any]) -> dict[str, float]:
    rows = payload.get("periods") or [{}]
    period = rows[0] if rows else {}
    bs = period.get("balance_sheet") or {}
    inc = period.get("income_statement") or {}
    return {
        "total_assets": float(bs.get("total_assets") or 0),
        "total_liabilities": float(bs.get("total_liabilities") or 0),
        "total_equity": float(bs.get("total_equity") or 0),
        "revenue": float(inc.get("revenue") or 0),
        "net_profit": float(inc.get("net_profit") or 0),
    }


async def consolidate(user_id: int, group_id: str, period: Any) -> dict[str, Any]:
    group = await _group(group_id, user_id)
    year, month = _period_parts(str(period or ""))
    label = _period_label(year, month)
    members = await _members(group_id, user_id)
    if not members:
        raise ValueError("合并范围为空：先加入至少一个主体")
    aggregated: dict[str, dict[str, Any]] = {}
    entities: list[dict[str, Any]] = []
    conflicts: list[str] = []
    rounding_diff = 0
    ok_count = 0
    for member in members:
        tid = int(member["tenant_id"])
        pct = float(member["ownership_pct"] or 100)
        method = str(member["method"] or "full")
        factor = 1.0 if method == "full" else pct / 100
        role = await org_role(tid, int(user_id))
        if role is None and not (int(user_id) == 0 and tid == 0):
            entities.append({
                "tenant_id": tid,
                "tenant_name": str(member.get("tenant_name") or ""),
                "tenant_kind": str(member.get("tenant_kind") or ""),
                "ownership_pct": pct,
                "method": method,
                "factor": factor,
                "status": "no_access",
                "period_id": None,
                "period_status": "",
                "posted_entries": 0,
                "draft_entries": 0,
                "statement": None,
                "included": None,
                "warning": "当前用户已不在该主体的有效成员范围内",
            })
            continue
        periods = await gl_list_periods(tid)
        found = next(
            (p for p in periods if int(p["year"]) == year and int(p["month"]) == month), None
        )
        posted = int(found.get("posted_entries") or 0) if found else 0
        status = "missing" if found is None else ("no_posted" if posted == 0 else "ok")
        entity: dict[str, Any] = {
            "tenant_id": tid,
            "tenant_name": str(member.get("tenant_name") or ""),
            "tenant_kind": str(member.get("tenant_kind") or ""),
            "ownership_pct": pct,
            "method": method,
            "factor": factor,
            "status": status,
            "period_id": int(found["id"]) if found else None,
            "period_status": str(found.get("status") or "") if found else "",
            "posted_entries": posted,
            "draft_entries": int(found.get("draft_entries") or 0) if found else 0,
            "statement": None,
            "included": None,
            "warning": "",
        }
        if status != "ok":
            entity["warning"] = (
                "该主体没有这一会计期间" if status == "missing"
                else "期间存在，但没有已过账凭证"
            )
            entities.append(entity)
            continue
        tb = await gl_trial_balance(tid, int(found["id"]))
        entity_payload = statements_from_trial_balance(
            tb.get("items") or [],
            company=str(member.get("tenant_name") or "主体"),
            period=label,
        )
        entity["statement"] = _summary(entity_payload)
        entity["included"] = {k: round(v * factor, 2) for k, v in entity["statement"].items()}
        entity["balanced"] = bool(tb.get("balanced"))
        entity["trial_balance"] = {
            "debit_cents": int(tb.get("total_debit_cents") or 0),
            "credit_cents": int(tb.get("total_credit_cents") or 0),
        }
        if method == "full" and pct != 100:
            entity["warning"] = "full 方式要求 100% 持股；当前记录不参与自动 NCI 计算"
        scaled, diff = _scale_items(tb.get("items") or [], factor)
        rounding_diff += diff
        for item in scaled:
            _merge_item(aggregated, item, conflict=conflicts)
        ok_count += 1
        entities.append(entity)
    if ok_count == 0:
        raise ValueError("所选期间没有可用主体：全部缺账或没有已过账凭证")

    adjustments = await list_adjustments(user_id, group_id, label)
    catalog = {a["code"]: a for a in (await account_catalog(group_id, user_id))["accounts"]}
    adj_debit = adj_credit = 0
    for voucher in adjustments:
        for line in voucher["lines"]:
            code = str(line["account_code"])
            adj_debit += int(line["debit_cents"] or 0)
            adj_credit += int(line["credit_cents"] or 0)
            _merge_item(
                aggregated,
                {
                    "code": code,
                    "name": line["account_name"],
                    "type": line["account_type"],
                    "debit_cents": int(line["debit_cents"] or 0),
                    "credit_cents": int(line["credit_cents"] or 0),
                },
                conflict=conflicts,
            )
            if code in catalog:
                item = aggregated[code]
                item["name"] = catalog[code]["name"]
                item["type"] = catalog[code]["type"]

    items = sorted(aggregated.values(), key=lambda x: str(x["code"]))
    for item in items:
        item["balance"] = (int(item["debit_cents"]) - int(item["credit_cents"])) / 100.0
    total_debit = sum(int(x["debit_cents"]) for x in items)
    total_credit = sum(int(x["credit_cents"]) for x in items)
    consolidated_payload = statements_from_trial_balance(
        items, company=str(group["name"]), period=label
    )
    consolidated = _summary(consolidated_payload)
    reported_sums = {
        "total_assets": round(sum(float(e["statement"]["total_assets"]) for e in entities if e["statement"]), 2),
        "total_liabilities": round(sum(float(e["statement"]["total_liabilities"]) for e in entities if e["statement"]), 2),
        "total_equity": round(sum(float(e["statement"]["total_equity"]) for e in entities if e["statement"]), 2),
        "revenue": round(sum(float(e["statement"]["revenue"]) for e in entities if e["statement"]), 2),
        "net_profit": round(sum(float(e["statement"]["net_profit"]) for e in entities if e["statement"]), 2),
    }
    included_sums = {
        "total_assets": round(sum(float(e["included"]["total_assets"]) for e in entities if e["included"]), 2),
        "total_liabilities": round(sum(float(e["included"]["total_liabilities"]) for e in entities if e["included"]), 2),
        "total_equity": round(sum(float(e["included"]["total_equity"]) for e in entities if e["included"]), 2),
        "revenue": round(sum(float(e["included"]["revenue"]) for e in entities if e["included"]), 2),
        "net_profit": round(sum(float(e["included"]["net_profit"]) for e in entities if e["included"]), 2),
    }
    warnings: list[str] = []
    if conflicts:
        warnings.append("科目编码在不同主体含义不一致：" + "、".join(sorted(set(conflicts))[:10]))
    if rounding_diff:
        warnings.append(f"比例折算产生 {rounding_diff} 分尾差，未自动抹平")
    if any(e["status"] != "ok" for e in entities):
        warnings.append("部分主体缺账或无已过账凭证，已排除出合并金额")
    if total_debit != total_credit:
        warnings.append(
            f"合并试算借贷不平：借方 {total_debit} 分，贷方 {total_credit} 分"
        )
    analysis = analyze_statements(consolidated_payload)
    return {
        "group": group,
        "period": label,
        "periods": await available_periods(group_id, user_id),
        "entities": entities,
        "adjustments": adjustments,
        "accounts": [a for a in (await account_catalog(group_id, user_id))["accounts"]],
        "items": items,
        "payload": consolidated_payload,
        "analysis": analysis,
        "summary": {
            "reported": reported_sums,
            "included": included_sums,
            "consolidated": consolidated,
            "eliminations": {
                "debit_cents": adj_debit,
                "credit_cents": adj_credit,
                "vouchers": len(adjustments),
            },
        },
        "balanced": total_debit == total_credit,
        "totals": {"debit_cents": total_debit, "credit_cents": total_credit},
        "warnings": warnings,
        "boundary": (
            "管理口径合并：只读各主体已过账凭证；full 需 100% 持股，"
            "proportional 按比例折算。不是法定合并，不自动计算少数股东权益，"
            "不自动识别内部交易，抵销分录须人工录入并借贷平衡。"
        ),
        "scope_note": "合并数字来自各主体已过账总账，缺账主体不按 0 计入。",
    }


__all__ = [
    "account_catalog", "add_entity", "available_periods", "consolidate",
    "create_adjustment", "create_entity", "create_group", "delete_adjustment",
    "delete_group", "entity_tenants", "group_detail", "list_adjustments", "list_groups",
    "remove_entity",
]
