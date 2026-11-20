"""db 种子数据与默认值：示例账本、data_note 标记、会话兜底迁移。

全新库仍是空账本，这里的一切只在显式「导入示例数据」或测试夹具里被调用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import aiosqlite

from . import _core
from ._schema import (
    DEFAULT_SETTINGS,
    SEED_DEBTS,
    SEED_POSITIONS,
    SEED_SETTINGS,
    SEED_SUBSCRIPTIONS,
    SEED_TRANSACTIONS,
)


def _seed_date(day: int) -> str:
    """种子流水的日期：本月已过去的日期（不晚于今天）。"""
    now = datetime.now()
    return now.replace(day=min(day, now.day)).strftime("%Y-%m-%d")

def _clean_due_day(v: object) -> str:
    """扣款日归一化：'' / '1'..'31'；非法值返回 ''。"""
    s = str(v or "").strip()
    if s in {"", "0"}:
        return ""
    if s.isdigit() and 1 <= int(s) <= 31:
        return s
    return ""

_COUNT_ALLOWED_TABLES = frozenset(
    {
        "transactions",
        "positions",
        "budgets",
        "goals",
        "subscriptions",
        "members",
        "runs",
        "audit_log",
        "transactions_fts",
    }
)

async def _count(table: str) -> int:
    if table not in _COUNT_ALLOWED_TABLES:
        raise ValueError(f"disallowed table for _core._count: {table!r}")
    cur = await _core._db.execute(f"SELECT COUNT(*) AS n FROM {table}")
    row = await cur.fetchone()
    return int(row["n"]) if row else 0

async def _seed_all(user_id: int = 0) -> None:
    """种入示例数据到指定租户。

    默认 0（本机默认账本）；`reset_to_seed` 传入当前租户，避免把示例数据
    写到别人的账本里。
    """
    assert _core._db is not None
    await _core._db.executemany(
        "INSERT INTO positions(user_id,symbol,name,kind,industry,shares,cost,last,buy_date,fee)"
        " VALUES(:user_id,:symbol,:name,:kind,:industry,:shares,:cost,:last,:buy_date,:fee)",
        [{**p, "buy_date": None, "fee": 0.0, "user_id": user_id} for p in SEED_POSITIONS],
    )
    await _core._db.executemany(
        "INSERT INTO transactions(user_id,date,item,category,amount) VALUES(?,?,?,?,?)",
        [
            (user_id, _seed_date(d), item, cat, amt)
            for d, item, cat, amt in SEED_TRANSACTIONS
        ],
    )
    await _core._db.executemany(
        "INSERT INTO subscriptions(user_id,name,monthly,note,due_day)"
        " VALUES(:user_id,:name,:monthly,:note,:due_day)",
        [
            {**s, "due_day": s.get("due_day", ""), "user_id": user_id}
            for s in SEED_SUBSCRIPTIONS
        ],
    )
    await _core._db.executemany(
        "INSERT INTO debts(user_id,name,monthly,balance,rate,due_day)"
        " VALUES(:user_id,:name,:monthly,:balance,:rate,:due_day)",
        [{**d, "due_day": d.get("due_day", ""), "user_id": user_id} for d in SEED_DEBTS],
    )
    await _core._db.executemany(
        "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
        list(SEED_SETTINGS.items()),
    )

async def _ensure_defaults() -> None:
    """补齐默认设置键。

    注意：默认值要落给**每一个已存在的租户**（否则新用户读不到默认项），
    而不是只落给当前请求的租户——这个函数在启动时运行，没有请求上下文。
    """
    conn = await _core._conn()
    try:
        rows = await _core.fetch_all("SELECT DISTINCT user_id FROM settings")
        uids = {int(r["user_id"]) for r in rows} or {0}
    except Exception:  # noqa: BLE001 — 旧库可能还没有 user_id 列
        uids = {0}
    params = [(uid, k, v) for uid in sorted(uids) for k, v in DEFAULT_SETTINGS.items()]
    await conn.executemany(
        "INSERT OR IGNORE INTO settings(user_id,key,value) VALUES(?,?,?)", params
    )

async def _migrate_sessions_from_runs() -> None:
    """历史迁移：已有问答（旧库）按 thread 生成会话，标题取该线程首个问题。

    系统归档线程（cron 晨报、skill:<id> 技能定时触发）不属于「问AI」会话列表：
    它们由 save_run(skip_session=True) 写入，此处也必须一并排除，否则重启时会把
    系统产出补建成会话、污染会话列表（skip_session 只拦写入侧）。
    同时自愈清理历史版本已误建的系统线程会话行。
    """
    conn = await _core._conn()
    # 启动期维护：跨租户清理系统归档线程（cron / skill:*）的会话行。
    # 这些线程本就不属于任何用户的会话列表，清理是幂等的全局操作。
    await conn.execute(
        "DELETE FROM sessions WHERE thread_id='cron' OR thread_id LIKE 'skill:%'"  # tenant: allow
    )
    # 按租户各建一份：同一 thread_id 可能属于不同用户，不能混用
    rows = await (
        await conn.execute(
            "SELECT r.user_id, r.thread_id, r.question FROM runs r"
            " WHERE r.id = (SELECT MIN(id) FROM runs x"
            "               WHERE x.thread_id = r.thread_id AND x.user_id = r.user_id)"
            "   AND r.thread_id <> 'cron' AND r.thread_id NOT LIKE 'skill:%'"
            "   AND NOT EXISTS (SELECT 1 FROM sessions s"
            "                   WHERE s.thread_id = r.thread_id AND s.user_id = r.user_id)"
        )
    ).fetchall()
    if not rows:
        await conn.commit()
        return
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for r in rows:
        await conn.execute(
            "INSERT OR IGNORE INTO sessions(user_id,thread_id,title,created_at,updated_at)"
            " VALUES(?,?,?,?,?)",
            (r["user_id"], r["thread_id"], str(r["question"])[:40] or "新会话", now, now),
        )
    await conn.commit()  # M1.3：读池时代所有写路径必须真实提交，否则读池不可见

async def reset_to_seed() -> dict[str, Any]:
    """清空并重新种入示例数据（演示/测试用）。

    只重置示例数据本身（持仓/流水/订阅/负债/预算）与 data_note 标记；用户设置
    （AI 端点与密钥、Agent 配置、偏好、账本假设）一律保留——「恢复示例数据」
    不应把用户的模型密钥与个性化配置一起清掉（e2e 复用在跑的研发服务时同理）。
    """
    from .tenant import current_user_id

    uid = current_user_id()
    conn = await _core._conn()
    for t in (
        "positions",
        "transactions",
        "subscriptions",
        "debts",
        "budgets",
    ):
        # 只清当前租户：此前无 WHERE，任何用户调用都会抹掉全实例账本
        await conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
    # 数据已换回种子 → data_note 标回 seed；其余 settings 全部保留
    await conn.execute(
        "INSERT INTO settings(user_id,key,value) VALUES(?,'data_note','seed') "
        "ON CONFLICT(user_id,key) DO UPDATE SET value='seed'",
        (uid,),
    )
    await _seed_all(uid)
    await conn.commit()
    return {"ok": True, "reset": True}

async def _mark_user_data(conn: aiosqlite.Connection) -> None:
    from .tenant import current_user_id

    await conn.execute(
        "INSERT INTO settings(user_id,key,value) VALUES(?,'data_note','user') "
        "ON CONFLICT(user_id,key) DO UPDATE SET value='user'",
        (current_user_id(),),
    )

PENDING_TTL_MINUTES = 10
