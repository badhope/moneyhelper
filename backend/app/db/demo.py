"""演示账本：独立租户里的只展示数据。

为什么单独放租户，而不是往用户账本里再灌一份示例：
历史上的「载入示例数据」会清空当前用户的持仓/流水再写种子，演示完再切回来
已经找不回真实数据，界面上「示例」与「真实」也共用一套数字。这里把演示
数据放到保留租户 `DEMO_USER_ID`，真实租户完全不动；切换只改请求上下文。

演示租户没有 users 记录，也不参与备份/登录：它只是一块可随时重建的展示区。
"""

from __future__ import annotations

from typing import Any

from . import _core
from ._schema import (
    SEED_DEBTS,
    SEED_POSITIONS,
    SEED_SETTINGS,
    SEED_SUBSCRIPTIONS,
    SEED_TRANSACTIONS,
)
from .db_write_txn import write_txn
from .seed import _seed_date
from .tenant import use_user

# 保留一个足够大的正数 id：不能是 0（会和本机真实账本撞），也不能是负数
# （部分权限/组织逻辑把 <=0 当作本机管理员）。10_000_001 远高于正常注册用户。
DEMO_USER_ID = 10_000_001
DEMO_NOTE = "demo"

_DEMO_TABLES = (
    "positions",
    "transactions",
    "subscriptions",
    "debts",
    "budgets",
    "goals",
    "sessions",
    "runs",
    "net_worth_snapshots",
    "settings",
    "attribution_confirmations",
    "attribution_rules",
    "attribution_rollbacks",
    "automation_runs",
    "automation_alerts",
)


async def ledger_counts(user_id: int) -> dict[str, int]:
    """某个租户的持仓/流水计数（不依赖当前请求上下文）。"""
    row = await _core.fetch_one(
        "SELECT"
        " (SELECT COUNT(*) FROM positions WHERE user_id=?) AS positions,"
        " (SELECT COUNT(*) FROM transactions WHERE user_id=?) AS transactions,"
        " (SELECT COUNT(*) FROM subscriptions WHERE user_id=?) AS subscriptions,"
        " (SELECT COUNT(*) FROM debts WHERE user_id=?) AS debts",
        (int(user_id), int(user_id), int(user_id), int(user_id)),
    )
    return {
        "positions": int(row["positions"]) if row else 0,
        "transactions": int(row["transactions"]) if row else 0,
        "subscriptions": int(row["subscriptions"]) if row else 0,
        "debts": int(row["debts"]) if row else 0,
    }


async def _seed_consolidation_demo(conn: Any) -> None:
    """重建演示集团：主体现金流与抵销分录都可重复复现。

    10000001 保留原有 8-11 月演示总账；10000002 每次重置后重建 2026-11 账套；
    10000003 故意不建账，用来展示「缺账不按 0 计入」。
    """
    from ..timeutil import new_id, now_iso

    parent, sub, empty = DEMO_USER_ID, 10000002, 10000003
    await conn.execute(
        "DELETE FROM consolidation_adjustments WHERE group_id IN"
        " (SELECT id FROM tenant_groups WHERE owner_user_id=?)", (DEMO_USER_ID,)
    )
    await conn.execute(
        "DELETE FROM tenant_group_entities WHERE group_id IN"
        " (SELECT id FROM tenant_groups WHERE owner_user_id=?)", (DEMO_USER_ID,)
    )
    await conn.execute(
        "DELETE FROM tenant_groups WHERE owner_user_id=?", (DEMO_USER_ID,)
    )
    for tid in (sub, empty):
        for table in ("gl_entry_lines", "gl_entries", "gl_periods", "gl_accounts"):
            await conn.execute(f"DELETE FROM {table} WHERE tenant_id=?", (tid,))
        await conn.execute("DELETE FROM org_memberships WHERE tenant_id=?", (tid,))
        await conn.execute("DELETE FROM tenants WHERE id=?", (tid,))

    now = now_iso()
    await conn.execute(
        "INSERT OR IGNORE INTO tenants(id,name,kind,owner_user_id,status,created_at)"
        " VALUES(?,?,?,?, 'active',?)",
        (parent, "演示集团总部", "enterprise", DEMO_USER_ID, now),
    )
    await conn.execute(
        "INSERT INTO org_memberships(tenant_id,user_id,role,status,created_at)"
        " VALUES(?,?, 'owner','active',?)"
        " ON CONFLICT(tenant_id,user_id) DO UPDATE SET role='owner',status='active'",
        (parent, DEMO_USER_ID, now),
    )
    for tid, name in ((sub, "演示子公司"), (empty, "待建账分部")):
        await conn.execute(
            "INSERT INTO tenants(id,name,kind,owner_user_id,status,created_at)"
            " VALUES(?,?,?,?, 'active',?)",
            (tid, name, "enterprise", DEMO_USER_ID, now),
        )
        await conn.execute(
            "INSERT INTO org_memberships(tenant_id,user_id,role,status,created_at)"
            " VALUES(?,?, 'owner','active',?)",
            (tid, DEMO_USER_ID, now),
        )

    group_id = "grp_demo"
    await conn.execute(
        "INSERT INTO tenant_groups(id,name,owner_user_id,status,created_at,updated_at)"
        " VALUES(?,?,?, 'active',?,?)",
        (group_id, "演示集团", DEMO_USER_ID, now, now),
    )
    for idx, (tid, pct, method) in enumerate(
        ((parent, 100, "full"), (sub, 80, "proportional"), (empty, 20, "proportional"))
    ):
        await conn.execute(
            "INSERT INTO tenant_group_entities"
            "(group_id,tenant_id,ownership_pct,method,sort_order,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (group_id, tid, pct, method, idx, now),
        )
    await conn.execute(
        "INSERT INTO consolidation_adjustments"
        "(id,group_id,period,voucher_id,line_no,description,account_code,"
        "account_name,account_type,debit_cents,credit_cents,memo,created_by,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            new_id("cal_"), group_id, "2026-11", "adj_demo", 1, "内部销售抵销",
            "6001", "主营业务收入", "income", 32000, 0, "抵销总部对子公司销售",
            DEMO_USER_ID, now,
        ),
    )
    await conn.execute(
        "INSERT INTO consolidation_adjustments"
        "(id,group_id,period,voucher_id,line_no,description,account_code,"
        "account_name,account_type,debit_cents,credit_cents,memo,created_by,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            new_id("cal_"), group_id, "2026-11", "adj_demo", 2, "内部销售抵销",
            "6401", "主营业务成本", "expense", 0, 32000, "抵销子公司对应成本",
            DEMO_USER_ID, now,
        ),
    )


