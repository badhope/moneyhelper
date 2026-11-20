"""分析内核单测：市场/账本/风控/模板叙述（纯函数，不碰网络与数据库）。"""

from __future__ import annotations

import pytest
from app import analysis, analysis_views


@pytest.fixture(autouse=True)
def _fixed_month(monkeypatch):
    """把账本「本月」口径钉在测试数据的月份上，避免测试随真实日历过期。"""
    # 实现已拆到 analysis_views，patch 要打到实际使用它的模块
    monkeypatch.setattr(analysis_views, "_month_prefix", lambda: "2026-09")


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

TXN = [
    {
        "id": 1,
        "date": "2026-09-02",
        "item": "工资",
        "category": "收入",
        "amount": 24800.0,
    },
    {
        "id": 2,
        "date": "2026-09-03",
        "item": "房租",
        "category": "居住",
        "amount": -5200.0,
    },
    {
        "id": 3,
        "date": "2026-09-05",
        "item": "外卖",
        "category": "餐饮",
        "amount": -1860.0,
    },
    {
        "id": 4,
        "date": "2026-08-20",
        "item": "上月餐费",
        "category": "餐饮",
        "amount": -900.0,
    },  # 上月，应被过滤
]

SETTINGS = {
    "monthly_income": "24800",
    "emergency_target_months": "6",
    "essential_categories": "居住,餐饮,交通",
}


def test_market_view_totals() -> None:
    m = analysis.market_view(POSITIONS, LIVE)
    assert m["total_market_value"] == 100 * 1521.0 + 40000.0
    assert m["total_pnl"] == 100 * (1521.0 - 1680.0)
    assert len(m["positions"]) == 2


def test_market_view_concentration_breach() -> None:
    m = analysis.market_view(POSITIONS, LIVE)
    top = m["concentration"]["by_asset"][0]
    assert top["name"] == "贵州茅台"
    assert any(b["name"] == "贵州茅台" for b in m["concentration"]["asset_breaches"])


def test_ledger_view_filters_other_month() -> None:
    led = analysis.ledger_view(TXN, [], [], SETTINGS, POSITIONS, LIVE)
    assert led["expense"] == 5200.0 + 1860.0  # 上月 900 不计入
    assert led["income"] == 24800.0
    assert round(led["net"], 2) == 24800.0 - 7060.0


def test_ledger_view_emergency() -> None:
    led = analysis.ledger_view(TXN, [], [], SETTINGS, POSITIONS, LIVE)
    em = led["emergency"]
    assert em["essential_monthly"] == 5200.0 + 1860.0
    assert round(em["months_covered"], 1) == round(40000.0 / 7060.0, 1)
    assert em["ok"] is False  # 5.7 个月 < 6 个月目标


def test_risk_checks_flags() -> None:
    m = analysis.market_view(POSITIONS, LIVE)
    led = analysis.ledger_view(TXN, [], [], SETTINGS, POSITIONS, LIVE)
    flags = analysis.risk_checks(m, led)
    codes = {f["code"] for f in flags}
    assert "CONCENTRATION" in codes
    assert "EMERGENCY_FUND" in codes


def test_risk_checks_no_flags_on_healthy() -> None:
    # 多元化组合（含现金）：集中度按「非现金市值」计，三只标的各约 33%，均低于阈值
    healthy_pos = [
        {
            "symbol": "A",
            "name": "沪深300ETF",
            "kind": "ETF",
            "industry": "指数",
            "shares": 120,
            "cost": 100.0,
            "last": 100.0,
        },
        {
            "symbol": "B",
            "name": "消费精选",
            "kind": "基金",
            "industry": "消费",
            "shares": 60,
            "cost": 200.0,
            "last": 200.0,
        },
        {
            "symbol": "C",
            "name": "科技龙头",
            "kind": "基金",
            "industry": "科技",
            "shares": 80,
            "cost": 150.0,
            "last": 150.0,
        },
        {
            "symbol": "CASH",
            "name": "现金",
            "kind": "现金",
            "industry": "现金",
            "shares": 1,
            "cost": 80000.0,
            "last": 80000.0,
        },
    ]
    healthy_tx = [
        {
            "id": 1,
            "date": "2026-09-01",
            "item": "工资",
            "category": "收入",
            "amount": 24800.0,
        },
        {
            "id": 2,
            "date": "2026-09-02",
            "item": "房租",
            "category": "居住",
            "amount": -5000.0,
        },
    ]
    s = {**SETTINGS, "emergency_target_months": "3"}
    m = analysis.market_view(healthy_pos, {p["symbol"]: p["last"] for p in healthy_pos})
    led = analysis.ledger_view(
        healthy_tx,
        [],
        [],
        s,
        healthy_pos,
        {p["symbol"]: p["last"] for p in healthy_pos},
    )
    assert analysis.risk_checks(m, led) == []


def test_emergency_no_data_no_false_alarm() -> None:
    """R1 回归：本月无必要支出数据时，应急金不得误报"仅覆盖 0 个月"。"""
    led = analysis.ledger_view([TXN[0]], [], [], SETTINGS, POSITIONS, LIVE)
    em = led["emergency"]
    assert em["essential_monthly"] == 0.0
    assert em["has_data"] is False

    m = analysis.market_view(POSITIONS, LIVE)
    flags = analysis.risk_checks(m, led)
    assert "EMERGENCY_FUND" not in {f["code"] for f in flags}

    text = analysis.template_answer(m, led, flags)
    assert "可覆盖 0.0 个月" not in text


def test_template_answer_mentions_numbers() -> None:
    m = analysis.market_view(POSITIONS, LIVE)
    led = analysis.ledger_view(TXN, [], [], SETTINGS, POSITIONS, LIVE)
    flags = analysis.risk_checks(m, led)
    text = analysis.template_answer(m, led, flags)
    assert "总市值" in text
    assert "本月" in text or "2026-09" in text
    assert "需关注" in text


def test_next_step_advice_gives_action_for_risk_codes() -> None:
    """主动理财引导：有风险 code 时给出对应下一步动作；无风险/空库时返回空串。"""
    m = analysis.market_view(POSITIONS, LIVE)
    led = analysis.ledger_view(TXN, [], [], SETTINGS, POSITIONS, LIVE)
    flags = analysis.risk_checks(m, led)
    zh = analysis.next_step_advice(flags, True, "zh")
    # 应急金与集中度都命中 → 最多 2 条，均为用户能执行的建议
    assert zh.startswith("下一步你可以：")
    assert "应急金" in zh or "储蓄" in zh
    assert "集中度" in zh or "40%" in zh
    # 空库 → 无引导（不硬塞噪音）
    assert analysis.next_step_advice(flags, False, "zh") == ""
    # 无风险 → 无引导
    assert analysis.next_step_advice([], True, "zh") == ""
    # 语言跟随：en 不含中文
    en = analysis.next_step_advice(flags, True, "en")
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in en)
    assert en.startswith("A next step")
