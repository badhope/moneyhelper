"""证券代码前缀与移动均线的单一真源守卫。

这两个模块的共同背景：同一套规则曾被拆成多份手写实现并逐渐漂移
（代码前缀 3 份、SMA 2 份），漂移的后果是"同一只股票在不同数据源上
拿到不同结果"，而调用方看不出差异。
"""

from __future__ import annotations

import pytest

from app import symbols


@pytest.mark.parametrize(
    ("code", "market"),
    [
        ("600519", "sh"),   # 沪市主板
        ("688981", "sh"),   # 科创板
        ("510300", "sh"),   # 沪市 ETF
        ("000001", "sz"),   # 深市主板
        ("300750", "sz"),   # 创业板
        ("159915", "sz"),   # 深市 ETF
        ("830799", "bj"),   # 北交所（原 sina 实现漏了这一档）
        ("430047", "bj"),
        ("CASH", None),
        ("", None),
        ("60051", None),    # 非 6 位
        ("ABCDEF", None),
    ],
)
def test_market_of(code: str, market: str | None) -> None:
    assert symbols.market_of(code) == market


def test_prefixes_are_consistent_across_sources() -> None:
    """同一代码在各数据源的输出必须能反推回同一个市场。"""
    assert symbols.to_sina("600519") == "sh600519"
    assert symbols.to_tencent("600519") == "sh600519"
    assert symbols.to_secid("600519") == "1.600519"

    assert symbols.to_sina("000001") == "sz000001"
    assert symbols.to_tencent("000001") == "sz000001"
    assert symbols.to_secid("000001") == "0.000001"


def test_beijing_is_only_excluded_where_source_lacks_it() -> None:
    """新浪没有北交所行情，应显式返回 None 让上层走备源，而不是静默给错前缀。"""
    assert symbols.to_sina("830799") is None
    assert symbols.to_tencent("830799") == "bj830799"
    assert symbols.to_secid("830799") is None


def test_unmappable_codes_return_none_everywhere() -> None:
    for code in ("CASH", "", "60051", "abc"):
        assert symbols.to_sina(code) is None
        assert symbols.to_tencent(code) is None
        assert symbols.to_secid(code) is None


def test_sma_no_rounding_by_default_and_rounding_on_demand() -> None:
    from app.calculations._shared import sma

    values = [1.0, 2.0, 3.0, 4.0]
    assert sma(values, 2) == [None, 1.5, 2.5, 3.5]
    # 1/3 这类无法精确表示的均值：指标页要 4 位，回测要全精度
    assert sma([1.0, 1.0, 2.0], 3, ndigits=4) == [None, None, round(4 / 3, 4)]
    assert sma([1.0, 1.0, 2.0], 3)[2] == pytest.approx(4 / 3)


def test_sma_short_input_yields_all_none() -> None:
    from app.calculations._shared import sma

    assert sma([1.0], 5) == [None]
    assert sma([1.0, 2.0], 0) == [None, None]
