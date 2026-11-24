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

    return await ledger_counts(DEMO_USER_ID)
