"""多账户合并口径：不重不漏、不猜汇率。

这套断言保护三个容易出错的点：
  1. 本地/模拟盘/实盘三个来源的加总公式；
  2. 外币账户不得被静默折算（必须单列 + 明示）；
  3. 重叠风险必须提示，而不是替用户做决定。
"""

from app.calculations.accounts import merge_accounts


def test_local_only_net_worth():
    r = merge_accounts(local_market_value=200000, local_cash=50000, local_debt=30000, lang="zh")
    assert r["total_net_worth"] == 220000
    assert r["account_count"] == 1


def test_paper_accounts_are_summed():
    r = merge_accounts(
        local_market_value=100000, local_cash=0, local_debt=0,
        paper_accounts=[
            {"account_id": "a", "name": "成长", "equity": 120000, "initial_cash": 100000},
            {"account_id": "b", "name": "稳健", "equity": 80000, "initial_cash": 100000},
        ],
        lang="zh",
    )
    assert r["paper_total"] == 200000
    assert r["total_net_worth"] == 300000
    assert r["account_count"] == 3


def test_foreign_currency_is_not_converted():
    """外币账户必须单列且不计入合计——不能用猜测汇率掩盖敞口。"""
    r = merge_accounts(
        local_market_value=100000, local_cash=0, local_debt=0,
        broker_accounts=[
            {"account_id": "us", "label": "美股", "net_liquidation": 50000, "currency": "USD"},
        ],
        lang="zh",
    )
    assert r["total_net_worth"] == 100000, "USD 不得被当成 CNY 相加"
    usd = [s for s in r["sources"] if s.get("currency") == "USD"][0]
    assert usd["counted"] is False
    assert any("USD" in c for c in r["caveats"])


def test_cny_broker_account_is_counted():
    r = merge_accounts(
        local_market_value=100000, local_cash=0, local_debt=0,
        broker_accounts=[
            {"account_id": "cn", "label": "A股", "net_liquidation": 250000, "currency": "CNY"},
        ],
        lang="zh",
    )
    assert r["broker_total"] == 250000
    assert r["total_net_worth"] == 350000


def test_overlap_warning_when_both_local_and_broker_exist():
    r = merge_accounts(
        local_market_value=100000,
        broker_accounts=[{"account_id": "cn", "net_liquidation": 100000, "currency": "CNY"}],
        lang="zh",
    )
    assert any("重叠" in c for c in r["caveats"])


def test_paper_separation_caveat_present():
    r = merge_accounts(
        local_market_value=1,
        paper_accounts=[{"account_id": "p", "equity": 1, "initial_cash": 1}],
        lang="zh",
    )
    assert any("虚拟资金" in c for c in r["caveats"])


def test_empty_inputs_are_zero_not_error():
    r = merge_accounts(lang="zh")
    assert r["total_net_worth"] == 0
    assert r["account_count"] == 1  # 本地账本恒存在（净值 0）
    assert r["sources"][0]["counted"] is True


def test_english_text_follows_lang():
    r = merge_accounts(local_market_value=1, lang="en")
    assert r["sources"][0]["name"] == "Local ledger"


def test_output_is_deterministic():
    args = dict(local_market_value=1, local_cash=2, local_debt=3,
                paper_accounts=[{"account_id": "a", "equity": 4}], lang="zh")
    assert merge_accounts(**args) == merge_accounts(**args)


def test_counted_total_equals_declared_components():
    """不变量：计入合计 ≥ 各已计入来源之和（防止漏加 silently）。"""
    r = merge_accounts(
        local_market_value=10, local_cash=5, local_debt=1,
        paper_accounts=[{"account_id": "a", "equity": 7}],
        broker_accounts=[{"account_id": "b", "net_liquidation": 3, "currency": "CNY"}],
        lang="zh",
    )
    counted = sum(s["net_worth"] for s in r["sources"] if s["counted"])
    assert abs(counted - r["counted_total"]) < 0.01
