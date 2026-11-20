"""db 只读/轻写查询：持仓、流水、订阅、负债与设置。

只用 _core 的连接与查询助手；写操作只到 settings 这类单语句级别，
多语句事务仍由调用方持 get_write_lock()。
"""

from __future__ import annotations

from typing import Any

from . import _core
from ._schema import DEFAULT_SETTINGS


async def list_positions() -> list[dict[str, Any]]:
    # 租户过滤：只返回当前用户的持仓（默认租户 0 = 未启用登录的本机用户）
    from .tenant import current_user_id

    return await _core.fetch_all(
        "SELECT * FROM positions WHERE user_id=? ORDER BY symbol",
        (current_user_id(),),
    )

async def list_transactions_by_month(month: str) -> list[dict[str, Any]]:
    """取某月流水（YYYY-MM）。账本视图只需要当月，不该拉全表。"""
    from .tenant import current_user_id

    return await _core.fetch_all(
        "SELECT * FROM transactions WHERE user_id=? AND date LIKE ? "
        "ORDER BY date DESC, id DESC",
        (current_user_id(), f"{month}-%"),
    )

async def list_transactions(
    member_id: int | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """列出交易流水。

    - member_id=None：返回当前租户流水（limit 给定时只取最近 N 条）
    - member_id=0 or specific id：返回 shared=1 的流水 + 自己拥有的流水

    limit 存在的意义：仪表盘要展示明细但不该拉全表；十万行账本每次刷新
    全量加载会让首屏随行数变慢。账本视图（月度聚合）另有按月的精确查询。
    """
    from .tenant import current_user_id

    uid = current_user_id()
    if member_id is None:
        if limit is not None:
            return await _core.fetch_all(
                "SELECT * FROM transactions WHERE user_id=? ORDER BY date DESC, id DESC LIMIT ?",
                (uid, max(1, int(limit))),
            )
        return await _core.fetch_all(
            "SELECT * FROM transactions WHERE user_id=? ORDER BY date DESC, id DESC",
            (uid,),
        )
    # 有 member_id：共享流水 + 自己的流水（含私有）
    return await _core.fetch_all(
        "SELECT * FROM transactions WHERE user_id=? AND (is_shared=1 OR owner_id=?) "
        "ORDER BY date DESC, id DESC",
        (uid, member_id),
    )

async def list_subscriptions() -> list[dict[str, Any]]:
    from .tenant import current_user_id

    return await _core.fetch_all(
        "SELECT * FROM subscriptions WHERE user_id=? ORDER BY name",
        (current_user_id(),),
    )

async def list_debts() -> list[dict[str, Any]]:
    from .tenant import current_user_id

    return await _core.fetch_all(
        "SELECT * FROM debts WHERE user_id=? ORDER BY name", (current_user_id(),)
    )

async def get_settings() -> dict[str, str]:
    """当前租户的设置。缺省键回落到 DEFAULT_SETTINGS，保证接口形状稳定。"""
    from .tenant import current_user_id

    rows = await _core.fetch_all(
        "SELECT * FROM settings WHERE user_id=?", (current_user_id(),)
    )
    out = dict(DEFAULT_SETTINGS)
    out.update({r["key"]: r["value"] for r in rows})
    return out

async def set_setting(key: str, value: str) -> dict[str, Any]:
    from .tenant import current_user_id

    conn = await _core._conn()
    await conn.execute(
        "INSERT INTO settings(user_id,key,value) VALUES(?,?,?) "
        "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
        (current_user_id(), str(key), str(value)),
    )
    await conn.commit()
    return {"ok": True}
