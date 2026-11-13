"""数据可移植域：全量导出/导入/月度趋势。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import aiosqlite

from ._core import (  # noqa: F401
    _conn,
    _ensure_defaults,  # noqa: F401
    _mark_user_data,
    fetch_all,
    get_settings,
    get_write_lock,
    list_debts,
    list_positions,
    list_subscriptions,
    list_transactions,
)
from .history import list_sessions
from .tenant import current_tenant_id, current_user_id

# --------------------------------------------------------------------------
# 数据导出 / 月度趋势
# --------------------------------------------------------------------------


# 备份恢复允许写回的 settings 键（用户偏好白名单）。
# 显式枚举而不是「排除 key」：新增的敏感键默认不会被旧备份意外写回。
_RESTORABLE_SETTING_KEYS = frozenset({
    "monthly_income",
    "emergency_target_months",
    "essential_categories",
    "quote_source_mode",
    "report_time",
    "report_focus",
    "voice_input",
    "voice_output",
    "text_scale",
    "high_contrast",
    "show_export",
    "expand_process",
    "show_suggestions",
    "auto_refresh",
    "auto_refresh_seconds",
    "compact_numbers",
    "color_scheme",
    "default_tab",
    "savings_goal",
    "enabled_models",
    "agent_tool_turns",
    "agent_plan",
    "agent_reflect",
    "knowledge_enabled",
    "ai_enabled",
    "data_note",
})


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


# --------------------------------------------------------------------------
# 备份恢复（导入导出配套；AI Key 不恢复，需重新在设置页填写）
# --------------------------------------------------------------------------


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

        counts["positions"] = await _restore_table(
            conn,
            "positions",
            data.get("positions"),
            "INSERT INTO positions(user_id,symbol,name,kind,industry,shares,cost,last,buy_date,fee)"
            " VALUES(:user_id,:symbol,:name,:kind,:industry,:shares,:cost,:last,:buy_date,:fee)",
        )
        # ---- 按外键依赖顺序恢复：members -> member_loans -> transactions ----
        # 反序会让带 owner_id 的流水在成员还不存在时触发 FOREIGN KEY 失败，
        # 而 _restore_table 的静默跳过会把它们悄悄丢掉（专家评审 P0-7）。
        counts["members"] = await _restore_table(
            conn,
            "members",
            data.get("members"),
            "INSERT INTO members(user_id,id,username,display_name,role,avatar_color,created_at)"
            " VALUES(:user_id,:id,:username,:display_name,:role,:avatar_color,:created_at)",
        )
        counts["member_loans"] = await _restore_table(
            conn,
            "member_loans",
            data.get("member_loans"),
            "INSERT INTO member_loans(user_id,id,from_member_id,to_member_id,amount,currency,note,settled,created_at,settled_at)"
            " VALUES(:user_id,:id,:from_member_id,:to_member_id,:amount,:currency,:note,:settled,:created_at,:settled_at)",
        )
        counts["family_motions"] = await _restore_table(
            conn,
            "family_motions",
            data.get("family_motions"),
            "INSERT INTO family_motions(user_id,id,title,amount,category,note,proposer_id,status,created_at,decided_at)"
            " VALUES(:user_id,:id,:title,:amount,:category,:note,:proposer_id,:status,:created_at,:decided_at)",
        )
        counts["family_votes"] = await _restore_table(
            conn,
            "family_votes",
            data.get("family_votes"),
            "INSERT INTO family_votes(user_id,motion_id,member_id,vote,note,created_at)"
            " VALUES(:user_id,:motion_id,:member_id,:vote,:note,:created_at)",
        )
        counts["transactions"] = await _restore_table(
            conn,
            "transactions",
            data.get("transactions"),
            "INSERT INTO transactions(user_id,date,item,category,amount,owner_id,is_shared)"
            " VALUES(:user_id,:date,:item,:category,:amount,:owner_id,:is_shared)",
        )
        counts["subscriptions"] = await _restore_table(
            conn,
            "subscriptions",
            data.get("subscriptions"),
            "INSERT INTO subscriptions(user_id,name,monthly,note,due_day)"
            " VALUES(:user_id,:name,:monthly,:note,:due_day)",
        )
        counts["debts"] = await _restore_table(
            conn,
            "debts",
            data.get("debts"),
            "INSERT INTO debts(user_id,name,monthly,balance,rate,due_day)"
            " VALUES(:user_id,:name,:monthly,:balance,:rate,:due_day)",
        )
        counts["budgets"] = await _restore_table(
            conn,
            "budgets",
            data.get("budgets"),
            "INSERT INTO budgets(user_id,month,category,amount)"
            " VALUES(:user_id,:month,:category,:amount)",
        )
        counts["goals"] = await _restore_table(
            conn,
            "goals",
            data.get("goals"),
            "INSERT INTO goals(user_id,name,target,saved,deadline,created_at)"
            " VALUES(:user_id,:name,:target,:saved,:deadline,:created_at)",
        )
        counts["allocation_targets"] = await _restore_table(
            conn,
            "allocation_targets",
            data.get("allocation_targets"),
            "INSERT INTO allocation_targets(user_id,symbol,name,target_pct,updated_at)"
            " VALUES(:user_id,:symbol,:name,:target_pct,:updated_at)",
        )
        counts["dca_plans"] = await _restore_table(
            conn,
            "dca_plans",
            data.get("dca_plans"),
            "INSERT INTO dca_plans(user_id,id,symbol,name,amount,frequency,day,start_date,note,active,created_at)"
            " VALUES(:user_id,:id,:symbol,:name,:amount,:frequency,:day,:start_date,:note,:active,:created_at)",
        )
        counts["financial_statements"] = await _restore_table(
            conn,
            "financial_statements",
            data.get("financial_statements"),
            "INSERT INTO financial_statements(user_id,id,company,currency,payload,report,created_at)"
            " VALUES(:user_id,:id,:company,:currency,:payload,:report,:created_at)",
        )
        counts["memory"] = await _restore_table(
            conn,
            "user_memory",
            data.get("memory"),
            "INSERT INTO user_memory(user_id,content,kind,created_at,updated_at)"
            " VALUES(:user_id,:content,:kind,:created_at,:updated_at)",
        )

        counts["watchlist"] = await _restore_table(
            conn,
            "watchlist",
            data.get("watchlist"),
            "INSERT INTO watchlist(user_id,symbol,name,kind,created_at)"
            " VALUES(:user_id,:symbol,:name,:kind,:created_at)",
        )
        counts["provenance"] = await _restore_table(
            conn,
            "provenance_log",
            data.get("provenance"),
            "INSERT INTO provenance_log(user_id,id,timestamp,action,entity_type,entity_id,before_json,after_json,source,username,metadata_json)"
            " VALUES(:user_id,:id,:timestamp,:action,:entity_type,:entity_id,:before_json,:after_json,:source,:username,:metadata_json)",
        )
        # 旧备份没有哈希字段：补空串后恢复，验链时按 legacy 前缀跳过。
        audit_rows = data.get("audit")
        if isinstance(audit_rows, list):
            audit_rows = [
                {**r, "prev_hash": r.get("prev_hash", ""), "entry_hash": r.get("entry_hash", "")}
                for r in audit_rows
                if isinstance(r, dict)
            ]
        counts["audit"] = await _restore_table(
            conn,
            "audit_logs",
            audit_rows,
            "INSERT INTO audit_logs(user_id,ts,action,method,path,status,actor,detail,"
            "duration_ms,prev_hash,entry_hash)"
            " VALUES(:user_id,:ts,:action,:method,:path,:status,:actor,:detail,"
            ":duration_ms,:prev_hash,:entry_hash)",
        )
        counts["attachments"] = await _restore_table(
            conn,
            "attachments",
            data.get("attachments"),
            "INSERT INTO attachments(user_id,id,filename,kind,size,content,indexed,created_at)"
            " VALUES(:user_id,:id,:filename,:kind,:size,:content,:indexed,:created_at)",
        )
        counts["conversation_summary"] = await _restore_table(
            conn,
            "conversation_summary",
            data.get("conversation_summary"),
            "INSERT INTO conversation_summary(user_id,thread_id,summary,source,covered_to,updated_at)"
            " VALUES(:user_id,:thread_id,:summary,:source,:covered_to,:updated_at)",
        )
        counts["dept_reports"] = await _restore_table(
            conn,
            "dept_reports",
            data.get("dept_reports"),
            "INSERT INTO dept_reports(user_id,id,report_id,question,dispatch,verdict,report,orders_json,conflicts_json,status,decision_note,decided_at,created_at)"
            " VALUES(:user_id,:id,:report_id,:question,:dispatch,:verdict,:report,:orders_json,:conflicts_json,:status,:decision_note,:decided_at,:created_at)",
        )
        counts["invoices"] = await _restore_table(
            conn,
            "invoices",
            data.get("invoices"),
            "INSERT INTO invoices(user_id,id,file_name,file_hash,source_format,invoice_code,"
            "invoice_number,invoice_date,buyer,seller,item,total_amount,tax_amount,tax_rate,"
            "kind,confidence,status,note,created_at)"
            " VALUES(:user_id,:id,:file_name,:file_hash,:source_format,:invoice_code,"
            ":invoice_number,:invoice_date,:buyer,:seller,:item,:total_amount,:tax_amount,:tax_rate,"
            ":kind,:confidence,:status,:note,:created_at)",
        )
        counts["brokerage_imports"] = await _restore_table(
            conn,
            "brokerage_imports",
            data.get("brokerage_imports"),
            "INSERT INTO brokerage_imports(user_id,id,file_name,file_hash,account,"
            "position_count,applied,warnings_json,created_at)"
            " VALUES(:user_id,:id,:file_name,:file_hash,:account,"
            ":position_count,:applied,:warnings_json,:created_at)",
        )
        counts["conditional_orders"] = await _restore_table(
            conn,
            "conditional_orders",
            data.get("conditional_orders"),
            "INSERT INTO conditional_orders(user_id,id,symbol,name,side,trigger_type,"
            "trigger_value,price,shares,mode,status,note,triggered_at,created_at)"
            " VALUES(:user_id,:id,:symbol,:name,:side,:trigger_type,"
            ":trigger_value,:price,:shares,:mode,:status,:note,:triggered_at,:created_at)",
        )
        counts["trade_risk_settings"] = await _restore_table(
            conn,
            "trade_risk_settings",
            data.get("trade_risk_settings"),
            "INSERT INTO trade_risk_settings(user_id,daily_limit,deviation_pct,concentration_pct,"
            "auto_execute_paper,updated_at)"
            " VALUES(:user_id,:daily_limit,:deviation_pct,:concentration_pct,"
            ":auto_execute_paper,:updated_at)",
        )
        counts["paper_accounts"] = await _restore_table(
            conn,
            "paper_accounts",
            data.get("paper_accounts"),
            "INSERT INTO paper_accounts(user_id,account_id,name,initial_cash,created_at)"
            " VALUES(:user_id,:account_id,:name,:initial_cash,:created_at)",
        )
        counts["paper_trades"] = await _restore_table(
            conn,
            "paper_trades",
            data.get("paper_trades"),
            "INSERT INTO paper_trades(user_id,account_id,date,symbol,name,side,price,shares,fee,amount)"
            " VALUES(:user_id,:account_id,:date,:symbol,:name,:side,:price,:shares,:fee,:amount)",
        )
        counts["paper_snapshots"] = await _restore_table(
            conn,
            "paper_snapshots",
            data.get("paper_snapshots"),
            "INSERT INTO paper_snapshots(user_id,account_id,date,equity,cash,market_value)"
            " VALUES(:user_id,:account_id,:date,:equity,:cash,:market_value)",
        )
        counts["net_worth_snapshots"] = await _restore_table(
            conn,
            "net_worth_snapshots",
            data.get("net_worth_snapshots"),
            "INSERT INTO net_worth_snapshots(user_id,date,total_assets,total_liabilities,"
            "net_worth,cash,market_value,source,created_at)"
            " VALUES(:user_id,:date,:total_assets,:total_liabilities,:net_worth,:cash,"
            ":market_value,:source,:created_at)",
        )

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

        # 设置：只恢复用户偏好白名单键；AI Key 与行为配置永不恢复
        # MCP 服务器：配置在 data/mcp.json，恢复时写回（打码过的地址仍可用；
        # 需要凭据的服务器由用户在设置页重新填写）
        mcp_servers = data.get("mcp_servers")
        if isinstance(mcp_servers, list):
            try:
                from .. import mcp_client

                def _keep(entry: dict[str, Any]) -> dict[str, Any]:
                    out = {
                        k: v
                        for k, v in entry.items()
                        if k in ("name", "url", "command", "args", "enabled")
                    }
                    env = entry.get("env")
                    if isinstance(env, dict):
                        # 备份里的 *** 是打码占位，不能当真实密钥写回配置
                        real = {k: v for k, v in env.items() if v and v != "***"}
                        if real:
                            out["env"] = real
                    # 恢复的 URL 同样要走 SSRF 校验：备份文件是可外部传入的输入，
                    # 不能成为写入内网地址（169.254.x / 10.x）的通道。
                    # 用 resolve=False：只做语法与字面 IP 检查，不依赖 DNS
                    # （离线恢复不该因为解析失败丢掉整条配置）。
                    if out.get("url"):
                        from urllib.parse import urlsplit, urlunsplit

                        from ..netguard import assert_public_http_url

                        raw_url = str(out["url"])
                        parts = urlsplit(raw_url)
                        if parts.username or parts.password:
                            # 备份里的是打码凭据 ***，本来也不能用；
                            # 去掉 userinfo 后由用户重新填写。
                            host = parts.hostname or ""
                            netloc = host + (f":{parts.port}" if parts.port else "")
                            raw_url = urlunsplit(
                                (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
                            )
                        try:
                            out["url"] = assert_public_http_url(raw_url, resolve=False)
                        except Exception as exc:  # noqa: BLE001 — 单条非法即跳过
                            raise ValueError(f"备份里的 MCP 地址不可用：{exc}") from exc
                    return out

                kept: list[dict[str, Any]] = []
                for s in mcp_servers:
                    if not isinstance(s, dict):
                        continue
                    try:
                        kept.append(_keep(s))
                    except ValueError:
                        continue
                clean = kept
                # stdio 配置等于本地命令执行；备份文件不应成为绕过 API 限制的入口。
                # 默认丢弃，只有部署者显式允许时才恢复。
                if not mcp_client.stdio_config_allowed():
                    clean = [
                        s for s in clean if not str(s.get("command") or "").strip()
                    ]
                mcp_client.save_servers(clean)
                counts["mcp_servers"] = len(clean)
            except Exception:  # noqa: BLE001 — MCP 恢复失败不阻断其余数据
                counts["mcp_servers"] = 0

        settings = data.get("settings") or {}
        if isinstance(settings, dict):
            # 只覆盖「用户偏好」类键。行为配置（studio_config / agent_config /
            # custom_system_prompt / ai_base_url / ai_model）不能由备份文件写入：
            # 否则一个来源不明的备份就能把权限模式改回 open、注入提示词、
            # 把模型端点指向别处（历史漏洞 M-3）。
            # 注意不能整表 DELETE：那样会把未列入白名单的行为配置一并清空，
            # 反而把权限模式重置成默认值。只删/写白名单键。
            restorable = {
                k: v
                for k, v in settings.items()
                if k in _RESTORABLE_SETTING_KEYS
            }
            if restorable:
                placeholders = ",".join("?" for _ in restorable)
                await conn.execute(
                    f"DELETE FROM settings WHERE user_id=? AND key IN ({placeholders})",
                    (uid, *restorable.keys()),
                )
            # 密钥永不从备份恢复，且恢复动作清空本机已存密钥：
            # 备份可能来自另一台机器，保留旧 key 会让"恢复"带着来源不明的凭据运行。
            await conn.execute(
                "DELETE FROM settings WHERE user_id=? AND key='ai_api_key'", (uid,)
            )
            await conn.executemany(
                "INSERT OR IGNORE INTO settings(user_id,key,value) VALUES(?,?,?)",
                [(uid, k, str(v)) for k, v in restorable.items()],
            )
            await _ensure_defaults()
            await _mark_user_data(conn)
            counts["settings"] = len(restorable)
            skipped = len(settings) - len(restorable)
            if skipped:
                counts["settings_skipped"] = skipped

        # 会话与问答历史：整体恢复（tools/flags 原样保留）
        sessions = data.get("sessions") or []
        for s in sessions:
            if not isinstance(s, dict) or not s.get("thread_id"):
                continue
            await conn.execute(
                "INSERT OR IGNORE INTO sessions(user_id,thread_id,title,created_at,updated_at)"
                " VALUES(?,?,?,?,?)",
                (
                    uid,
                    s["thread_id"],
                    str(s.get("title") or "新会话")[:40],
                    s.get("created_at") or "",
                    s.get("updated_at") or "",
                ),
            )
        counts["sessions"] = len(sessions)
        runs = data.get("runs") or []
        for r in runs:
            if not isinstance(r, dict) or not r.get("question"):
                continue
            await conn.execute(
                "INSERT INTO runs(user_id,thread_id,question,answer,level,flags_json,created_at,route,llm,route_reason,tools,actions)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uid,
                    r.get("thread_id") or "default",
                    str(r.get("question") or "")[:500],
                    str(r.get("answer") or ""),
                    str(r.get("level") or ""),
                    json.dumps(r.get("flags") or [], ensure_ascii=False),
                    r.get("created_at")
                    or datetime.now().astimezone().isoformat(timespec="seconds"),
                    str(r.get("route") or ""),
                    str(r.get("llm") or ""),
                    str(r.get("route_reason") or ""),
                    json.dumps(r.get("tools") or [], ensure_ascii=False),
                    json.dumps(r.get("actions") or [], ensure_ascii=False),
                ),
            )
        counts["runs"] = len(runs)
    except Exception:  # noqa: BLE001 — 恢复失败由外层统一回滚，不留半截状态
        raise


async def _restore_gl(
    conn: aiosqlite.Connection, data: dict[str, Any], tenant_id: int
) -> dict[str, int]:
    """恢复总账并重映射内部 ID（科目/期间/凭证/分录行）。

    备份里的 id/外键只在原库有意义；跨库恢复必须重新分配，否则会与
    其他租户的全局自增 id 冲突，或把分录挂到错误的凭证上。
    """

    def rows(name: str) -> list[dict[str, Any]]:
        raw = data.get(name) or []
        if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
            raise ValueError(f"{name} 备份格式不正确")
        return raw

    accounts = rows("gl_accounts")
    periods = rows("gl_periods")
    entries = rows("gl_entries")
    lines = rows("gl_entry_lines")

    for table in ("gl_entry_lines", "gl_entries", "gl_periods", "gl_accounts"):
        await conn.execute(
            f"DELETE FROM {table} WHERE tenant_id=?", (int(tenant_id),)
        )

    account_map: dict[int, int] = {}
    for a in accounts:
        cur = await conn.execute(
            "INSERT INTO gl_accounts(tenant_id,code,name,type,parent_id,is_active,created_at)"
            " VALUES(?,?,?,?,NULL,?,?)",
            (
                int(tenant_id),
                str(a.get("code") or "")[:20],
                str(a.get("name") or "")[:80],
                str(a.get("type") or ""),
                int(a.get("is_active", 1) or 0),
                str(a.get("created_at") or ""),
            ),
        )
        account_map[int(a["id"])] = int(cur.lastrowid)
    for a in accounts:
        parent = a.get("parent_id")
        if parent is None:
            continue
        parent_id = account_map.get(int(parent))
        if parent_id is None:
            raise ValueError("总账科目上级引用缺失")
        await conn.execute(
            "UPDATE gl_accounts SET parent_id=? WHERE tenant_id=? AND id=?",
            (parent_id, int(tenant_id), account_map[int(a["id"])]),
        )

    period_map: dict[int, int] = {}
    for p in periods:
        cur = await conn.execute(
            "INSERT INTO gl_periods(tenant_id,year,month,start_date,end_date,status,"
            "created_at,closed_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                int(p.get("year") or 0),
                int(p.get("month") or 0),
                str(p.get("start_date") or ""),
                str(p.get("end_date") or ""),
                str(p.get("status") or "open"),
                str(p.get("created_at") or ""),
                str(p.get("closed_at") or ""),
            ),
        )
        period_map[int(p["id"])] = int(cur.lastrowid)

    entry_map: dict[int, int] = {}
    for e in entries:
        period_id = period_map.get(int(e.get("period_id") or 0))
        if period_id is None:
            raise ValueError("总账凭证的期间引用缺失")
        cur = await conn.execute(
            "INSERT INTO gl_entries(tenant_id,entry_no,entry_date,period_id,description,"
            "status,source,reversal_of,created_by,created_at,posted_at)"
            " VALUES(?,?,?,?,?,?,?,NULL,?,?,?)",
            (
                int(tenant_id),
                str(e.get("entry_no") or ""),
                str(e.get("entry_date") or ""),
                period_id,
                str(e.get("description") or ""),
                str(e.get("status") or "draft"),
                str(e.get("source") or "manual"),
                e.get("created_by"),
                str(e.get("created_at") or ""),
                str(e.get("posted_at") or ""),
            ),
        )
        entry_map[int(e["id"])] = int(cur.lastrowid)
    for e in entries:
        rev = e.get("reversal_of")
        if rev is None:
            continue
        rev_id = entry_map.get(int(rev))
        if rev_id is None:
            raise ValueError("总账反冲引用缺失")
        await conn.execute(
            "UPDATE gl_entries SET reversal_of=? WHERE tenant_id=? AND id=?",
            (rev_id, int(tenant_id), entry_map[int(e["id"])]),
        )

    for line in lines:
        entry_id = entry_map.get(int(line.get("entry_id") or 0))
        account_id = account_map.get(int(line.get("account_id") or 0))
        if entry_id is None or account_id is None:
            raise ValueError("总账分录行引用缺失")
        await conn.execute(
            "INSERT INTO gl_entry_lines(tenant_id,entry_id,line_no,account_id,"
            "debit_cents,credit_cents,memo) VALUES(?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                entry_id,
                int(line.get("line_no") or 0),
                account_id,
                int(line.get("debit_cents") or 0),
                int(line.get("credit_cents") or 0),
                str(line.get("memo") or "")[:200],
            ),
        )

    return {
        "gl_accounts": len(accounts),
        "gl_periods": len(periods),
        "gl_entries": len(entries),
        "gl_entry_lines": len(lines),
    }, {
        "accounts": account_map,
        "periods": period_map,
        "entries": entry_map,
    }


async def _restore_expenses(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    entry_map: dict[int, int],
) -> tuple[dict[str, int], dict[int, int]]:
    """恢复报销单；gl_entry_id 必须映射到新总账凭证 id。"""
    raw = data.get("expense_claims") or []
    if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
        raise ValueError("expense_claims 备份格式不正确")
    await conn.execute(
        "DELETE FROM expense_claims WHERE tenant_id=?", (int(tenant_id),)
    )
    claim_map: dict[int, int] = {}
    for c in raw:
        old_entry = c.get("gl_entry_id")
        new_entry = None
        if old_entry is not None:
            new_entry = entry_map.get(int(old_entry))
            if new_entry is None:
                raise ValueError("报销单关联的总账凭证引用缺失")
        cur = await conn.execute(
            "INSERT INTO expense_claims(tenant_id,claim_no,title,applicant_user_id,"
            "department_id,amount_cents,category,expense_account_id,credit_account_id,"
            "invoice_ref,attachment_name,status,approved_by,approved_at,"
            "rejected_reason,gl_entry_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                str(c.get("claim_no") or ""),
                str(c.get("title") or ""),
                int(c.get("applicant_user_id") or 0),
                c.get("department_id"),
                int(c.get("amount_cents") or 0),
                str(c.get("category") or ""),
                int(c.get("expense_account_id") or 0),
                int(c.get("credit_account_id") or 0),
                str(c.get("invoice_ref") or ""),
                str(c.get("attachment_name") or ""),
                str(c.get("status") or "draft"),
                c.get("approved_by"),
                str(c.get("approved_at") or ""),
                str(c.get("rejected_reason") or ""),
                new_entry,
                str(c.get("created_at") or ""),
                str(c.get("updated_at") or ""),
            ),
        )
        claim_map[int(c["id"])] = int(cur.lastrowid)
    return {"expense_claims": len(raw)}, claim_map


async def _restore_payments(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    claim_map: dict[int, int],
    payable_map: dict[int, int],
    entry_map: dict[int, int],
    account_map: dict[int, int],
) -> tuple[dict[str, int], dict[int, int]]:
    raw = data.get("payments") or []
    if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
        raise ValueError("payments 备份格式不正确")
    await conn.execute("DELETE FROM payments WHERE tenant_id=?", (int(tenant_id),))
    payment_map: dict[int, int] = {}
    for p in raw:
        old_claim = int(p.get("claim_id") or 0)
        claim_id = claim_map.get(old_claim) if old_claim else 0
        if old_claim and claim_id is None:
            raise ValueError("付款关联的报销单引用缺失")
        old_payable = p.get("payable_id")
        payable_id = None
        if old_payable is not None:
            payable_id = payable_map.get(int(old_payable))
            if payable_id is None:
                raise ValueError("付款关联的应付单引用缺失")
        account_id = account_map.get(int(p.get("bank_account_id") or 0))
        if account_id is None:
            raise ValueError("付款关联的银行科目引用缺失")
        old_entry = p.get("gl_entry_id")
        entry_id = None
        if old_entry is not None:
            entry_id = entry_map.get(int(old_entry))
            if entry_id is None:
                raise ValueError("付款关联的总账凭证引用缺失")
        cur = await conn.execute(
            "INSERT INTO payments(tenant_id,payment_no,claim_id,payable_id,amount_cents,"
            "payee,bank_account_id,method,status,paid_at,gl_entry_id,created_by,note,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                str(p.get("payment_no") or ""),
                int(claim_id or 0),
                payable_id,
                int(p.get("amount_cents") or 0),
                str(p.get("payee") or ""),
                account_id,
                str(p.get("method") or "bank"),
                str(p.get("status") or "paid"),
                str(p.get("paid_at") or ""),
                entry_id,
                p.get("created_by"),
                str(p.get("note") or ""),
                str(p.get("created_at") or ""),
                str(p.get("updated_at") or ""),
            ),
        )
        payment_map[int(p["id"])] = int(cur.lastrowid)
    return {"payments": len(raw)}, payment_map


async def _restore_procurement(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    account_map: dict[int, int],
    entry_map: dict[int, int],
) -> tuple[dict[str, int], dict[int, int], list[tuple[int, int]]]:
    """恢复供应商 / 采购单 / 应付单。

    付款与应付单互相引用（应付单记 payment_id，付款记 payable_id），
    这里先不写 payment_id，返回待回填清单，等 payments 落库后由调用方补上。
    """
    vendors = data.get("vendors") or []
    orders = data.get("purchase_orders") or []
    payables = data.get("payables") or []
    for name, rows in (
        ("vendors", vendors),
        ("purchase_orders", orders),
        ("payables", payables),
    ):
        if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows):
            raise ValueError(f"{name} 备份格式不正确")

    await conn.execute("DELETE FROM payables WHERE tenant_id=?", (int(tenant_id),))
    await conn.execute(
        "DELETE FROM purchase_orders WHERE tenant_id=?", (int(tenant_id),)
    )
    await conn.execute("DELETE FROM vendors WHERE tenant_id=?", (int(tenant_id),))

    vendor_map: dict[int, int] = {}
    for v in vendors:
        cur = await conn.execute(
            "INSERT INTO vendors(tenant_id,code,name,tax_no,contact,phone,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                str(v.get("code") or ""),
                str(v.get("name") or ""),
                str(v.get("tax_no") or ""),
                str(v.get("contact") or ""),
                str(v.get("phone") or ""),
                str(v.get("status") or "active"),
                str(v.get("created_at") or ""),
            ),
        )
        vendor_map[int(v["id"])] = int(cur.lastrowid)

    po_map: dict[int, int] = {}
    for po in orders:
        new_vendor = vendor_map.get(int(po.get("vendor_id") or 0))
        if new_vendor is None:
            raise ValueError("采购单关联的供应商引用缺失")
        cur = await conn.execute(
            "INSERT INTO purchase_orders(tenant_id,po_no,vendor_id,order_date,"
            "expected_date,amount_cents,description,status,approved_by,approved_at,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                str(po.get("po_no") or ""),
                new_vendor,
                str(po.get("order_date") or ""),
                str(po.get("expected_date") or ""),
                int(po.get("amount_cents") or 0),
                str(po.get("description") or ""),
                str(po.get("status") or "draft"),
                po.get("approved_by"),
                str(po.get("approved_at") or ""),
                str(po.get("created_at") or ""),
                str(po.get("updated_at") or ""),
            ),
        )
        po_map[int(po["id"])] = int(cur.lastrowid)

    payable_map: dict[int, int] = {}
    pending_payments: list[tuple[int, int]] = []
    for ap in payables:
        new_vendor = vendor_map.get(int(ap.get("vendor_id") or 0))
        if new_vendor is None:
            raise ValueError("应付单关联的供应商引用缺失")
        old_po = ap.get("po_id")
        new_po = None
        if old_po is not None:
            new_po = po_map.get(int(old_po))
            if new_po is None:
                raise ValueError("应付单关联的采购单引用缺失")
        new_expense = account_map.get(int(ap.get("expense_account_id") or 0))
        new_payable_account = account_map.get(int(ap.get("payable_account_id") or 0))
        if new_expense is None or new_payable_account is None:
            raise ValueError("应付单关联的会计科目引用缺失")
        old_entry = ap.get("gl_entry_id")
        new_entry = None
        if old_entry is not None:
            new_entry = entry_map.get(int(old_entry))
            if new_entry is None:
                raise ValueError("应付单关联的总账凭证引用缺失")
        cur = await conn.execute(
            "INSERT INTO payables(tenant_id,payable_no,vendor_id,po_id,invoice_no,"
            "invoice_date,due_date,amount_cents,tax_cents,expense_account_id,"
            "payable_account_id,status,gl_entry_id,payment_id,approved_by,approved_at,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?,?)",
            (
                int(tenant_id),
                str(ap.get("payable_no") or ""),
                new_vendor,
                new_po,
                str(ap.get("invoice_no") or ""),
                str(ap.get("invoice_date") or ""),
                str(ap.get("due_date") or ""),
                int(ap.get("amount_cents") or 0),
                int(ap.get("tax_cents") or 0),
                new_expense,
                new_payable_account,
                str(ap.get("status") or "draft"),
                new_entry,
                ap.get("approved_by"),
                str(ap.get("approved_at") or ""),
                str(ap.get("created_at") or ""),
                str(ap.get("updated_at") or ""),
            ),
        )
        new_payable_id = int(cur.lastrowid)
        payable_map[int(ap["id"])] = new_payable_id
        if ap.get("payment_id") is not None:
            pending_payments.append((new_payable_id, int(ap["payment_id"])))
    return (
        {
            "vendors": len(vendors),
            "purchase_orders": len(orders),
            "payables": len(payables),
        },
        payable_map,
        pending_payments,
    )


async def _restore_bank_transactions(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    payment_map: dict[int, int],
    account_map: dict[int, int],
) -> dict[str, int]:
    raw = data.get("bank_transactions") or []
    if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
        raise ValueError("bank_transactions 备份格式不正确")
    await conn.execute(
        "DELETE FROM bank_transactions WHERE tenant_id=?", (int(tenant_id),)
    )
    for b in raw:
        account_id = account_map.get(int(b.get("bank_account_id") or 0))
        if account_id is None:
            raise ValueError("银行流水关联的银行科目引用缺失")
        old_payment = b.get("payment_id")
        new_payment = None
        if old_payment is not None:
            new_payment = payment_map.get(int(old_payment))
            if new_payment is None:
                raise ValueError("银行流水关联的付款引用缺失")
        await conn.execute(
            "INSERT INTO bank_transactions(tenant_id,bank_account_id,txn_date,direction,"
            "amount_cents,counterparty,memo,bank_ref,status,payment_id,matched_by,"
            "matched_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                account_id,
                str(b.get("txn_date") or ""),
                str(b.get("direction") or ""),
                int(b.get("amount_cents") or 0),
                str(b.get("counterparty") or ""),
                str(b.get("memo") or ""),
                str(b.get("bank_ref") or ""),
                str(b.get("status") or "unmatched"),
                new_payment,
                b.get("matched_by"),
                str(b.get("matched_at") or ""),
                str(b.get("created_at") or ""),
                str(b.get("updated_at") or ""),
            ),
        )
    return {"bank_transactions": len(raw)}


async def _restore_bank_reconciliations(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    account_map: dict[int, int],
    period_map: dict[int, int],
) -> dict[str, int]:
    raw = data.get("bank_reconciliations") or []
    if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
        raise ValueError("bank_reconciliations 备份格式不正确")
    await conn.execute(
        "DELETE FROM bank_reconciliations WHERE tenant_id=?", (int(tenant_id),)
    )
    for r in raw:
        account_id = account_map.get(int(r.get("bank_account_id") or 0))
        period_id = period_map.get(int(r.get("period_id") or 0))
        if account_id is None or period_id is None:
            raise ValueError("对账记录的账户或期间引用缺失")
        await conn.execute(
            "INSERT INTO bank_reconciliations(tenant_id,bank_account_id,period_id,"
            "statement_balance_cents,book_balance_cents,difference_cents,status,note,"
            "created_by,created_at,closed_by,closed_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                account_id,
                period_id,
                int(r.get("statement_balance_cents") or 0),
                int(r.get("book_balance_cents") or 0),
                int(r.get("difference_cents") or 0),
                str(r.get("status") or "open"),
                str(r.get("note") or ""),
                r.get("created_by"),
                str(r.get("created_at") or ""),
                r.get("closed_by"),
                str(r.get("closed_at") or ""),
            ),
        )
    return {"bank_reconciliations": len(raw)}


async def _restore_table(
    conn: aiosqlite.Connection,
    name: str,
    rows: Any,
    sql: str,
) -> int:
    """把备份列表写回指定表。

    统一注入当前租户：备份包本身不带 user_id（也不该带），恢复时一律落到
    当前登录用户名下。

    错误策略（专家评审 P0-7）：**不再静默跳过坏行**。旧实现 `except: continue`
    会让外键失败/字段不匹配的行悄悄消失，接口却返回 ok，用户以为恢复成功。
    现在收集失败行并在最后抛错，由调用方整体回滚。
    """
    if not isinstance(rows, list):
        return 0
    uid = current_user_id()
    n = 0
    failed: list[str] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            failed.append(f"#{idx}: 非对象")
            continue
        try:
            await conn.execute(sql, {**row, "user_id": uid})
            n += 1
        except Exception as exc:  # noqa: BLE001
            failed.append(f"#{idx}: {type(exc).__name__}: {exc}")
    if failed:
        raise ValueError(
            f"恢复 {name} 时有 {len(failed)} 行失败（已回滚）：" + "; ".join(failed[:3])
        )
    return n
