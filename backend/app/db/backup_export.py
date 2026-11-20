"""全量导出与月度趋势（备份的只读一侧）。

从 db/backup.py 拆出；导入侧（含各域还原组件）仍在 backup.py，备份格式不变。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ._core import (
    fetch_all,
    get_settings,
    list_debts,
    list_positions,
    list_subscriptions,
    list_transactions,
)
from .history import list_sessions
from .tenant import current_tenant_id, current_user_id


async def export_data() -> dict[str, Any]:
    """全量导出（备份）：持仓 / 流水 / 订阅 / 负债 / 预算 / 目标 / 长期记忆 / 设置 / 会话 / 问答。"""
    runs = await fetch_all(
        "SELECT * FROM runs WHERE user_id=? ORDER BY id", (current_user_id(),)
    )
    for r in runs:
        try:
            r["flags"] = json.loads(r.pop("flags_json") or "[]")
        except Exception:
            r["flags"] = []
        try:
            r["tools"] = json.loads(r.pop("tools") or "[]")
        except Exception:
            r["tools"] = []
        try:
            r["actions"] = json.loads(r.pop("actions") or "[]")
        except Exception:
            r["actions"] = []
    settings = await get_settings()
    # 备份文件可能被分享/上传：AI Key 不落明文（恢复时在设置页重新填写）
    if settings.get("ai_api_key"):
        settings["ai_api_key"] = "********"
    return {
        "version": 3,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "positions": await list_positions(),
        "transactions": await list_transactions(),
        "subscriptions": await list_subscriptions(),
        "debts": await list_debts(),
        "budgets": await fetch_all(
            "SELECT * FROM budgets WHERE user_id=? ORDER BY month, category",
            (current_user_id(),),
        ),
        "goals": await fetch_all(
            "SELECT * FROM goals WHERE user_id=? ORDER BY name", (current_user_id(),)
        ),
        "memory": await fetch_all(
            "SELECT * FROM user_memory WHERE user_id=? ORDER BY id",
            (current_user_id(),),
        ),
        "settings": settings,
        # MCP 服务器清单（含 stdio 命令与启停状态）存在 data/mcp.json，不在 settings 表里；
        # 不单独导出的话，恢复后 Studio 市场装的 MCP 与用户自建服务器全部消失。
        "mcp_servers": _export_mcp_servers(),
        "sessions": await list_sessions(),
        "runs": runs,
        # 家庭/协作数据：漏掉这些表会导致恢复后"成员消失、流水失去归属"
        "members": await fetch_all(
            "SELECT * FROM members WHERE user_id=? ORDER BY id", (current_user_id(),)
        ),
        "member_loans": await fetch_all(
            "SELECT * FROM member_loans WHERE user_id=? ORDER BY id",
            (current_user_id(),),
        ),
        # 家庭议案/投票、再平衡目标、定投计划、财报分析：此前不在导出范围，
        # 换机/迁移后会静默丢失。全部为租户表，恢复时统一落到当前用户名下。
        "family_motions": await fetch_all(
            "SELECT * FROM family_motions WHERE user_id=? ORDER BY id",
            (current_user_id(),),
        ),
        "family_votes": await fetch_all(
            "SELECT * FROM family_votes WHERE user_id=? ORDER BY motion_id, member_id",
            (current_user_id(),),
        ),
        "allocation_targets": await fetch_all(
            "SELECT * FROM allocation_targets WHERE user_id=? ORDER BY symbol",
            (current_user_id(),),
        ),
        "dca_plans": await fetch_all(
            "SELECT * FROM dca_plans WHERE user_id=? ORDER BY id",
            (current_user_id(),),
        ),
        "financial_statements": await fetch_all(
            "SELECT * FROM financial_statements WHERE user_id=? ORDER BY created_at",
            (current_user_id(),),
        ),
        "watchlist": await fetch_all(
            "SELECT * FROM watchlist WHERE user_id=? ORDER BY symbol",
            (current_user_id(),),
        ),
        # 审计与溯源链：备份要能支撑"恢复后仍可追责"
        "provenance": await fetch_all(
            "SELECT * FROM provenance_log WHERE user_id=? ORDER BY id",
            (current_user_id(),),
        ),
        "audit": await fetch_all(
            "SELECT * FROM audit_logs WHERE user_id=? ORDER BY id", (current_user_id(),)
        ),
        # 附件 / 会话摘要 / 部门呈批件：漏掉会导致恢复后知识库、会话上下文、
        # 呈批历史整体消失（三者均为租户表，user_id 由迁移保证存在）
        "attachments": await fetch_all(
            "SELECT * FROM attachments WHERE user_id=? ORDER BY id",
            (current_user_id(),),
        ),
        "conversation_summary": await fetch_all(
            "SELECT * FROM conversation_summary WHERE user_id=? ORDER BY thread_id",
            (current_user_id(),),
        ),
        "dept_reports": await fetch_all(
            "SELECT * FROM dept_reports WHERE user_id=? ORDER BY id",
            (current_user_id(),),
        ),
        # 连接中心深化（v4.5）：发票归档 / 对账单导入记录 / 条件单 / 风控设置
        "invoices": await fetch_all(
            "SELECT * FROM invoices WHERE user_id=? ORDER BY created_at", (current_user_id(),)
        ),
        "brokerage_imports": await fetch_all(
            "SELECT * FROM brokerage_imports WHERE user_id=? ORDER BY created_at",
            (current_user_id(),),
        ),
        "conditional_orders": await fetch_all(
            "SELECT * FROM conditional_orders WHERE user_id=? ORDER BY created_at",
            (current_user_id(),),
        ),
        "trade_risk_settings": await fetch_all(
            "SELECT * FROM trade_risk_settings WHERE user_id=?", (current_user_id(),)
        ),
        # 模拟盘与净值曲线：没有它们，恢复后历史净值/持仓表现全部断档。
        "paper_accounts": await fetch_all(
            "SELECT * FROM paper_accounts WHERE user_id=? ORDER BY account_id",
            (current_user_id(),),
        ),
        "paper_trades": await fetch_all(
            "SELECT * FROM paper_trades WHERE user_id=? ORDER BY id",
            (current_user_id(),),
        ),
        "paper_snapshots": await fetch_all(
            "SELECT * FROM paper_snapshots WHERE user_id=? ORDER BY id",
            (current_user_id(),),
        ),
        "net_worth_snapshots": await fetch_all(
            "SELECT * FROM net_worth_snapshots WHERE user_id=? ORDER BY date",
            (current_user_id(),),
        ),
        # 复式总账（切片 4）：按 tenant_id 导出，恢复时重映射内部 ID。
        "gl_accounts": await fetch_all(
            "SELECT * FROM gl_accounts WHERE tenant_id=? ORDER BY id",
            (current_tenant_id(),),
        ),
        "gl_periods": await fetch_all(
            "SELECT * FROM gl_periods WHERE tenant_id=? ORDER BY id",
            (current_tenant_id(),),
        ),
        "gl_entries": await fetch_all(
            "SELECT * FROM gl_entries WHERE tenant_id=? ORDER BY id",
            (current_tenant_id(),),
        ),
        "gl_entry_lines": await fetch_all(
            "SELECT * FROM gl_entry_lines WHERE tenant_id=? ORDER BY id",
            (current_tenant_id(),),
        ),
        "expense_claims": await fetch_all(
            "SELECT * FROM expense_claims WHERE tenant_id=? ORDER BY id",
            (current_tenant_id(),),
        ),
        "payments": await fetch_all(
            "SELECT * FROM payments WHERE tenant_id=? ORDER BY id",
            (current_tenant_id(),),
        ),
        # 采购/应付（切片 8）：供应商 → 采购单 → 应付单
        "vendors": await fetch_all(
            "SELECT * FROM vendors WHERE tenant_id=? ORDER BY id",
            (current_tenant_id(),),
        ),
        "purchase_orders": await fetch_all(
            "SELECT * FROM purchase_orders WHERE tenant_id=? ORDER BY id",
            (current_tenant_id(),),
        ),
        "payables": await fetch_all(
            "SELECT * FROM payables WHERE tenant_id=? ORDER BY id",
            (current_tenant_id(),),
        ),
        "bank_transactions": await fetch_all(
            "SELECT * FROM bank_transactions WHERE tenant_id=? ORDER BY id",
            (current_tenant_id(),),
        ),
        "bank_reconciliations": await fetch_all(
            "SELECT * FROM bank_reconciliations WHERE tenant_id=? ORDER BY id",
            (current_tenant_id(),),
        ),
    }


def _export_mcp_servers() -> list[dict[str, Any]]:
    """导出 MCP 配置（凭据一律打码：备份文件可能被分享/上传）。

    两处会带凭据：
    - `url` 里的 `user:token@host`
    - `env` 里的 API Key（如 GITHUB_TOKEN / ZOTERO_API_KEY）
    只保留键名、把值替换成 ***，恢复后由用户重新填写。
    """
    try:
        from .. import mcp_client

        out = []
        for s in mcp_client.raw_servers():
            entry = dict(s)
            if entry.get("url"):
                entry["url"] = mcp_client.redact_url(str(entry["url"]))
            if isinstance(entry.get("env"), dict):
                entry["env"] = {k: "***" for k in entry["env"]}
            out.append(entry)
        return out
    except Exception:  # noqa: BLE001 — MCP 配置读取失败不应让备份整体失败
        return []


async def monthly_trend(months: int = 6) -> list[dict[str, Any]]:
    """按自然月聚合流水：收入 / 支出 / 结余（含当前月，最近 N 个月）。"""
    rows = await fetch_all(
        "SELECT substr(date,1,7) AS month,"
        " SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS income,"
        " SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS expense,"
        " SUM(amount) AS net"
        " FROM transactions WHERE user_id=? GROUP BY month ORDER BY month DESC LIMIT ?",
        (current_user_id(), int(months)),
    )
    return [dict(r) for r in reversed(rows)]
