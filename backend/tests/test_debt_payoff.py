"""债务清偿规划测试：引擎口径 + 端点契约。

这些测试刻意断言**行为**而不是实现：月数、利息、结清顺序、负摊还告警，
以及端点必须给出可读的 400 而不是 500。
"""

from __future__ import annotations

import httpx
import pytest
from app import main
from app.calculations.debt_payoff import (
    DebtItem,
    compare_methods,
    plan_payoff,
)


@pytest.fixture
async def client(temp_db):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


def _debts() -> list[dict]:
    return [
        {"name": "信用卡", "balance": 20000, "rate": 0.18, "min_payment": 1000},
        {"name": "消费贷", "balance": 50000, "rate": 0.06, "min_payment": 1500},
        {"name": "花呗", "balance": 3000, "rate": 0.12, "min_payment": 300},
    ]


class TestOrdering:
    def test_avalanche_orders_by_rate_desc(self):
        plan = plan_payoff(_debts(), extra_payment=2000, method="avalanche")
        assert plan.order == ["信用卡", "花呗", "消费贷"]

    def test_snowball_orders_by_balance_asc(self):
        plan = plan_payoff(_debts(), extra_payment=2000, method="snowball")
        assert plan.order == ["花呗", "信用卡", "消费贷"]

    def test_custom_order_respected(self):
        plan = plan_payoff(
            _debts(), extra_payment=2000, method="custom", custom_order=["消费贷", "信用卡"]
        )
        assert plan.order[:2] == ["消费贷", "信用卡"]
        # 未列出的排到最后，不丢数据
        assert plan.order[-1] == "花呗"

    def test_unknown_method_raises(self):
        with pytest.raises(ValueError):
            plan_payoff(_debts(), method="wat")  # type: ignore[arg-type]


class TestSimulation:
    def test_plan_terminates_and_clears_all_debts(self):
        plan = plan_payoff(_debts(), extra_payment=2000)
        assert plan.months > 0
        assert plan.warnings == []
        assert plan.debt_free_date is not None
        last = plan.schedule[-1]
        assert last.balances == {}

    def test_extra_payment_shortens_timeline(self):
        slow = plan_payoff(_debts(), extra_payment=0)
        fast = plan_payoff(_debts(), extra_payment=3000)
        assert fast.months < slow.months
        assert fast.total_interest < slow.total_interest

    def test_interest_saved_matches_baseline(self):
        plan = plan_payoff(_debts(), extra_payment=2000)
        assert plan.baseline_available is True
        assert plan.interest_saved == pytest.approx(
            plan.baseline_interest - plan.total_interest, abs=0.02
        )

    def test_baseline_does_not_depend_on_method(self):
        """「只付最低月供」是同一个客观事实，不能因为排序方法不同给出两个数。

        历史缺陷：基线也重投释放额度，于是雪球/雪崩各得一个不同的「可省利息」。
        """
        a = plan_payoff(_debts(), extra_payment=500, method="avalanche")
        s = plan_payoff(_debts(), extra_payment=500, method="snowball")
        assert a.baseline_interest == s.baseline_interest

    def test_feasible_plan_not_flagged_by_infeasible_baseline(self):
        """基线还不完 ≠ 方案还不完。历史缺陷：基线告警被并进方案 warnings，
        一份 75 个月能还清的计划被判「按当前预算无法还清」。"""
        plan = plan_payoff(
            [{"name": "高息贷", "balance": 100000, "rate": 0.24, "min_payment": 100}],
            extra_payment=2500,
        )
        assert plan.warnings == []
        assert plan.debt_free_date is not None
        assert plan.baseline_available is False
        assert plan.interest_saved is None, "基线不可算时不得硬写成 0"

    def test_debt_clearing_this_month_is_not_negative_amortization(self):
        """某笔债当月结清、实付被余额压低时，不能误报「还不完」。

        历史缺陷：用「当期总还款 vs 当期总利息」判定，500+100=600 < 利息 750
        就报负摊还，而实际月供合计 1100 完全够。
        """
        plan = plan_payoff(
            [
                {"name": "快还完", "balance": 500, "rate": 0, "min_payment": 1000},
                {"name": "高息", "balance": 50000, "rate": 0.18, "min_payment": 100},
            ],
            extra_payment=0,
        )
        assert plan.warnings == []
        assert plan.months > 1
        assert plan.debt_free_date is not None

    def test_surplus_of_overpaid_minimum_is_reallocated(self):
        """月供大于余额的差额必须当期转投，不能凭空消失。

        否则逐月明细的实付合计与 monthly_budget 对不上，方案整体偏长。
        """
        plan = plan_payoff(
            [
                {"name": "小额", "balance": 100, "rate": 0, "min_payment": 5000},
                {"name": "大额", "balance": 50000, "rate": 0.24, "min_payment": 100},
            ],
            extra_payment=0,
        )
        first = plan.schedule[0]
        # 首月实付应达到月供合计（5100），而不是只付 200
        assert sum(first.payments.values()) == pytest.approx(plan.monthly_budget, abs=1.0)

    def test_total_paid_equals_principal_plus_interest(self):
        plan = plan_payoff(_debts(), extra_payment=2000)
        principal = 73000.0
        assert plan.total_paid == pytest.approx(principal + plan.total_interest, abs=0.5)

    def test_milestones_are_chronological(self):
        plan = plan_payoff(_debts(), extra_payment=2000)
        months = [m["month"] for m in plan.milestones]
        assert months == sorted(months)
        assert {m["name"] for m in plan.milestones} == {"信用卡", "消费贷", "花呗"}

    def test_zero_balance_debt_is_ignored(self):
        plan = plan_payoff(
            [{"name": "已还清", "balance": 0, "rate": 0.1, "min_payment": 100}],
            extra_payment=100,
        )
        assert plan.months == 0
        assert plan.total_interest == 0.0

    def test_schedule_can_be_omitted(self):
        plan = plan_payoff(_debts(), extra_payment=1000, include_schedule=False)
        assert plan.schedule == []
        d = plan.to_dict(include_schedule=False)
        assert "schedule" not in d
        # 未收集明细时不给 schedule_months：0 会被读成「零个月」，
        # 而实际是 months 个月（字段整体省略，语义才自洽）
        assert "schedule_months" not in d
        assert d["months"] > 0


