"""收支归因确认持久化（4.17.1）：只记录用户确认结果与依据，不改写金额。"""

from __future__ import annotations

import json
from typing import Any

from ..timeutil import now_iso
from ._core import fetch_all, fetch_one, write_txn


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


__all__ = ["get_confirmation", "list_confirmations", "upsert_confirmation"]
