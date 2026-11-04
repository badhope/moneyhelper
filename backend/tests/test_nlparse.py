"""一句话记账规则引擎单测：金额提取、相对/显式日期、收支方向。"""

from __future__ import annotations

from datetime import datetime, timedelta

from app import nlparse


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


def test_amount_prefers_currency_marked_number() -> None:
    """句中另有月份/型号/数量数字时，金额仍取带货币语义的那个。"""
    assert nlparse.parse("9月工资 8000 到账")["amount"] == 8000
    assert nlparse.parse("12月房租2000")["amount"] == -2000
    assert nlparse.parse("买iPhone15花了5999元")["amount"] == -5999
    assert nlparse.parse("买了10股5000元")["amount"] == -5000


def test_amount_plain_fallback() -> None:
    """无货币单位时退回「第一个数字」，既有句式不受影响。"""
    assert nlparse.parse("昨天打车 32")["amount"] == -32
    assert nlparse.parse("工资 8000 已到账")["amount"] == 8000
    assert nlparse.parse("买基金 1.5万")["amount"] == -15000
    assert nlparse.parse("乱七八糟") is None


def test_amount_chinese_numerals() -> None:
    """中文数字金额（cn2an）：口语记账里「三十块」「一万二」很常见。"""
    assert nlparse.parse("午饭三十块")["amount"] == -30
    assert nlparse.parse("午饭三十元")["amount"] == -30
    assert nlparse.parse("房租一万二")["amount"] == -12000
    assert nlparse.parse("打车二十")["amount"] == -20
    assert nlparse.parse("工资八千")["amount"] == 8000
    assert nlparse.parse("奶茶十五块五")["amount"] == -15.5


def test_chinese_numerals_need_unit_or_context() -> None:
    """纯中文数字但无货币语义时不猜（「三」「二月」不是金额）。"""
    assert nlparse.parse("三月") is None


def test_relative_date_longest_word_wins() -> None:
    """「大前天」不得被「前天」抢先匹配。"""
    r = nlparse.parse("大前天吃饭 50")
    assert r is not None
    assert (
        r["date"]
        == (datetime.now().astimezone().date() - timedelta(days=3)).isoformat()
    )
    assert r["amount"] == -50


def test_invalid_explicit_date_falls_back_to_today() -> None:
    """日历非法日期不得抛 ValueError（否则 /api/nl-add 直接 500）。"""
    r = nlparse.parse("2026年13月40日 打车10元")
    assert r is not None
    assert r["date"] == _today()
    assert r["amount"] == -10
    assert r["category"] == "交通"


def test_delivery_verb_is_not_income() -> None:
    """「发了快递 12 元」是支出，不得因「发了」被判成收入。"""
    r = nlparse.parse("发了快递 12 元")
    assert r is not None
    assert r["amount"] == -12
    assert r["category"] != "收入"


def test_valid_explicit_date_still_parsed() -> None:
    r = nlparse.parse("2026-09-10 午饭 30 元")
    assert r is not None
    assert r["date"] == "2026-09-10"
    assert r["amount"] == -30


class TestParseMany:
    """一句话多笔：「午餐 45 打车 28」必须落成两条。

    回归背景：原实现只取第一个金额、条目名取全文最后匹配的关键词，
    于是这句话变成「打车 −45」——丢一笔 + 金额与条目错配。
    """

    def test_space_separated_two_items(self):
        from app.nlparse import parse_many

        out = parse_many("午餐 45 打车 28")
        assert out is not None and len(out) == 2
        assert {o["item"] for o in out} == {"午餐", "打车"}
        amounts = sorted(abs(o["amount"]) for o in out)
        assert amounts == [28.0, 45.0]
        assert {o["category"] for o in out} == {"餐饮", "交通"}

    def test_single_item_returns_none(self):
        from app.nlparse import parse_many

        assert parse_many("午餐 45") is None
        assert parse_many("房租 6000 元") is None

    def test_explicit_separators_defer_to_caller(self):
        """已有逗号/顿号时交给上层分段，避免双重切分。"""
        from app.nlparse import parse_many

        assert parse_many("午餐 45，打车 28") is None

    def test_amounts_not_mixed_up(self):
        from app.nlparse import parse_many

        out = parse_many("咖啡 28 房租 6000")
        by_item = {o["item"]: abs(o["amount"]) for o in out or []}
        assert by_item.get("咖啡") == 28.0
        assert by_item.get("房租") == 6000.0
