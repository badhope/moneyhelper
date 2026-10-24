"""界面口径回归测试：这些缺陷曾经"看起来正常但数字是错的"，必须锁死。

覆盖的四个真实 bug（均为截图审查发现）：
1. 持仓编辑弹窗把总成本当每股成本回填 → 保存一次成本放大 100 倍
2. 持仓表"占比"含现金、右侧集中度排除现金 → 同屏两个不同的百分比
3. 总览"今日盈亏"分母把总成本又乘一次股数 → 收益率恒为 +0.00%
4. 亏损时文案仍写"浮盈" → 自相矛盾
"""

from __future__ import annotations

import httpx
import pytest
from app import analysis, main
from app import quotes as quotes_mod

POSITIONS = [
    {
        "symbol": "600519",
        "name": "贵州茅台",
        "kind": "股票",
        "industry": "白酒",
        "shares": 100,
        "cost": 1680.0,
        "last": 1521.0,
    },
    {
        "symbol": "CASH",
        "name": "活期现金",
        "kind": "现金",
        "industry": "现金",
        "shares": 1,
        "cost": 40000.0,
        "last": 40000.0,
    },
]
LIVE = {"600519": 1521.0, "CASH": 40000.0}


# --------------------------------------------------------------------------
# 1. 每股成本字段
# --------------------------------------------------------------------------


def test_positions_expose_cost_per_share():
    """positions[].cost 是总额，必须额外给出每股成本供编辑表单回填。"""
    m = analysis.market_view(POSITIONS, LIVE)
    moutai = next(p for p in m["positions"] if p["symbol"] == "600519")
    assert moutai["cost"] == 168000.0  # 100 股 × 1680
    assert moutai["cost_per_share"] == 1680.0


def test_cost_per_share_times_shares_equals_total_cost():
    """不变量：每股成本 × 股数 == 总成本。防止两个字段各算各的漂移。"""
    m = analysis.market_view(POSITIONS, LIVE)
    for p in m["positions"]:
        assert round(p["cost_per_share"] * p["shares"], 2) == p["cost"]


def test_cost_per_share_for_fractional_shares():
    """场外基金常有小数份额：每股成本不能被 round(2) 截断。"""
    positions = [
        {
            "symbol": "110011",
            "name": "混合基金",
            "kind": "基金",
            "industry": "主动权益",
            "shares": 12345.6789,
            "cost": 4.123456,
            "last": 3.58,
        }
    ]
    m = analysis.market_view(positions, {"110011": 3.58})
    p = m["positions"][0]
    assert p["cost_per_share"] == 4.123456
    assert abs(p["cost_per_share"] * p["shares"] - p["cost"]) < 1.0


# --------------------------------------------------------------------------
# 2. 集中度口径
# --------------------------------------------------------------------------


def test_concentration_excludes_cash():
    """双口径：pct 相对总市值（饼图），investable_pct 相对非现金（集中度判定）。"""
    m = analysis.market_view(POSITIONS, LIVE)
    by_name = {a["name"]: a for a in m["concentration"]["by_asset"]}
    # 总市值 192100，茅台 152100 → 79.2%
    assert by_name["贵州茅台"]["pct"] == 79.2
    # 非现金只有茅台 → investable 100%
    assert by_name["贵州茅台"]["investable_pct"] == 100.0
    # 现金 40000 / 192100 = 20.8%（相对总市值，不是 26.3%）
    assert by_name["活期现金"]["pct"] == 20.8
    # 现金不算可投资资产（不计入集中度分母），investable_pct 仍是相对同一分母
    assert by_name["活期现金"]["investable_pct"] == 26.3


def test_concentration_pct_sums_to_100():
    """饼图前提：所有 pct 加起来必须是 100（历史 bug 会得到 126%）。"""
    m = analysis.market_view(POSITIONS, LIVE)
    total = sum(a["pct"] for a in m["concentration"]["by_asset"])
    assert round(total, 1) == 100.0


