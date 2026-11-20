"""订阅到期巡检（scheduler._check_subscriptions_due）行为测试：直接调用、不启动 APScheduler。
通过 patch("app.scheduler_subs.datetime", ...) 固定 today，验证窗口内/外/去重三种场景。
注意：temp_db 会调 reset_to_seed() 种入演示数据（含 健身私教 due_day=5 等），
本模块的测试统一在测例开头先清空 subscriptions 再按需 add。
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from app import db, scheduler


class _FixedDatetime:
    """仅实现 scheduler 需要的 now().astimezone().date()/.isoformat()/.strftime()。"""

    def __init__(self, today: date):
        self._today = today

    def now(self, tz=None):
        today = self._today

        class _Now:
            def astimezone(self, _tz=None):
                t = today

                class _Tz:
                    @staticmethod
                    def date():
                        return t

                    @staticmethod
                    def isoformat(timespec=None):
                        return t.strftime("%Y-%m-%dT08:00:00")

                    @staticmethod
                    def strftime(fmt):
                        return t.strftime(fmt)

                    @property
                    def year(self):
                        return t.year

                    @property
                    def month(self):
                        return t.month

                return _Tz()

        return _Now()


async def _reset_subs():
    """清空 subscriptions（避免 reset_to_seed() 的演示数据污染 due_day 测试）。"""
    await db.execute("DELETE FROM subscriptions")


@pytest.mark.anyio
async def test_sub_due_within_window_writes(temp_db):
    await _reset_subs()
    today = date(2026, 10, 5)
    await db.add_subscription({"name": "Netflix", "monthly": 45.0, "note": "4K", "due_day": "5"})
    with patch("app.scheduler_subs.datetime", _FixedDatetime(today)):
        await scheduler._check_subscriptions_due()

    mem = await db.fetch_all("SELECT * FROM user_memory WHERE kind LIKE 'subscription_due:%'")
    assert len(mem) == 1, "窗口内应写 1 条提醒"
    assert "Netflix" in mem[0]["content"]
    assert "45.00" in mem[0]["content"]
    assert "4K" in mem[0]["content"]


@pytest.mark.anyio
async def test_sub_due_outside_window_skipped(temp_db):
    await _reset_subs()
    today = date(2026, 10, 5)
    await db.add_subscription({"name": "FarSub", "monthly": 10.0, "due_day": "28"})  # 23 天后
    with patch("app.scheduler_subs.datetime", _FixedDatetime(today)):
        await scheduler._check_subscriptions_due()

    mem = await db.fetch_all("SELECT * FROM user_memory WHERE kind LIKE 'subscription_due:%'")
    assert len(mem) == 0, "窗口外应不写"


@pytest.mark.anyio
async def test_sub_no_due_day_skipped(temp_db):
    await _reset_subs()
    today = date(2026, 10, 5)
    await db.add_subscription({"name": "NoDue", "monthly": 20.0, "due_day": ""})
    with patch("app.scheduler_subs.datetime", _FixedDatetime(today)):
        await scheduler._check_subscriptions_due()

    mem = await db.fetch_all("SELECT * FROM user_memory WHERE kind LIKE 'subscription_due:%'")
    assert len(mem) == 0


@pytest.mark.anyio
async def test_sub_dedup_same_month(temp_db):
    await _reset_subs()
    today = date(2026, 10, 5)
    await db.add_subscription({"name": "Once", "monthly": 30.0, "due_day": "5"})
    with patch("app.scheduler_subs.datetime", _FixedDatetime(today)):
        for _ in range(3):
            await scheduler._check_subscriptions_due()

    mem = await db.fetch_all("SELECT * FROM user_memory WHERE kind LIKE 'subscription_due:%'")
    assert len(mem) == 1, "同月应只保留 1 条"
