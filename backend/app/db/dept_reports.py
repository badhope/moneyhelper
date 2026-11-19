"""部门呈批件存储（M3.5）：呈批件的落库与审批状态流转。

## 为什么要落库

部门模式跑一轮要几秒到几十秒（四个 agent 并行）。如果呈批件只在
HTTP 响应里返回，老板离开页面就丢了——而"呈批"这个动作本身就是
"我稍后再看/我要认真看"。所以呈批件必须持久化，并能跨请求、跨重启审批。

## 状态机

    pending ──approve──→ approved
       │
       ├──reject(note)──→ rejected   （附理由，可带 note 要求重跑）
       └──inquire(note)─→ inquired   （追问：把问题转给指定部门再跑）

`inquired` 是终态：追问会产生**一份新的呈批件**（带上追问内容重跑），
原呈批件保留为历史。这样审批链完整可查，不会被覆盖。

## 审计

每次状态变更都写 provenance（action=dept_report_<decision>），
老板的决策与数字产出在同一条审计链上——这是"可复核"的一部分。
"""

from __future__ import annotations

import json
from typing import Any

from ..timeutil import now_iso as _now_iso
from ._core import _conn, fetch_all, fetch_one, uuid_hex
from .tenant import current_user_id

# 允许的审批动作
DECISIONS = ("approve", "reject", "inquire")

_STATUS_BY_DECISION = {
    "approve": "approved",
    "reject": "rejected",
    "inquire": "inquired",
}




def _row_to_report(row: Any) -> dict[str, Any]:
    out = dict(row)
    for src, dst in (("orders_json", "orders"), ("conflicts_json", "conflicts")):
        raw = out.pop(src, "[]")
        try:
            out[dst] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            out[dst] = []
    return out


async def save_report(
    question: str,
    report: dict[str, Any],
    dispatch: str = "",
) -> str:
    """保存一份呈批件，返回 report_id。"""
    report_id = uuid_hex()[:16]
    conn = await _conn()
    await conn.execute(
        "INSERT INTO dept_reports("
        " user_id, report_id, question, dispatch, verdict, report, orders_json,"
        " conflicts_json, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            current_user_id(),
            report_id,
            question,
            dispatch or str(report.get("dispatch") or ""),
            str(report.get("verdict") or ""),
            str(report.get("report") or ""),
            json.dumps(report.get("orders") or [], ensure_ascii=False),
            json.dumps(report.get("conflicts") or [], ensure_ascii=False),
            "pending",
            _now_iso(),
        ),
    )
    await conn.commit()
    return report_id


async def get_report(report_id: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM dept_reports WHERE user_id=? AND report_id=?",
        (current_user_id(), report_id),
    )
    return _row_to_report(row) if row else None


async def list_reports(
    status: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """列出呈批件（最新在前）。status 为空则全部。"""
    limit = max(1, min(int(limit), 200))
    if status:
        rows = await fetch_all(
            "SELECT * FROM dept_reports WHERE user_id=? AND status=?"
            " ORDER BY id DESC LIMIT ?",
            (current_user_id(), status, limit),
        )
    else:
        rows = await fetch_all(
            "SELECT * FROM dept_reports WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (current_user_id(), limit),
        )
    return [_row_to_report(r) for r in rows]


async def decide(
    report_id: str, decision: str, note: str = ""
) -> dict[str, Any] | None:
    """对呈批件做审批。返回更新后的记录；不存在或非 pending 返回 None。

    用条件 UPDATE（WHERE status='pending'）保证幂等与并发安全：
    两个请求同时批准时只有一个生效，另一个拿到 None。
    """
    if decision not in DECISIONS:
        raise ValueError(f"未知审批动作：{decision}")
    new_status = _STATUS_BY_DECISION[decision]
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE dept_reports SET status=?, decision_note=?, decided_at=?"
        " WHERE user_id=? AND report_id=? AND status='pending'",
        (new_status, note[:1000], _now_iso(), current_user_id(), report_id),
    )
    await conn.commit()
    if cur.rowcount != 1:
        return None
    return await get_report(report_id)


async def pending_count() -> int:
    row = await fetch_one(
        "SELECT COUNT(*) AS n FROM dept_reports WHERE user_id=? AND status='pending'",
        (current_user_id(),),
    )
    return int(row["n"]) if row else 0
