"""收支归因确认持久化（4.17.1）：只记录用户确认结果与依据，不改写金额。"""

from __future__ import annotations

import json
from typing import Any

from ..timeutil import new_id, now_iso
from ._core import fetch_all, fetch_one, write_txn
from .undo import _record_snapshot


def _decode(row: Any) -> dict[str, Any]:
    out = dict(row)
    try:
        out["matched"] = json.loads(out.pop("matched_json") or "[]")
    except (TypeError, ValueError):
        out["matched"] = []
    return out


async def list_confirmations(tenant_id: int, user_id: int) -> dict[int, dict[str, Any]]:
    rows = await fetch_all(
        "SELECT transaction_id,original_category,confirmed_category,source,rule_id,"
        "confidence,matched_json,confirmed_at,updated_at"
        " FROM attribution_confirmations WHERE tenant_id=? AND user_id=?"
        " ORDER BY confirmed_at DESC LIMIT 500",
        (int(tenant_id), int(user_id)),
    )
    return {int(r["transaction_id"]): _decode(r) for r in rows}


async def get_confirmation(
    tenant_id: int, user_id: int, transaction_id: int
) -> dict[str, Any] | None:
    rows = await fetch_all(
        "SELECT transaction_id,original_category,confirmed_category,source,rule_id,"
        "confidence,matched_json,confirmed_at,updated_at"
        " FROM attribution_confirmations"
        " WHERE tenant_id=? AND user_id=? AND transaction_id=?",
        (int(tenant_id), int(user_id), int(transaction_id)),
    )
    return _decode(rows[0]) if rows else None


async def get_transaction(user_id: int, transaction_id: int) -> dict[str, Any] | None:
    """读当前用户的一条流水；不存在返回 None，不把 0 当默认。"""
    row = await fetch_one(
        "SELECT id,date,item,category,amount FROM transactions WHERE user_id=? AND id=?",
        (int(user_id), int(transaction_id)),
    )
    return dict(row) if row else None


async def list_confirmed_rows(
    tenant_id: int, user_id: int, limit: int = 20
) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT c.transaction_id,c.original_category,c.confirmed_category,c.source,"
        "c.rule_id,c.confidence,c.confirmed_at,t.date,t.item,t.amount"
        " FROM attribution_confirmations c"
        " JOIN transactions t ON t.id=c.transaction_id AND t.user_id=c.user_id"
        " WHERE c.tenant_id=? AND c.user_id=?"
        " ORDER BY c.confirmed_at DESC LIMIT ?",
        (int(tenant_id), int(user_id), max(1, min(int(limit), 50))),
    )
    return [dict(r) for r in rows]


async def upsert_confirmation(
    *,
    tenant_id: int,
    user_id: int,
    transaction_id: int,
    original_category: str,
    confirmed_category: str,
    source: str,
    rule_id: str,
    confidence: float,
    matched: list[str],
) -> dict[str, Any]:
    now = now_iso()
    async with write_txn() as conn:
        await conn.execute(
            "INSERT INTO attribution_confirmations"
            "(tenant_id,user_id,transaction_id,original_category,confirmed_category,source,"
            "rule_id,confidence,matched_json,confirmed_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(tenant_id,user_id,transaction_id) DO UPDATE SET"
            " original_category=excluded.original_category,"
            " confirmed_category=excluded.confirmed_category,"
            " source=excluded.source,rule_id=excluded.rule_id,"
            " confidence=excluded.confidence,matched_json=excluded.matched_json,"
            " updated_at=excluded.updated_at",
            (
                int(tenant_id),
                int(user_id),
                int(transaction_id),
                str(original_category or ""),
                str(confirmed_category or ""),
                str(source or "rule"),
                str(rule_id or ""),
                float(confidence or 0),
                json.dumps(matched or [], ensure_ascii=False),
                now,
                now,
            ),
        )
    return {
        "transaction_id": int(transaction_id),
        "original_category": str(original_category or ""),
        "confirmed_category": str(confirmed_category or ""),
        "source": str(source or "rule"),
        "rule_id": str(rule_id or ""),
        "confidence": float(confidence or 0),
        "matched": list(matched or []),
        "confirmed_at": now,
        "updated_at": now,
    }




