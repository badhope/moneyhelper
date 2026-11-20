"""凭证校验：借贷平衡、科目存在性、金额与摘要口径（写前必过）。"""

from __future__ import annotations

from typing import Any

from ..calculations.gl import assert_balanced, to_cents
from ._core import fetch_all
from .gl_accounts import _account_payload


async def _validate_lines(
    tenant_id: int, lines: Any
) -> tuple[list[dict[str, Any]], int]:
    assert_balanced(lines)
    # 一次取齐所有科目，避免逐行查询（凭证行数多时是 N 次往返）。
    wanted = {int(line.get("account_id") or 0) for line in lines}
    wanted.discard(0)
    accounts: dict[int, dict[str, Any]] = {}
    if wanted:
        placeholders = ",".join("?" * len(wanted))
        rows = await fetch_all(
            "SELECT id,tenant_id,code,name,type,parent_id,is_active,created_at"
            f" FROM gl_accounts WHERE tenant_id=? AND id IN ({placeholders})",
            (int(tenant_id), *sorted(wanted)),
        )
        accounts = {int(r["id"]): _account_payload(dict(r)) for r in rows}
    normalized: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, 1):
        account_id = int(line.get("account_id") or 0)
        account = accounts.get(account_id)
        if account is None or not account["is_active"]:
            raise ValueError(f"第 {idx} 行科目不存在或已停用")
        debit = to_cents(line.get("debit", 0))
        credit = to_cents(line.get("credit", 0))
        normalized.append(
            {
                "line_no": idx,
                "account_id": account_id,
                "debit_cents": debit,
                "credit_cents": credit,
                "memo": str(line.get("memo") or "")[:200],
            }
        )
    total = sum(x["debit_cents"] for x in normalized)
    return normalized, total
