"""决策中心：把分散结论收敛成可执行待办。

断言的是「排序与取舍」，不是文案：紧急项必须先出现、缺失领域不占位、
无量化收益的条目不得凭空出现。
"""

from app.calculations.decisions import (
    PRIORITY_HIGH,
    PRIORITY_URGENT,
    build_actions,
)


def test_urgent_risk_ranks_first():
    out = build_actions(
        flags=[
            {"code": "SAVINGS_RATE", "level": "warn", "text": "储蓄率 14%"},
            {"code": "CONCENTRATION", "level": "warn", "text": "茅台 65%"},
        ],
        lang="zh",
    )
    assert out["items"][0]["domain"] == "risk"
    assert out["items"][0]["priority"] == PRIORITY_URGENT


def test_empty_inputs_yield_empty_list():
    out = build_actions(lang="zh")
    assert out == {"items": [], "count": 0, "top": None}


def test_tax_item_only_when_saving_is_positive():
    assert build_actions(tax_saving=0, lang="zh")["count"] == 0
    assert build_actions(tax_saving=None, lang="zh")["count"] == 0
    assert build_actions(tax_saving=800, lang="zh")["count"] == 1


def test_goal_behind_only_when_expired():
    active = {"name": "旅行", "gap": 5000, "pct": 40, "months_left": 6, "done": False}
    expired = {"name": "买房", "gap": 90000, "pct": 10, "months_left": 0, "done": False}
    done = {"name": "买车", "gap": 0, "pct": 100, "months_left": 3, "done": True}
    out = build_actions(goals=[active, expired, done], lang="zh")
    titles = [i["title"] for i in out["items"]]
    assert any("买房" in t for t in titles)
    assert not any("旅行" in t for t in titles)
    assert not any("买车" in t for t in titles)


def test_rebalance_needs_real_amount():
    out = build_actions(
        rebalance=[
            {"symbol": "510300", "side": "buy", "amount": 0},
            {"symbol": "600519", "side": "sell", "amount": 3200},
        ],
        lang="zh",
    )
    assert out["count"] == 1
    assert "600519" in out["items"][0]["title"]


def test_limit_truncates_but_count_reports_all():
    flags = [
        {"code": "CONCENTRATION", "level": "warn", "text": f"标的{i} 超限"}
        for i in range(10)
    ]
    out = build_actions(flags=flags, lang="zh", limit=3)
    assert len(out["items"]) == 3
    assert out["count"] == 10


def test_output_is_deterministic():
    args = dict(
        flags=[{"code": "CONCENTRATION", "level": "warn", "text": "白酒 65%"}],
        tax_saving=500,
        lang="zh",
    )
    assert build_actions(**args) == build_actions(**args)


def test_english_labels_follow_lang():
    out = build_actions(
        flags=[{"code": "CONCENTRATION", "level": "warn", "text": "concentrated"}],
        lang="en",
    )
    assert out["items"][0]["domain_label"] == "Risk"
    assert "Position" in out["items"][0]["title"]


def test_unknown_flag_falls_back_to_generic_item():
    out = build_actions(flags=[{"code": "SOMETHING_NEW", "level": "info", "text": "新提示"}],
                        lang="zh")
    assert out["count"] == 1
    assert out["items"][0]["priority"] >= PRIORITY_HIGH
