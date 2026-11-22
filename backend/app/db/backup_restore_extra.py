"""备份恢复·计划与资产域：预算/目标/定投/财报/记忆/观察/审计/纸面账户/净值。"""

from __future__ import annotations

from typing import Any

import aiosqlite

from .backup_restore import _restore_table


async def _restore_extra_tables(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    counts: dict[str, int],
    uid: str,
) -> None:
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
    # 兼容旧备份：4.16.30 之前没有 mime/data，用空串补齐，避免整包恢复失败
    att_rows = data.get("attachments")
    if isinstance(att_rows, list):
        att_rows = [
            {**r, "mime": r.get("mime", ""), "data": r.get("data", "")}
            if isinstance(r, dict) else r
            for r in att_rows
        ]
    counts["attachments"] = await _restore_table(
        conn,
        "attachments",
        att_rows,
        "INSERT INTO attachments(user_id,id,filename,kind,size,content,mime,data,indexed,created_at)"
        " VALUES(:user_id,:id,:filename,:kind,:size,:content,:mime,:data,:indexed,:created_at)",
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
