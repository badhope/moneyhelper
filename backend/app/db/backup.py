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


# 导出侧已拆到 db/backup_export.py，见文件末尾导入。



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


# 各域还原组件已拆到 db/backup_restore.py，见文件末尾导入。


from .backup_export import export_data, monthly_trend  # noqa: F401,E402 — 对外同名导出
from .backup_restore import (  # noqa: F401,E402 — 供 _import_backup_locked 调用
    _restore_bank_reconciliations,
    _restore_bank_transactions,
    _restore_expenses,
    _restore_gl,
    _restore_payments,
    _restore_procurement,
    _restore_table,
)

