"""团队模拟盘 agent 工具的端到端回归（v4.2）。

工具层是模型唯一能触达的写路径：开户 → 下单 → 总览必须真跑通。
此前 tools.py 漏导入盘口校验/估值函数，调用即 NameError，而单测只覆盖了引擎层，
所以整条链路是"测试全绿、线上必炸"。
"""

from __future__ import annotations

import json

import pytest
from app import tools


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    yield


async def test_paper_tools_full_flow() -> None:
    opened = json.loads(await tools.tool_paper_open({"name": "甲组", "initial_cash": 100000}))
    assert opened["ok"] is True
    aid = opened["account_id"]

    traded = json.loads(
        await tools.tool_paper_trade(
            {"account_id": aid, "symbol": "600519", "side": "buy", "price": 100.0, "shares": 100}
        )
    )
    assert traded["ok"] is True
    assert traded["fee"] >= 5.0

    overview = json.loads(await tools.tool_paper_overview({}))
    assert overview["ranking"][0]["account_id"] == aid
    assert overview["summary"]["account_count"] == 1
