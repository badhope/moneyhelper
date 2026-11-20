"""数据可移植域：全量导出/导入/月度趋势。

导入路径按域拆到：
- backup_restore_core.py   持仓/成员/借贷/家庭表决/流水/订阅/负债
- backup_restore_extra.py 预算/目标/定投/财报/记忆/观察/审计/纸面账户/净值
- backup_restore_prefs.py  MCP 服务器、用户偏好白名单、会话与问答历史
- backup_restore.py        复式总账/报销/采购/付款/银行对账等域还原组件
"""

from __future__ import annotations

from typing import Any

import aiosqlite

from ._core import _conn, get_write_lock
from .tenant import current_tenant_id, current_user_id


async def import_backup(data: dict[str, Any]) -> dict[str, int]:
    """把 export_data() 的 JSON 恢复进库：先清空业务表再写入。

    返回各表写入条数。settings 跳过 ai_api_key（安全），其余按 key 覆盖。
    """
    conn = await _conn()
    counts: dict[str, int] = {}
    # 多语句事务（先清表再逐表写入）：与批量入账共用写锁串行，
    # 否则并发写会在共享连接上互相破坏事务边界。
    async with get_write_lock():
        # autocommit 连接下必须显式开事务：这条路径先 DELETE 全租户数据再写回，
        # 没有事务边界时「恢复失败回滚」是空话——原数据已经被删掉了。
        await conn.execute("BEGIN IMMEDIATE")
        try:
            await _import_backup_locked(conn, data, counts)
            await conn.execute("COMMIT")
        except BaseException:
            try:
                await conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001 — 回滚失败不能掩盖原始异常
                pass
            raise
    return counts


async def _import_backup_locked(
    conn: aiosqlite.Connection, data: dict[str, Any], counts: dict[str, int]
) -> None:
    """import_backup 的实际写入段（调用方必须已持有写锁）。"""
    uid = current_user_id()
    tenant_id = current_tenant_id()
    try:
        for t in (
            "positions",
            "transactions",
            "subscriptions",
            "debts",
            "budgets",
            "goals",
            "user_memory",
            "runs",
            "sessions",
            "member_loans",
            "members",
            "watchlist",
            "provenance_log",
            "audit_logs",
            "attachments",
            "conversation_summary",
            "dept_reports",
            "invoices",
            "brokerage_imports",
            "conditional_orders",
            "trade_risk_settings",
            "family_motions",
            "family_votes",
            "allocation_targets",
            "dca_plans",
            "financial_statements",
            "paper_accounts",
            "paper_trades",
            "paper_snapshots",
            "net_worth_snapshots",
        ):
            # 只清当前租户：多租户下清全表会把别人的数据一起抹掉
            await conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))

        await _restore_core_tables(conn, data, counts, uid)
        await _restore_extra_tables(conn, data, counts, uid)

        # 复式总账：只有备份里出现 GL 字段才替换；旧备份不碰当前总账。
        entry_map: dict[int, int] = {}
        account_map: dict[int, int] = {}
        period_map: dict[int, int] = {}
        if any(
            k in data
            for k in ("gl_accounts", "gl_periods", "gl_entries", "gl_entry_lines")
        ):
            gl_counts, gl_maps = await _restore_gl(conn, data, tenant_id)
            counts.update(gl_counts)
            entry_map = gl_maps["entries"]
            account_map = gl_maps["accounts"]
            period_map = gl_maps["periods"]
        claim_map: dict[int, int] = {}
        if "expense_claims" in data:
            exp_counts, claim_map = await _restore_expenses(
                conn, data, tenant_id, entry_map
            )
            counts.update(exp_counts)
        # 采购/应付要先于付款恢复：付款要重映射 payable_id。
        payable_map: dict[int, int] = {}
        payable_payments: list[tuple[int, int]] = []
        if any(k in data for k in ("vendors", "purchase_orders", "payables")):
            proc_counts, payable_map, payable_payments = await _restore_procurement(
                conn, data, tenant_id, account_map, entry_map
            )
            counts.update(proc_counts)
        payment_map: dict[int, int] = {}
        if "payments" in data:
            pay_counts, payment_map = await _restore_payments(
                conn, data, tenant_id, claim_map, payable_map, entry_map, account_map
            )
            counts.update(pay_counts)
            # 应付单的 payment_id 是事后回填：付款先落库才能拿到新 id。
            for new_payable_id, old_payment_id in payable_payments:
                new_payment_id = payment_map.get(old_payment_id)
                if new_payment_id is None:
                    raise ValueError("应付单关联的付款引用缺失")
                await conn.execute(
                    "UPDATE payables SET payment_id=? WHERE tenant_id=? AND id=?",
                    (new_payment_id, int(tenant_id), int(new_payable_id)),
                )
        if "bank_transactions" in data:
            counts.update(
                await _restore_bank_transactions(
                    conn, data, tenant_id, payment_map, account_map
                )
            )
        if "bank_reconciliations" in data:
            counts.update(
                await _restore_bank_reconciliations(
                    conn, data, tenant_id, account_map, period_map
                )
            )

        await _restore_mcp_servers(data, counts)
        await _restore_settings(conn, data, counts, uid)
        await _restore_sessions_runs(conn, data, counts, uid)
    except Exception:  # noqa: BLE001 — 恢复失败由外层统一回滚，不留半截状态
        raise


# 导出侧已拆到 db/backup_export.py；各域还原组件在 backup_restore*.py。
from .backup_export import export_data, monthly_trend  # noqa: F401,E402 — 对外同名导出
from .backup_restore import (  # noqa: F401,E402 — 供 _import_backup_locked 调用
    _restore_bank_reconciliations,
    _restore_bank_transactions,
    _restore_expenses,
    _restore_gl,
    _restore_payments,
    _restore_procurement,
)
from .backup_restore_core import _restore_core_tables  # noqa: E402
from .backup_restore_extra import _restore_extra_tables  # noqa: E402
from .backup_restore_prefs import (  # noqa: E402
    _restore_mcp_servers,
    _restore_sessions_runs,
    _restore_settings,
)
