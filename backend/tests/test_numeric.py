"""数值解析单一实现的行为约定。

同一个 `_num` 曾在行情备源、三表指标、技术指标、市场视图各存一份，差异只在
"解析失败返回 0 还是 None"。收敛后用一个 `to_float(raw, default)` 表达，
这里把四种调用形态的预期钉住，避免以后又有人就地复制一份。
"""

from __future__ import annotations

import pytest
from app.numeric import to_float


@pytest.mark.parametrize("raw", [None, "", "-", "abc", True, False])
def test_placeholders_and_bools_become_default(raw):
    assert to_float(raw) is None
    assert to_float(raw, 0.0) == 0.0


@pytest.mark.parametrize(("raw", "want"), [("1.5", 1.5), (-2, -2.0), (0, 0.0), (" 3 ", 3.0)])
def test_numbers_including_negative_and_zero(raw, want):
    assert to_float(raw) == want


def test_default_only_on_failure():
    assert to_float("x", 9.0) == 9.0
    assert to_float("0", 9.0) == 0.0