class TestNegativeAmortization:
    def test_min_payment_below_interest_flags_warning(self):
        # 余额 100000，年利率 24% → 月息 2000；月供 100 永远还不完
        plan = plan_payoff(
            [{"name": "高息贷", "balance": 100000, "rate": 0.24, "min_payment": 100}],
            extra_payment=0,
        )
        assert plan.warnings
        assert "负摊还" in plan.warnings[0]
        assert plan.debt_free_date is None

    def test_warning_means_no_fake_payoff_date(self):
        plan = plan_payoff(
            [{"name": "高息贷", "balance": 100000, "rate": 0.24, "min_payment": 100}]
        )
        d = plan.to_dict(include_schedule=False)
        assert d["debt_free_date"] is None


class TestValidation:
    def test_negative_extra_rejected(self):
        with pytest.raises(ValueError):
            plan_payoff(_debts(), extra_payment=-1)

    def test_nan_extra_rejected(self):
        with pytest.raises(ValueError):
            plan_payoff(_debts(), extra_payment=float("nan"))

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError):
            DebtItem(name="  ", balance=100, rate=0.1, min_payment=10)

    def test_rate_above_100pct_rejected(self):
        # 常见输入错误：把 12（12%）当 12.0 传进来
        with pytest.raises(ValueError):
            DebtItem(name="x", balance=100, rate=12.0, min_payment=10)

    def test_negative_balance_rejected(self):
        with pytest.raises(ValueError):
            DebtItem(name="x", balance=-1, rate=0.1, min_payment=10)

    def test_empty_list_rejected(self):
        with pytest.raises(ValueError):
            plan_payoff([])

    def test_infinite_min_payment_rejected(self):
        with pytest.raises(ValueError):
            DebtItem(name="x", balance=100, rate=0.1, min_payment=float("inf"))


class TestInputHygiene:
    def test_duplicate_names_rejected(self):
        """重名会让按名字做 dict 时后者覆盖前者，本金凭空消失且无提示。"""
        with pytest.raises(ValueError, match="重复"):
            plan_payoff(
                [
                    {"name": "信用卡", "balance": 10000, "rate": 0.12, "min_payment": 1000},
                    {"name": "信用卡", "balance": 5000, "rate": 0.12, "min_payment": 500},
                ]
            )

    @pytest.mark.parametrize("bad", ["", [], {}, [1], True, 10**400, float("inf")])
    def test_non_numeric_fields_rejected_not_silently_zero(self, bad):
        """空串/空列表/超大整数都不能被静默当成 0——那会产出「已还清」的假结论。"""
        with pytest.raises(ValueError):
            plan_payoff([{"name": "x", "balance": bad, "rate": 0.1, "min_payment": 10}])

    def test_non_dict_item_rejected(self):
        with pytest.raises(ValueError):
            plan_payoff([1, 2, 3])  # type: ignore[list-item]