async def reset_demo_ledger() -> dict[str, Any]:
    """清空并重建演示租户，返回重建后的计数。

    每次进入演示都重建一次：用户可能在演示里点过「记一笔」，下次再进来
    不该看到上次残留的半截状态。真实租户不受影响。
    """
    with use_user(DEMO_USER_ID):
        async with write_txn() as conn:
            for table in _DEMO_TABLES:
                await conn.execute(f"DELETE FROM {table} WHERE user_id=?", (DEMO_USER_ID,))

            await conn.executemany(
                "INSERT INTO positions(user_id,symbol,name,kind,industry,shares,cost,last,buy_date,fee)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        DEMO_USER_ID,
                        p["symbol"],
                        p["name"],
                        p["kind"],
                        p["industry"],
                        p["shares"],
                        p["cost"],
                        p["last"],
                        None,
                        0.0,
                    )
                    for p in SEED_POSITIONS
                ],
            )
            await conn.executemany(
                "INSERT INTO transactions(user_id,date,item,category,amount) VALUES(?,?,?,?,?)",
                [
                    (DEMO_USER_ID, _seed_date(d), item, cat, amt)
                    for d, item, cat, amt in SEED_TRANSACTIONS
                ],
            )
            await conn.executemany(
                "INSERT INTO subscriptions(user_id,name,monthly,note,due_day)"
                " VALUES(?,?,?,?,?)",
                [
                    (DEMO_USER_ID, s["name"], s["monthly"], s.get("note", ""), s.get("due_day", ""))
                    for s in SEED_SUBSCRIPTIONS
                ],
            )
            await conn.executemany(
                "INSERT INTO debts(user_id,name,monthly,balance,rate,due_day)"
                " VALUES(?,?,?,?,?,?)",
                [
                    (DEMO_USER_ID, d["name"], d["monthly"], d["balance"], d["rate"], d.get("due_day", ""))
                    for d in SEED_DEBTS
                ],
            )
            for key, value in SEED_SETTINGS.items():
                await conn.execute(
                    "INSERT INTO settings(user_id,key,value) VALUES(?,?,?)"
                    " ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
                    (DEMO_USER_ID, key, value),
                )
            await conn.execute(
                "INSERT INTO settings(user_id,key,value) VALUES(?,?,?)"
                " ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
                (DEMO_USER_ID, "data_note", DEMO_NOTE),
            )
            await _seed_consolidation_demo(conn)

    await _seed_demo_gl()
    return await ledger_counts(DEMO_USER_ID)


async def _seed_demo_gl() -> None:
    """给演示主体铺 2026-11 已过账凭证；已有总账不覆盖。"""
    from .gl_accounts import gl_bootstrap, gl_list_accounts, gl_list_periods
    from .gl_entries_post import gl_post_entry
    from .gl_entries_write import gl_create_entry

    async def seed(tenant_id: int, entries: tuple[tuple[str, list[tuple[str, float, float]]], ...]) -> None:
        await gl_bootstrap(tenant_id, ref_date="2026-11-28")
        periods = await gl_list_periods(tenant_id)
        found = next(
            (p for p in periods if int(p["year"]) == 2026 and int(p["month"]) == 11), None
        )
        if found and int(found.get("posted_entries") or 0) > 0:
            return
        accounts = {a["code"]: a for a in await gl_list_accounts(tenant_id)}
        for desc, lines in entries:
            entry = await gl_create_entry(
                tenant_id, "2026-11-28", desc,
                [
                    {"account_id": accounts[code]["id"], "debit": debit, "credit": credit}
                    for code, debit, credit in lines
                ],
            )
            await gl_post_entry(tenant_id, entry["id"])

    await seed(
        DEMO_USER_ID,
        (
            ("2026-11 总部销售收入", [("1001", 410000, 0), ("6001", 0, 410000)]),
            ("2026-11 总部经营支出", [("6602", 200000, 0), ("1001", 0, 200000)]),
            ("2026-11 总部计提税费", [("6603", 30000, 0), ("2203", 0, 30000)]),
        ),
    )
    await seed(
        10000002,
        (
            ("2026-11 集团内销售", [("1001", 1200, 0), ("6001", 0, 1200)]),
            ("2026-11 采购成本", [("6401", 400, 0), ("1001", 0, 400)]),
            ("2026-11 管理费用", [("6602", 100, 0), ("1001", 0, 100)]),
        ),
    )
