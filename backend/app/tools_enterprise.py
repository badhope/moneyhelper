"""企业域只读工具（从 tools.py 拆出，控制单文件体量）。

边界：这里只放**只读**工具。企业域写操作（建凭证/采购/应付、审批、付款）
需要审批链与人工签字，不暴露给模型自执行——模型只能「看」，不能「改账」。
租户由 current_tenant_id() 决定，与 HTTP / MCP 侧同一口径。
"""

from __future__ import annotations

import json
from typing import Any

from . import db

# ---------------------------------------------------------------------------
# 企业域只读工具（切片 12）：让应用内对话 agent 也能回答企业财务问题
#
# 边界：这里只放**只读**工具。企业域写操作（建凭证/采购/应付、审批、付款）
# 需要审批链与人工签字，不暴露给模型自执行——模型只能「看」，不能「改账」。
# 租户由 current_tenant_id() 决定，与 HTTP / MCP 侧同一口径。
# ---------------------------------------------------------------------------


def _ent_tenant() -> int:
    from .db.tenant import current_tenant_id

    return current_tenant_id()


async def tool_get_gl_summary(_args: dict[str, Any]) -> str:
    """查总账概览：科目数、期间、最近凭证与借贷是否平衡。"""
    tid = _ent_tenant()
    accounts = await db.gl_list_accounts(tid)
    periods = await db.gl_list_periods(tid)
    entries = await db.gl_list_entries(tid, None, 10)
    latest_period = periods[-1] if periods else None
    trial: dict[str, Any] | None = None
    if latest_period:
        try:
            trial = await db.gl_trial_balance(tid, int(latest_period["id"]))
        except Exception:  # noqa: BLE001 — 空期间没有试算表，不是错误
            trial = None
    return json.dumps(
        {
            "accounts": [
                {"code": a["code"], "name": a["name"], "type": a["type"]}
                for a in accounts[:40]
            ],
            "account_count": len(accounts),
            "periods": [
                {"id": p["id"], "year": p["year"], "month": p["month"], "status": p["status"]}
                for p in periods[-6:]
            ],
            "recent_entries": [
                {
                    "entry_no": e.get("entry_no"),
                    "date": e.get("entry_date"),
                    "description": e.get("description"),
                    "status": e.get("status"),
                }
                for e in entries
            ],
            "latest_trial_balance": (
                {
                    "total_debit": trial.get("total_debit"),
                    "total_credit": trial.get("total_credit"),
                    "balanced": trial.get("balanced"),
                }
                if trial
                else None
            ),
        },
        ensure_ascii=False,
    )


async def tool_get_payables_summary(_args: dict[str, Any]) -> str:
    """查应付与采购：供应商数、未付款应付、即将到期、采购单状态分布。"""
    tid = _ent_tenant()
    vendors = await db.vendor_list(tid)
    orders = await db.po_list(tid)
    payables = await db.payable_list(tid)
    unpaid = [p for p in payables if p.get("status") != "paid"]
    total_unpaid = sum(float(p.get("amount") or 0) for p in unpaid)
    return json.dumps(
        {
            "vendor_count": len(vendors),
            "purchase_orders": {
                "total": len(orders),
                "draft": sum(1 for o in orders if o.get("status") == "draft"),
                "submitted": sum(1 for o in orders if o.get("status") == "submitted"),
                "approved": sum(1 for o in orders if o.get("status") == "approved"),
            },
            "payables": {
                "total": len(payables),
                "unpaid": len(unpaid),
                "unpaid_amount": round(total_unpaid, 2),
                "overdue": [
                    {"payable_no": p.get("payable_no"), "due_date": p.get("due_date"),
                     "amount": p.get("amount")}
                    for p in unpaid
                    if p.get("due_date") and str(p["due_date"]) < __import__("time").strftime("%Y-%m-%d")
                ][:20],
            },
        },
        ensure_ascii=False,
    )


async def tool_get_expense_queue(_args: dict[str, Any]) -> str:
    """查报销队列：待审核报销单数量、金额、申请人。"""
    tid = _ent_tenant()
    claims = await db.expense_list_claims(tid, None)
    pending = [c for c in claims if c.get("status") in ("submitted", "approving")]
    return json.dumps(
        {
            "total": len(claims),
            "pending": len(pending),
            "pending_amount": round(sum(float(c.get("amount") or 0) for c in pending), 2),
            "items": [
                {
                    "claim_no": c.get("claim_no"),
                    "title": c.get("title"),
                    "amount": c.get("amount"),
                    "status": c.get("status"),
                }
                for c in pending[:20]
            ],
        },
        ensure_ascii=False,
    )


async def tool_get_org_overview(_args: dict[str, Any]) -> str:
    """查组织概览：部门、岗位、成员数量与当前角色。"""
    from .db import org

    tid = _ent_tenant()
    data = await org.org_overview(tid)
    return json.dumps(
        {
            "tenant_id": tid,
            "departments": [d["name"] for d in (data.get("departments") or [])],
            "positions": [p["name"] for p in (data.get("positions") or [])],
            "member_count": len(data.get("members") or []),
            "counts": data.get("counts"),
        },
        ensure_ascii=False,
    )


async def tool_list_longtasks(_args: dict[str, Any]) -> str:
    """查长任务：标题、类型、进度、状态。"""
    from . import longtask

    return json.dumps({"tasks": longtask.list_tasks(limit=20)}, ensure_ascii=False)