def test_concentration_falls_back_to_total_when_all_cash():
    positions = [POSITIONS[1]]
    m = analysis.market_view(positions, LIVE)
    assert m["concentration"]["by_asset"][0]["pct"] == 100.0
    assert m["concentration"]["by_asset"][0]["investable_pct"] == 100.0


# --------------------------------------------------------------------------
# 3. 今日盈亏分母
# --------------------------------------------------------------------------


def test_dashboard_position_cost_is_total_not_per_share():
    """前端计算今日收益率用 sum(cost)，因此 cost 必须是总额。

    历史 bug：前端写 cost * shares，分母被放大 100 倍 → +0.00%。
    这条测试锁住后端口径，前端不得再乘。
    """
    m = analysis.market_view(POSITIONS, LIVE)
    non_cash_cost = sum(p["cost"] for p in m["positions"] if p["kind"] != "现金")
    assert non_cash_cost == 168000.0
    today_pnl = 2219.0
    rate = today_pnl / non_cash_cost * 100
    # 1.32% —— 是个有意义的数字，不是 0.00
    assert round(rate, 2) == 1.32


# --------------------------------------------------------------------------
# 4. 盈亏方向文案
# --------------------------------------------------------------------------


def _summary_market(pnl: float) -> dict:
    return {
        "total_market_value": 264884.0,
        "total_cost": 302000.0,
        "total_pnl": pnl,
        "total_pnl_pct": -12.58 if pnl < 0 else 8.5,
        "concentration": {"by_asset": [], "by_industry": [], "threshold_pct": 40},
    }


def test_summary_text_says_loss_when_losing():
    text = analysis.template_answer(
        market=_summary_market(-38116.0),
        ledger=None,
        flags=[],
        has_data=True,
        lang="zh",
    )
    assert "浮亏" in text
    assert "浮盈" not in text


def test_summary_text_says_gain_when_profiting():
    text = analysis.template_answer(
        market=_summary_market(38116.0),
        ledger=None,
        flags=[],
        has_data=True,
        lang="zh",
    )
    assert "浮盈" in text
    assert "浮亏" not in text


def test_summary_text_english_direction():
    text = analysis.template_answer(
        market=_summary_market(-38116.0),
        ledger=None,
        flags=[],
        has_data=True,
        lang="en",
    )
    assert "down" in text.lower()
    assert " up " not in text.lower()


# --------------------------------------------------------------------------
# 5. 健康评分单一口径
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    yield


@pytest.fixture
async def client(monkeypatch):
    async def _snap(positions):
        return {p["symbol"]: float(p["last"]) for p in positions}

    async def _no_indices():
        return []

    async def _no_pnl(positions):
        return {"total": 0.0, "items": {}}

    monkeypatch.setattr(quotes_mod, "live_quotes", _snap)
    monkeypatch.setattr(quotes_mod, "indices_quotes", _no_indices)
    monkeypatch.setattr(quotes_mod, "portfolio_today_pnl", _no_pnl)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


async def test_health_endpoint_matches_health_check_report(client):
    """`/api/calculations/health` 与 `/api/health-check` 必须是同一个分数。

    历史 bug：总览健康卡 51、体检页 50，两套实现各算一遍。
    """
    a = (await client.get("/api/calculations/health")).json()
    b = (await client.get("/api/health-check")).json()
    assert a["score"] == b["score"]
    assert a["grade"] == b["grade"]


async def test_net_worth_uses_same_price_as_dashboard(client):
    """总览净资产与 /api/calculations/net-worth 必须是同一份总资产。

    历史 bug：前者用实时行情、后者用库内快照价，同屏两个差额十几万的总资产。
    """
    dash = (await client.get("/api/dashboard")).json()
    nw = (await client.get("/api/calculations/net-worth")).json()
    assert nw["total_assets"] == pytest.approx(dash["totals"]["total_market_value"], abs=0.01)