async def list_rules(tenant_id: int, user_id: int, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    sql = (
        "SELECT rule_id,name,keyword,category,direction,priority,merchant,"
        "min_amount_cents,max_amount_cents,member_id,enabled,created_at,updated_at"
        " FROM attribution_rules WHERE tenant_id=? AND user_id=?"
    )
    if enabled_only:
        sql += " AND enabled=1"
    sql += " ORDER BY enabled DESC, priority DESC, created_at ASC LIMIT 50"
    rows = await fetch_all(sql, (int(tenant_id), int(user_id)))
    return [dict(r) for r in rows]


async def create_rule(
    *,
    tenant_id: int,
    user_id: int,
    name: str,
    keyword: str,
    category: str,
    direction: str,
    priority: int,
    merchant: str = "",
    min_amount_cents: int = 0,
    max_amount_cents: int = 0,
    member_id: int | None = None,
) -> dict[str, Any]:
    now = now_iso()
    rule_id = new_id("ar_")
    async with write_txn() as conn:
        await conn.execute(
            "INSERT INTO attribution_rules"
            "(tenant_id,user_id,rule_id,name,keyword,category,direction,priority,"
            "merchant,min_amount_cents,max_amount_cents,member_id,enabled,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
            (
                int(tenant_id), int(user_id), rule_id, name, keyword, category,
                direction, int(priority), merchant, int(min_amount_cents),
                int(max_amount_cents), member_id, now, now,
            ),
        )
    return {
        "rule_id": rule_id, "name": name, "keyword": keyword, "category": category,
        "direction": direction, "priority": int(priority), "merchant": merchant,
        "min_amount_cents": int(min_amount_cents),
        "max_amount_cents": int(max_amount_cents),
        "member_id": member_id, "enabled": 1, "created_at": now, "updated_at": now,
    }


async def update_rule(
    tenant_id: int,
    user_id: int,
    rule_id: str,
    *,
    name: str | None = None,
    keyword: str | None = None,
    category: str | None = None,
    direction: str | None = None,
    priority: int | None = None,
    enabled: bool | None = None,
    merchant: str | None = None,
    min_amount_cents: int | None = None,
    max_amount_cents: int | None = None,
    member_id: int | None = None,
) -> dict[str, Any] | None:
    current = await fetch_one(
        "SELECT rule_id,name,keyword,category,direction,priority,merchant,"
        "min_amount_cents,max_amount_cents,member_id,enabled,created_at"
        " FROM attribution_rules WHERE tenant_id=? AND user_id=? AND rule_id=?",
        (int(tenant_id), int(user_id), str(rule_id)),
    )
    if current is None:
        return None
    row = dict(current)
    merged = {
        "name": row["name"] if name is None else name,
        "keyword": row["keyword"] if keyword is None else keyword,
        "category": row["category"] if category is None else category,
        "direction": row["direction"] if direction is None else direction,
        "priority": int(row["priority"] if priority is None else priority),
        "merchant": str(row.get("merchant") or "") if merchant is None else merchant,
        "min_amount_cents": int(row.get("min_amount_cents") or 0) if min_amount_cents is None else int(min_amount_cents),
        "max_amount_cents": int(row.get("max_amount_cents") or 0) if max_amount_cents is None else int(max_amount_cents),
        "member_id": row.get("member_id") if member_id is None else (None if int(member_id) == 0 else int(member_id)),
        "enabled": int(row["enabled"] if enabled is None else (1 if enabled else 0)),
        "updated_at": now_iso(),
    }
    async with write_txn() as conn:
        await conn.execute(
            "UPDATE attribution_rules SET name=?,keyword=?,category=?,direction=?,"
            "priority=?,merchant=?,min_amount_cents=?,max_amount_cents=?,member_id=?,"
            "enabled=?,updated_at=? WHERE tenant_id=? AND user_id=? AND rule_id=?",
            (
                merged["name"], merged["keyword"], merged["category"], merged["direction"],
                merged["priority"], merged["merchant"], merged["min_amount_cents"],
                merged["max_amount_cents"], merged["member_id"], merged["enabled"],
                merged["updated_at"], int(tenant_id), int(user_id), str(rule_id),
            ),
        )
    return {**row, **merged}


async def delete_rule(tenant_id: int, user_id: int, rule_id: str) -> bool:
    async with write_txn() as conn:
        cur = await conn.execute(
            "DELETE FROM attribution_rules WHERE tenant_id=? AND user_id=? AND rule_id=?",
            (int(tenant_id), int(user_id), str(rule_id)),
        )
    return bool(cur.rowcount)


async def batch_apply_confirmations(
    *,
    tenant_id: int,
    user_id: int,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """批量写回分类并落确认记录；任何一个流水变动都会整批回滚。"""
    now = now_iso()
    written: list[dict[str, Any]] = []
    async with write_txn() as conn:
        for item in items:
            tx_id = int(item["transaction_id"])
            cur = await conn.execute(
                "SELECT date,item,category,amount,owner_id,is_shared FROM transactions"
                " WHERE user_id=? AND id=?",
                (int(user_id), tx_id),
            )
            row = await cur.fetchone()
            if row is None:
                raise ValueError(f"流水 {tx_id} 不存在")
            old = dict(row)
            if str(old.get("category") or "") != str(item["original_category"]):
                raise ValueError(f"流水 {tx_id} 分类已变化，请刷新后重试")
            await _record_snapshot(
                "transaction", str(tx_id),
                json.dumps({"id": tx_id, **old}, ensure_ascii=False),
            )
            await conn.execute(
                "UPDATE transactions SET category=? WHERE user_id=? AND id=?",
                (str(item["confirmed_category"]), int(user_id), tx_id),
            )
            await conn.execute(
                "INSERT INTO attribution_confirmations"
                "(tenant_id,user_id,transaction_id,original_category,confirmed_category,source,"
                "rule_id,confidence,matched_json,confirmed_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(tenant_id,user_id,transaction_id) DO UPDATE SET"
                " original_category=excluded.original_category,"
                " confirmed_category=excluded.confirmed_category,"
                " source=excluded.source,rule_id=excluded.rule_id,"
                " confidence=excluded.confidence,matched_json=excluded.matched_json,"
                " confirmed_at=excluded.confirmed_at,updated_at=excluded.updated_at",
                (
                    int(tenant_id), int(user_id), tx_id,
                    str(item["original_category"]), str(item["confirmed_category"]),
                    str(item["source"]), str(item["rule_id"]), float(item["confidence"]),
                    json.dumps(item["matched"], ensure_ascii=False), now, now,
                ),
            )
            written.append(
                {
                    "transaction_id": tx_id,
                    "previous_category": str(item["original_category"]),
                    "category": str(item["confirmed_category"]),
                    "source": str(item["source"]),
                    "rule_id": str(item["rule_id"]),
                    "confidence": float(item["confidence"]),
                    "matched": list(item["matched"]),
                    "confirmed_at": now,
                }
            )
    return written


async def rollback_confirmation(
    *,
    tenant_id: int,
    user_id: int,
    transaction_id: int,
) -> dict[str, Any]:
    """回滚一次确认：恢复原分类、删除确认、单独保留回滚证据。"""
    conf = await get_confirmation(tenant_id, user_id, transaction_id)
    if conf is None:
        raise ValueError("该流水没有可回滚的归因确认")
    async with write_txn() as conn:
        cur = await conn.execute(
            "SELECT date,item,category,amount,owner_id,is_shared FROM transactions"
            " WHERE user_id=? AND id=?",
            (int(user_id), int(transaction_id)),
        )
        row = await cur.fetchone()
        if row is None:
            raise ValueError(f"流水 {transaction_id} 不存在")
        old = dict(row)
        if str(old.get("category") or "") != str(conf["confirmed_category"]):
            raise ValueError("流水分类已被改动，拒绝用旧确认覆盖")
        original = str(conf.get("original_category") or "其他") or "其他"
        await _record_snapshot(
            "transaction", str(transaction_id),
            json.dumps({"id": int(transaction_id), **old}, ensure_ascii=False),
        )
        await conn.execute(
            "UPDATE transactions SET category=? WHERE user_id=? AND id=?",
            (original, int(user_id), int(transaction_id)),
        )
        await conn.execute(
            "DELETE FROM attribution_confirmations"
            " WHERE tenant_id=? AND user_id=? AND transaction_id=?",
            (int(tenant_id), int(user_id), int(transaction_id)),
        )
        now = now_iso()
        await conn.execute(
            "INSERT INTO attribution_rollbacks"
            "(id,tenant_id,user_id,transaction_id,original_category,confirmed_category,"
            "source,rule_id,reverted_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                new_id("rb_"), int(tenant_id), int(user_id), int(transaction_id),
                original, str(conf["confirmed_category"]), str(conf["source"]),
                str(conf["rule_id"]), now, now,
            ),
        )
    return {
        "ok": True,
        "transaction_id": int(transaction_id),
        "restored_category": original,
        "reverted_category": str(conf["confirmed_category"]),
        "source": str(conf["source"]),
        "rule_id": str(conf["rule_id"]),
        "reverted_at": now,
    }


async def confirmation_stats(tenant_id: int, user_id: int) -> dict[str, Any]:
    grouped = await fetch_all(
        "SELECT source,rule_id,COUNT(*) AS n FROM attribution_confirmations"
        " WHERE tenant_id=? AND user_id=? GROUP BY source,rule_id",
        (int(tenant_id), int(user_id)),
    )
    reverted = await fetch_all(
        "SELECT rule_id,COUNT(*) AS n FROM attribution_rollbacks"
        " WHERE tenant_id=? AND user_id=? GROUP BY rule_id",
        (int(tenant_id), int(user_id)),
    )
    return {
        "by_rule": [dict(r) for r in grouped],
        "reverted_by_rule": [dict(r) for r in reverted],
    }


__all__ = [
    "batch_apply_confirmations", "confirmation_stats", "create_rule", "delete_rule",
    "get_confirmation", "list_confirmations", "list_confirmed_rows", "list_rules",
    "rollback_confirmation",
    "update_rule", "upsert_confirmation",
]