class TestCompare:
    def test_compare_returns_both_methods(self):
        out = compare_methods(_debts(), extra_payment=2000)
        assert out["avalanche"]["method"] == "avalanche"
        assert out["snowball"]["method"] == "snowball"
        assert isinstance(out["verdict"], str) and out["verdict"]

    def test_avalanche_never_costs_more_interest(self):
        out = compare_methods(_debts(), extra_payment=2000)
        assert out["avalanche"]["total_interest"] <= out["snowball"]["total_interest"] + 0.01

    def test_interest_diff_matches_sign(self):
        out = compare_methods(_debts(), extra_payment=2000)
        computed = round(
            out["snowball"]["total_interest"] - out["avalanche"]["total_interest"], 2
        )
        assert out["interest_diff"] == pytest.approx(computed, abs=0.02)

    def test_infeasible_side_makes_comparison_unavailable(self):
        """一方还不完时不得给利息差额——拿跑满上限的部分利息去减会得出反话。"""
        out = compare_methods(
            [
                {"name": "d0", "balance": 1000, "rate": 0, "min_payment": 1000},
                {"name": "d1", "balance": 3000, "rate": 0.24, "min_payment": 1000},
                {"name": "d2", "balance": 60000, "rate": 0.36, "min_payment": 100},
            ],
            0,
        )
        if out["comparable"]:
            assert out["interest_diff"] is not None
        else:
            assert out["interest_diff"] is None
            assert "不可直接比较" in out["verdict"]

    def test_single_debt_methods_identical(self):
        out = compare_methods(
            [{"name": "一笔", "balance": 10000, "rate": 0.1, "min_payment": 500}], 500
        )
        assert out["avalanche"]["months"] == out["snowball"]["months"]
        assert abs(out["interest_diff"]) < 0.01


class TestPayoffEndpoint:
    """端点契约：可用性、参数校验、错误不得漏成 500。"""

    @pytest.mark.asyncio
    async def test_get_returns_unavailable_without_debts(self, client):
        # seed 库自带负债，这里必须先清空才能验证「没有负债」的降级路径
        from app import db

        for d in await db.list_debts():
            await db.delete_debt(d["name"])
        r = await client.get("/api/finance/debts/payoff")
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is False
        assert body["reason"]

    @pytest.mark.asyncio
    async def test_get_uses_ledger_debts(self, client):
        """默认从账本取数：不传 debts 也要能算出计划。"""
        r = await client.get("/api/finance/debts/payoff?extra_payment=1000")
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        assert body["debts"], "应该返回规划所依据的负债明细"
        assert body["order"]
        assert body["months"] > 0

    @pytest.mark.asyncio
    async def test_post_with_inline_debts(self, client):
        r = await client.post(
            "/api/finance/debts/payoff",
            json={"debts": _debts(), "extra_payment": 2000, "method": "avalanche"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        assert body["months"] > 0
        assert body["order"][0] == "信用卡"

    @pytest.mark.asyncio
    async def test_post_compare_returns_both(self, client):
        r = await client.post(
            "/api/finance/debts/payoff",
            json={"debts": _debts(), "extra_payment": 2000, "compare": True},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["avalanche"]["months"] > 0
        assert body["snowball"]["months"] > 0

    @pytest.mark.asyncio
    async def test_bad_method_is_400_with_readable_message(self, client):
        r = await client.post(
            "/api/finance/debts/payoff", json={"debts": _debts(), "method": "magic"}
        )
        assert r.status_code == 400
        assert "avalanche" in r.json()["error"]

    @pytest.mark.asyncio
    async def test_negative_extra_is_400(self, client):
        r = await client.get("/api/finance/debts/payoff?extra_payment=-5")
        assert r.status_code == 400
        assert r.json()["error"]

    @pytest.mark.asyncio
    async def test_non_numeric_extra_is_400_not_500(self, client):
        r = await client.post(
            "/api/finance/debts/payoff", json={"debts": _debts(), "extra_payment": "abc"}
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [[1], {"a": 1}, True, 10**400])
    async def test_non_numeric_amount_is_400_not_500(self, client, bad):
        r = await client.post(
            "/api/finance/debts/payoff",
            json={"debts": [{"name": "x", "balance": bad, "rate": 0.1, "min_payment": 10}]},
        )
        assert r.status_code == 400, f"{bad!r} 得到 {r.status_code}: {r.text[:200]}"
        assert r.json()["error"]

    @pytest.mark.asyncio
    async def test_duplicate_names_is_400(self, client):
        r = await client.post(
            "/api/finance/debts/payoff",
            json={
                "debts": [
                    {"name": "同名", "balance": 1000, "rate": 0.1, "min_payment": 100},
                    {"name": "同名", "balance": 2000, "rate": 0.1, "min_payment": 100},
                ]
            },
        )
        assert r.status_code == 400
        assert "重复" in r.json()["error"]

    @pytest.mark.asyncio
    async def test_debts_must_be_array(self, client):
        r = await client.post("/api/finance/debts/payoff", json={"debts": {"a": 1}})
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_too_many_debts_rejected(self, client):
        many = [
            {"name": f"d{i}", "balance": 100, "rate": 0.1, "min_payment": 10} for i in range(60)
        ]
        r = await client.post("/api/finance/debts/payoff", json={"debts": many})
        assert r.status_code == 400
