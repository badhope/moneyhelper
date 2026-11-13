"""数据可信回归：更新流水拒绝无穷、显式零值不被默认值覆盖。"""

from __future__ import annotations

import pytest
from app import db
from app.calculations.tax import vat
from app.routes.finance_tax import _f


async def test_update_transaction_rejects_infinity(temp_db) -> None:
    await db.add_transaction(
        date="2026-01-01", item="测试-无穷校验", category="其他", amount=-10
    )
    tx = next(t for t in await db.list_transactions() if t["item"] == "测试-无穷校验")
    with pytest.raises(ValueError, match="无穷"):
        await db.update_transaction(tx["id"], amount="inf")
    # 失败不能留下被污染的行
    again = next(t for t in await db.list_transactions() if t["id"] == tx["id"])
    assert again["amount"] == -10


def test_tax_zero_rate_is_not_replaced_by_default() -> None:
    assert _f({"rate": 0}, "rate", 0.13) == 0.0
    assert _f({}, "rate", 0.13) == 0.13
    assert _f({"rate": None}, "rate", 0.13) == 0.13
    assert _f({"rate": ""}, "rate", 0.13) == 0.13


def test_vat_accepts_zero_rate() -> None:
    result = vat(sales=1000.0, rate=0.0)
    assert result["output_vat"] == 0.0
    assert result["vat_payable"] == 0.0
    assert result["total"] == 0.0
