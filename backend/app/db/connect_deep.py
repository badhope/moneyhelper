"""连接中心深化域持久化：发票归档 / 持仓对账单导入 / 条件单 / 风控设置。

设计要点：
- 全部按租户隔离（user_id 复合主键）；
- 发票与对账单都用 `file_hash` 做幂等：同一文件重复上传不产生重复记录；
- 条件单是「观察中的规则」，触发后只生成待确认意图（不代下单）；
- 风控设置单行存储，缺省时返回默认值而不是报错。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from ..logging_utils import get_logger
from ._core import _conn, _mark_user_data, fetch_all, fetch_one, get_write_lock
from .tenant import current_user_id

log = get_logger(__name__)

CONDITIONAL_STATUSES = ("watching", "triggered", "cancelled", "expired")
TRIGGER_TYPES = ("price_below", "price_above", "pct_change_below", "pct_change_above")
INVOICE_STATUSES = ("parsed", "confirmed", "archived", "ignored")

MAX_INVOICES = 2000
MAX_CONDITIONAL = 100


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def file_hash(raw: bytes) -> str:
    """内容指纹：同文件重复上传/重复扫描都能识别。"""
    return hashlib.sha256(raw).hexdigest()[:32]


# ---------------------------------------------------------------------------
# 发票
# ---------------------------------------------------------------------------


async def save_invoice(
    *,
    file_name: str,
    raw: bytes,
    parsed: dict[str, Any],
    note: str = "",
) -> dict[str, Any]:
    """归档一张发票。同内容文件已存在时返回既有记录（duplicate=True）。"""
    uid = current_user_id()
    digest = file_hash(raw)
    existing = await fetch_one(
        "SELECT id FROM invoices WHERE user_id=? AND file_hash=?", (uid, digest)
    )
    if existing:
        row = await get_invoice(str(existing["id"]))
        return {**(row or {}), "duplicate": True}

    rows = await fetch_all("SELECT id FROM invoices WHERE user_id=?", (uid,))
    if len(rows) >= MAX_INVOICES:
        raise ValueError(f"最多归档 {MAX_INVOICES} 张发票")

    iid = _new_id("inv")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO invoices(user_id,id,file_name,file_hash,source_format,invoice_code,"
            "invoice_number,invoice_date,buyer,seller,item,total_amount,tax_amount,tax_rate,"
            "kind,confidence,status,note,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uid,
                iid,
                file_name[:120],
                digest,
                str(parsed.get("source_format") or "")[:20],
                str(parsed.get("invoice_code") or "")[:30],
                str(parsed.get("invoice_number") or "")[:30],
                str(parsed.get("invoice_date") or "")[:10],
                str(parsed.get("buyer") or "")[:80],
                str(parsed.get("seller") or "")[:80],
                str(parsed.get("item") or "")[:120],
                parsed.get("total_amount"),
                parsed.get("tax_amount"),
                str(parsed.get("tax_rate") or "")[:12],
                str(parsed.get("kind") or "")[:24],
                str(parsed.get("confidence") or "")[:12],
                "parsed",
                note[:200],
                _now(),
            ),
        )
        await _mark_user_data(conn)
        await conn.commit()
    return {**(await get_invoice(iid) or {}), "duplicate": False}


async def get_invoice(iid: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM invoices WHERE user_id=? AND id=?", (current_user_id(), iid)
    )
    return dict(row) if row else None


async def list_invoices(limit: int = 100, status: str = "") -> list[dict[str, Any]]:
    params: list[Any] = [current_user_id()]
    sql = "SELECT * FROM invoices WHERE user_id=?"
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    return await fetch_all(sql, tuple(params))


async def update_invoice_status(iid: str, status: str, note: str = "") -> dict[str, Any]:
    if status not in INVOICE_STATUSES:
        raise ValueError(f"状态只能是 {'/'.join(INVOICE_STATUSES)}")
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "UPDATE invoices SET status=?, note=? WHERE user_id=? AND id=?",
            (status, note[:200], current_user_id(), iid),
        )
        await conn.commit()
        if cur.rowcount == 0:
            raise ValueError("发票不存在")
    return await get_invoice(iid) or {}


async def invoice_summary() -> dict[str, Any]:
    """发票汇总：张数、价税合计、税额、按月分布。"""
    rows = await fetch_all(
        "SELECT invoice_date,total_amount,tax_amount,status FROM invoices WHERE user_id=?",
        (current_user_id(),),
    )
    total_amount = round(sum(float(r["total_amount"] or 0) for r in rows), 2)
    total_tax = round(sum(float(r["tax_amount"] or 0) for r in rows), 2)
    by_month: dict[str, float] = {}
    for r in rows:
        month = str(r["invoice_date"] or "")[:7] or "未知"
        by_month[month] = round(by_month.get(month, 0.0) + float(r["total_amount"] or 0), 2)
    return {
        "count": len(rows),
        "total_amount": total_amount,
        "total_tax": total_tax,
        "by_month": [{"month": k, "amount": v} for k, v in sorted(by_month.items())],
        "pending": sum(1 for r in rows if r["status"] == "parsed"),
    }


async def delete_invoice(iid: str) -> bool:
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "DELETE FROM invoices WHERE user_id=? AND id=?", (current_user_id(), iid)
        )
        await conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# 持仓对账单导入
# ---------------------------------------------------------------------------


async def record_brokerage_import(
    *,
    file_name: str,
    raw: bytes,
    account: str,
    position_count: int,
    applied: int,
    warnings: list[str],
) -> dict[str, Any]:
    """记录一次持仓导入；同文件重复导入返回既有记录（duplicate=True）。"""
    uid = current_user_id()
    digest = file_hash(raw)
    existing = await fetch_one(
        "SELECT * FROM brokerage_imports WHERE user_id=? AND file_hash=?", (uid, digest)
    )
    if existing:
        row = dict(existing)
        row["warnings"] = json.loads(row.pop("warnings_json", "[]"))
        row["duplicate"] = True
        return row

    bid = _new_id("bimp")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO brokerage_imports(user_id,id,file_name,file_hash,account,"
            "position_count,applied,warnings_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                uid,
                bid,
                file_name[:120],
                digest,
                account[:40],
                int(position_count),
                int(applied),
                json.dumps(warnings[:50], ensure_ascii=False),
                _now(),
            ),
        )
        await conn.commit()
    return {
        "id": bid,
        "file_name": file_name,
        "account": account,
        "position_count": position_count,
        "applied": applied,
        "warnings": warnings,
        "duplicate": False,
    }


async def list_brokerage_imports(limit: int = 30) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM brokerage_imports WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (current_user_id(), max(1, min(int(limit), 200))),
    )
    out = []
    for r in rows:
        row = dict(r)
        row["warnings"] = json.loads(row.pop("warnings_json", "[]"))
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# 条件单
# ---------------------------------------------------------------------------


async def create_conditional(payload: dict[str, Any]) -> dict[str, Any]:
    symbol = str(payload.get("symbol") or "").strip().upper()
    if not (symbol.isdigit() and len(symbol) == 6):
        raise ValueError("代码需为 6 位数字")
    side = str(payload.get("side") or "").lower()
    if side not in ("buy", "sell"):
        raise ValueError("方向只能是 buy / sell")
    trigger_type = str(payload.get("trigger_type") or "price_below")
    if trigger_type not in TRIGGER_TYPES:
        raise ValueError(f"触发类型只能是 {'/'.join(TRIGGER_TYPES)}")
    try:
        trigger_value = float(payload.get("trigger_value") or 0)
        price = float(payload.get("price") or 0)
        shares = float(payload.get("shares") or 0)
    except (TypeError, ValueError):
        raise ValueError("触发值/价格/股数必须是数字") from None
    if trigger_value <= 0 or price <= 0 or shares <= 0:
        raise ValueError("触发值、价格、股数必须大于 0")
    mode = str(payload.get("mode") or "paper")
    if mode not in ("paper", "live"):
        raise ValueError("mode 只能是 paper / live")

    rows = await fetch_all(
        "SELECT id FROM conditional_orders WHERE user_id=? AND status='watching'",
        (current_user_id(),),
    )
    if len(rows) >= MAX_CONDITIONAL:
        raise ValueError(f"最多 {MAX_CONDITIONAL} 条观察中的条件单")

    cid = _new_id("cond")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO conditional_orders(user_id,id,symbol,name,side,trigger_type,"
            "trigger_value,price,shares,mode,status,note,triggered_at,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                current_user_id(),
                cid,
                symbol,
                str(payload.get("name") or "")[:40],
                side,
                trigger_type,
                round(trigger_value, 4),
                round(price, 4),
                round(shares, 4),
                mode,
                "watching",
                str(payload.get("note") or "")[:200],
                "",
                _now(),
            ),
        )
        await _mark_user_data(conn)
        await conn.commit()
    return await get_conditional(cid) or {}


async def get_conditional(cid: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM conditional_orders WHERE user_id=? AND id=?",
        (current_user_id(), cid),
    )
    return dict(row) if row else None


async def list_conditionals(status: str = "") -> list[dict[str, Any]]:
    params: list[Any] = [current_user_id()]
    sql = "SELECT * FROM conditional_orders WHERE user_id=?"
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    return await fetch_all(sql, tuple(params))


async def update_conditional_status(cid: str, status: str) -> dict[str, Any]:
    if status not in CONDITIONAL_STATUSES:
        raise ValueError(f"状态只能是 {'/'.join(CONDITIONAL_STATUSES)}")
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "UPDATE conditional_orders SET status=?, triggered_at=? WHERE user_id=? AND id=?",
            (status, _now() if status == "triggered" else "", current_user_id(), cid),
        )
        await conn.commit()
        if cur.rowcount == 0:
            raise ValueError("条件单不存在")
    return await get_conditional(cid) or {}


async def delete_conditional(cid: str) -> bool:
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "DELETE FROM conditional_orders WHERE user_id=? AND id=?",
            (current_user_id(), cid),
        )
        await conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# 风控设置
# ---------------------------------------------------------------------------

RISK_DEFAULTS = {
    "daily_limit": 200_000.0,
    "deviation_pct": 3.0,
    "concentration_pct": 30.0,
    "auto_execute_paper": 1,
}


async def get_risk_settings() -> dict[str, Any]:
    row = await fetch_one(
        "SELECT * FROM trade_risk_settings WHERE user_id=?", (current_user_id(),)
    )
    if not row:
        return dict(RISK_DEFAULTS)
    out = dict(RISK_DEFAULTS)
    # sqlite3.Row 没有 .get()：只能用 keys() 判断后再取（SIM118 的写法在这里不适用）
    keys = set(row.keys())
    out.update({k: row[k] for k in RISK_DEFAULTS if k in keys})
    out["updated_at"] = row["updated_at"] if "updated_at" in keys else ""
    return out


async def save_risk_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = await get_risk_settings()
    merged = {**current}
    for key in ("daily_limit", "deviation_pct", "concentration_pct"):
        if key in payload:
            try:
                merged[key] = float(payload[key])
            except (TypeError, ValueError):
                raise ValueError(f"{key} 必须是数字") from None
    if "auto_execute_paper" in payload:
        merged["auto_execute_paper"] = 1 if payload["auto_execute_paper"] else 0
    if merged["daily_limit"] < 0:
        raise ValueError("日限额不能为负")
    if not (0 <= merged["deviation_pct"] <= 100):
        raise ValueError("偏离阈值需在 0-100")
    if not (1 <= merged["concentration_pct"] <= 100):
        raise ValueError("集中度阈值需在 1-100")

    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO trade_risk_settings(user_id,daily_limit,deviation_pct,concentration_pct,"
            "auto_execute_paper,updated_at) VALUES(?,?,?,?,?,?)"
            " ON CONFLICT(user_id) DO UPDATE SET daily_limit=excluded.daily_limit,"
            " deviation_pct=excluded.deviation_pct, concentration_pct=excluded.concentration_pct,"
            " auto_execute_paper=excluded.auto_execute_paper, updated_at=excluded.updated_at",
            (
                current_user_id(),
                merged["daily_limit"],
                merged["deviation_pct"],
                merged["concentration_pct"],
                merged["auto_execute_paper"],
                _now(),
            ),
        )
        await conn.commit()
    return await get_risk_settings()
