"""同名持仓合并：把多条同名记录并为一条，金额与股数相加。"""

from __future__ import annotations

import json
from typing import Any

from ._core import (
    _mark_user_data,
)
from .tenant import current_user_id
from .undo import _record_snapshot


async def merge_positions_by_name(name: str) -> dict[str, Any]:
    """同名不同 symbol 的持仓合并成一条：保留最早录入那条的 symbol，
    股数求和、成本/现价/费用加权平均。返回合并掉的条数。"""
    nm = str(name).strip()
    if not nm:
        raise ValueError("名称不能为空")
    from ._core import write_txn

    async with write_txn() as conn:
        # 合并快照需要全量字段，以备撤回时按 symbol 完整恢复每一行
        cur = await conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND name=? ORDER BY symbol",
            (current_user_id(), nm),
        )
        old_rows = [dict(r) for r in await cur.fetchall()]
        if len(old_rows) <= 1:
            return {"ok": True, "merged": 0}

        # 撤销快照：为合并涉及的所有行各存一份完整旧行 JSON，撤回时按 symbol 各自 INSERT OR REPLACE
        for r in old_rows:
            await _record_snapshot(
                "position", r["symbol"], json.dumps(r, ensure_ascii=False, default=str)
            )

        rows = [
            {
                "symbol": r["symbol"],
                "shares": r["shares"],
                "cost": r["cost"],
                "last": r["last"],
                "fee": r["fee"],
            }
            for r in old_rows
        ]

        # 保留最早录入那条（created_at 最小 / symbol 字典序最小兜底），其余合并进它
        keep = rows[0]
        total_shares = sum(r["shares"] for r in rows if r["shares"] > 0)
        if total_shares <= 0:
            total_shares = keep["shares"]

        # 成本/现价/费用按股数加权平均（share=0 的条目权重取 1）
        def _wavg(field: str) -> float:
            num = 0.0
            den = 0.0
            for r in rows:
                w = r["shares"] if r["shares"] > 0 else 1.0
                num += r[field] * w
                den += w
            return round(num / den, 6) if den else 0.0

        merged_cost = _wavg("cost")
        merged_last = _wavg("last")
        # 佣金（fee）是每笔持仓的总额，合并时求和而非加权平均
        merged_fee = round(sum(r["fee"] for r in rows), 6)

        await conn.execute(
            "UPDATE positions SET shares=?, cost=?, last=?, fee=?"
            " WHERE user_id=? AND symbol=?",
            (
                total_shares,
                merged_cost,
                merged_last,
                merged_fee,
                current_user_id(),
                keep["symbol"],
            ),
        )
        for r in rows[1:]:
            await conn.execute(
                "DELETE FROM positions WHERE user_id=? AND symbol=?",
                (current_user_id(), r["symbol"]),
            )
        await _mark_user_data(conn)
        return {"ok": True, "merged": len(rows) - 1, "symbol": keep["symbol"]}
