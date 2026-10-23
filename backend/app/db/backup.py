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
from .tenant import current_user_id

# --------------------------------------------------------------------------
# 数据导出 / 月度趋势
# --------------------------------------------------------------------------


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
    }


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
        await _import_backup_locked(conn, data, counts)
    return counts


async def _import_backup_locked(
    conn: aiosqlite.Connection, data: dict[str, Any], counts: dict[str, int]
) -> None:
    """import_backup 的实际写入段（调用方必须已持有写锁）。"""
    uid = current_user_id()
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
        counts["audit"] = await _restore_table(
            conn,
            "audit_logs",
            data.get("audit"),
            "INSERT INTO audit_logs(user_id,ts,action,method,path,status,actor,detail,duration_ms)"
            " VALUES(:user_id,:ts,:action,:method,:path,:status,:actor,:detail,:duration_ms)",
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

        # 设置：整表覆盖，但 AI Key 永不恢复（明文 Key 不进备份/恢复链路）
        settings = data.get("settings") or {}
        if isinstance(settings, dict):
            await conn.execute("DELETE FROM settings WHERE user_id=?", (uid,))
            await conn.executemany(
                "INSERT OR IGNORE INTO settings(user_id,key,value) VALUES(?,?,?)",
                [
                    (uid, k, str(v))
                    for k, v in settings.items()
                    if k != "ai_api_key"
                ],
            )
            await _ensure_defaults()
            await _mark_user_data(conn)
            counts["settings"] = len(settings) - (1 if "ai_api_key" in settings else 0)

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

        await conn.commit()
    except Exception:  # noqa: BLE001 — 恢复失败整体回滚，不留半截状态
        await conn.rollback()
        raise


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
