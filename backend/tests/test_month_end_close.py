"""月末自动结账：用户不用懂会计、也不用点关账按钮。

覆盖三件事：
1. 没建账（上月期间不存在）时必须静默退出，不能因为定时任务报错而中断其它任务；
2. 已关账的期间重跑必须幂等（不重复处理、不报错）；
3. 有草稿凭证时先自动过账再关账——这是"全托管"的关键一步。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from app import db, scheduler


def _prev_month_end() -> date:
    return date.today().replace(day=1) - timedelta(days=1)


@pytest.mark.asyncio
async def test_noop_when_period_missing(client) -> None:
    # 只有当期期间，没有上月：结账必须什么都不做，且不抛
    await db.gl_bootstrap(0)
    await scheduler._month_end_close()


@pytest.mark.asyncio
async def test_posts_drafts_then_closes(client) -> None:
    prev_end = _prev_month_end()
    await db.gl_bootstrap(0, ref_date=prev_end.isoformat())
    accounts = await db.gl_list_accounts(0)
    cash = next(a for a in accounts if str(a["code"]) == "1001")
    rent = next(a for a in accounts if str(a["code"]) == "6602")

    entry = await db.gl_create_entry(
        0,
        prev_end.isoformat(),
        "月末自动结账测试",
        [
            {"account_id": cash["id"], "debit": 100, "credit": 0},
            {"account_id": rent["id"], "debit": 0, "credit": 100},
        ],
    )
    assert entry["status"] == "draft"

    await scheduler._month_end_close()

    period = next(
        p
        for p in await db.gl_list_periods(0)
        if int(p["year"]) == prev_end.year and int(p["month"]) == prev_end.month
    )
    assert period["status"] == "closed", "上月期间必须已被自动关账"
    got = await db.gl_get_entry(0, int(entry["id"]))
    assert got is not None and got["status"] == "posted", "草稿应先被自动过账"


@pytest.mark.asyncio
async def test_idempotent_on_closed_period(client) -> None:
    prev_end = _prev_month_end()
    await db.gl_bootstrap(0, ref_date=prev_end.isoformat())
    await scheduler._month_end_close()
    # 再跑一次：已关账，不应报错、也不应改动
    await scheduler._month_end_close()
    periods = await db.gl_list_periods(0)
    target = next(
        p
        for p in periods
        if int(p["year"]) == prev_end.year and int(p["month"]) == prev_end.month
    )
    assert target["status"] == "closed"
