"""v4.16 审计回归测试：税负引擎与账单解析。

延续 v4.15 的筛选标准——**结果错但接口不报错**。本轮 8 处：

税负（calculations/tax.py）
1. payroll(months>1)：income_tax 是累计口径，net_pay 却只减一个月工资，
   实发被算少且无任何说明。
2. 公积金基数被社保上限压住，与其自身 docstring「常见上限高于社保」矛盾。
3. base_min > base_max 时 min(max(...)) 静默退化，基数与提示文案互相矛盾。
4. vat() 免征分支缺 surcharge_detail，返回结构与计税分支不一致。
5. month_end_checklist 放过 "2026-13" / "2026-00"，清单挂在不存在的月份上。

解析（import_parsers/）
6. _parse_amount 丢掉会计负数与尾随负号的符号，支出导入后变成收入。
7. 微信/支付宝缺「收/支」列时逐行静默跳过：导入"成功"、0 笔、0 条错误。
8. 报错行号与用户文件对不上（过滤空行 + 手工 +1 偏移）；
   generic_csv 把「金额列恒为 0 + 借贷分列」的银行对账单塞成 0 元流水。
"""

from __future__ import annotations

import pytest
from app.calculations.tax import (
    individual_income_tax,
    month_end_checklist,
    payroll,
    vat,
)
from app.import_parsers import get_parser
from app.import_parsers.base import _parse_amount

WECHAT_HEADER = (
    "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注"
)
ALIPAY_HEADER = (
    "交易时间,交易分类,交易对方,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注"
)


def _wechat_csv(rows: list[str], header: str = WECHAT_HEADER, preamble: int = 2) -> str:
    lines = ["微信支付账单明细,,,,,,," for _ in range(preamble)]
    lines.append(header)
    lines.extend(rows)
    return "\n".join(lines) + "\n"


def _alipay_csv(rows: list[str], header: str = ALIPAY_HEADER) -> str:
    lines = ["支付宝交易记录明细查询", "", header, *rows]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 6. 金额解析的符号
# ---------------------------------------------------------------------------


class TestParseAmountSign:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("(1,234.56)", -1234.56),      # 会计负数（银行对账单常见）
            ("（100.00）", -100.0),         # 全角括号
            ("100.00-", -100.0),           # 尾随负号
            ("-100.00", -100.0),           # 前导负号（原本就对，防回归）
            ("¥1,234.56", 1234.56),        # 千分位 + 货币符号
            ("1.234,56", 1234.56),         # 欧式小数逗号
            ("12,34", 12.34),              # 逗号小数
            ("1,234", 1234.0),             # 纯千分位
            ("借方100", 100.0),            # 夹在文字里的数字
            ("", None),
            ("--", None),
            (None, None),
        ],
    )
    def test_sign_and_separators(self, raw, expected):
        assert _parse_amount(raw) == expected

    def test_accounting_negative_flows_through_parser(self):
        """一笔括号负数的支出，导入后必须是支出，不能变成收入。"""
        # 含逗号的字段在真实 CSV 里带引号
        csv_text = (
            "交易日期,摘要,金额\n"
            '2026-03-01,货款,"(1,234.56)"\n'
            "2026-03-02,退款,500.00\n"
        )
        res = get_parser("generic").parse(csv_text)
        assert len(res.transactions) == 2
        assert res.transactions[0].amount == -1234.56
        assert res.transactions[1].amount == 500.0
        assert res.total_expense == -1234.56
        assert res.total_income == 500.0


# ---------------------------------------------------------------------------
# 7. 方向列缺失必须显式失败
# ---------------------------------------------------------------------------


class TestMissingDirectionColumn:
    NO_DIR_HEADER = "交易时间,交易类型,交易对方,商品,金额(元),支付方式,当前状态,交易单号,商户单号,备注"

    def test_wechat_reports_error_instead_of_silent_zero(self):
        row = "2026-03-01 12:00:00,商户消费,某商家,午餐,45.00,零钱,支付成功,1,2,"
        # 金额列现在在索引 4
        csv_text = _wechat_csv([row], header=self.NO_DIR_HEADER)
        res = get_parser("wechat").parse(csv_text)
        assert res.transactions == []
        assert any("收/支" in e for e in res.errors)

    def test_alipay_reports_error_instead_of_silent_zero(self):
        header = "交易时间,交易分类,交易对方,商品说明,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注"
        row = "2026-03-01 12:00:00,餐饮美食,某商家,午餐,45.00,余额宝,交易成功,1,2,"
        res = get_parser("alipay").parse(_alipay_csv([row], header=header))
        assert res.transactions == []
        assert any("收/支" in e for e in res.errors)

    def test_wechat_still_parses_normal_file(self):
        rows = [
            "2026-03-01 12:00:00,商户消费,某商家,午餐,支出,¥45.00,零钱,支付成功,1,2,",
            "2026-03-02 09:00:00,转账,张三,还款,收入,¥500.00,零钱,已存入,3,4,",
            "2026-03-03 09:00:00,零钱提现,自己,,/,¥100.00,零钱,提现成功,5,6,",
        ]
        res = get_parser("wechat").parse(_wechat_csv(rows))
        assert [t.amount for t in res.transactions] == [-45.0, 500.0]
        assert res.total_income == 500.0
        assert res.total_expense == -45.0

    def test_unrecognized_direction_is_reported(self):
        rows = [
            "2026-03-01 12:00:00,商户消费,某商家,午餐,未知方向,¥45.00,零钱,支付成功,1,2,",
            "2026-03-02 09:00:00,转账,张三,还款,收入,¥500.00,零钱,已存入,3,4,",
        ]
        res = get_parser("wechat").parse(_wechat_csv(rows))
        assert len(res.transactions) == 1
        assert any("无法识别" in e for e in res.errors)


# ---------------------------------------------------------------------------
# 8. 行号与 0 元流水
# ---------------------------------------------------------------------------


class TestLineNumbersAndZeroRows:
    def test_wechat_error_line_number_matches_file(self):
        """报错行号必须是用户文件里的真实行号（含前导元信息与空行）。"""
        rows = [
            "2026-03-01 12:00:00,商户消费,某商家,午餐,支出,¥45.00,零钱,支付成功,1,2,",
            "",  # 空行：旧实现会把它过滤掉，导致后续行号整体前移
            "不是日期,商户消费,某商家,晚餐,支出,¥60.00,零钱,支付成功,3,4,",
        ]
        csv_text = _wechat_csv(rows, preamble=2)
        res = get_parser("wechat").parse(csv_text)
        assert len(res.transactions) == 1
        # 前导 2 行 + 表头 1 行 = 第 3 行；数据从第 4 行起，坏行是第 6 行
        assert any("第 6 行" in e for e in res.errors), res.errors

    def test_generic_csv_zero_amount_falls_through_to_debit_credit(self):
        """银行常见排版：金额列恒为 0，真实金额在借方/贷方分列。"""
        csv_text = (
            "交易日期,摘要,金额,借方发生额,贷方发生额\n"
            "2026-03-01,取现,0.00,500.00,0.00\n"
            "2026-03-02,工资,0.00,0.00,8000.00\n"
        )
        res = get_parser("generic").parse(csv_text)
        assert [t.amount for t in res.transactions] == [-500.0, 8000.0]

    def test_generic_csv_rejects_all_zero_row(self):
        csv_text = (
            "交易日期,摘要,金额\n"
            "2026-03-01,测试,0.00\n"
            "2026-03-02,午餐,45.00\n"
        )
        res = get_parser("generic").parse(csv_text)
        assert [t.amount for t in res.transactions] == [45.0]
        assert any("为 0" in e for e in res.errors)

    def test_generic_csv_line_number_with_blank_line(self):
        csv_text = (
            "交易日期,摘要,金额\n"
            "2026-03-01,午餐,45.00\n"
            "\n"
            "坏日期,晚餐,60.00\n"
        )
        res = get_parser("generic").parse(csv_text)
        assert len(res.transactions) == 1
        assert any("第 4 行" in e for e in res.errors), res.errors


# ---------------------------------------------------------------------------
# 1. 工资核算的累计 / 单月口径
# ---------------------------------------------------------------------------


class TestPayrollPeriodSemantics:
    GROSS = 30_000.0

    def _deductions(self, r) -> tuple[float, float]:
        """payroll 实际用的三险一金个人部分（口径必须与被测函数一致）。"""
        si = r.employee["pension"] + r.employee["medical"] + r.employee["unemployment"]
        return si, r.employee["housing_fund"]

    def _cum_tax(self, r, months: int) -> float:
        si, hf = self._deductions(r)
        return individual_income_tax(
            monthly_salary=self.GROSS, months=months, social_insurance=si, housing_fund=hf
        )["cumulative_tax"]

    def _single_month_tax(self, r, months: int) -> float:
        """按累计预扣法算出第 months 个月**当月**应预扣（月薪恒定、此前正常预扣）。"""
        prev = self._cum_tax(r, months - 1) if months > 1 else 0.0
        return round(self._cum_tax(r, months) - prev, 2)

    @pytest.mark.parametrize("months", [1, 2, 3, 6, 12])
    def test_net_pay_is_single_month(self, months):
        r = payroll(gross_salary=self.GROSS, months=months)
        # net_pay 必须是"这一个月"的实发：扣掉当月五险一金与当月应预扣税
        assert r.net_pay == pytest.approx(
            round(self.GROSS - r.employee_total - self._single_month_tax(r, months), 2), abs=0.01
        )
        assert r.net_pay > 0

    @pytest.mark.parametrize("months", [3, 6])
    def test_period_net_pay_covers_whole_period(self, months):
        r = payroll(gross_salary=self.GROSS, months=months)
        assert r.period_net_pay == pytest.approx(
            round(self.GROSS * months - r.employee_total * months - r.income_tax, 2), abs=0.01
        )
        # 累计口径的税必须大于单月税，否则说明两个字段被混用了
        assert r.income_tax > r.current_month_tax
        assert any("累计" in n for n in r.notes)

    def test_already_withheld_makes_current_equals_income_tax(self):
        """传了已预扣税额时，income_tax 本身就是当月应预扣。"""
        probe = payroll(gross_salary=self.GROSS, months=3)
        prev = self._cum_tax(probe, 2)
        r = payroll(gross_salary=self.GROSS, months=3, already_withheld=prev)
        assert r.current_month_tax == r.income_tax
        assert r.income_tax == pytest.approx(self._single_month_tax(probe, 3), abs=0.01)

    def test_months_one_unchanged(self):
        r = payroll(gross_salary=self.GROSS)
        assert r.current_month_tax == r.income_tax
        assert r.period_net_pay == r.net_pay


class TestPayrollBaseClamp:
    def test_housing_base_can_exceed_social_max(self):
        r = payroll(
            gross_salary=50_000,
            housing_base=48_000,
            base_max=35_000,
            housing_base_max=60_000,
        )
        assert r.employee["housing_fund"] == pytest.approx(48_000 * 0.12, abs=0.01)
        # 社保仍按自己的上限钳制
        assert r.employee["pension"] == pytest.approx(35_000 * 0.08, abs=0.01)

    def test_housing_base_defaults_to_social_bounds(self):
        r = payroll(gross_salary=50_000, housing_base=48_000, base_max=35_000)
        assert r.employee["housing_fund"] == pytest.approx(35_000 * 0.12, abs=0.01)
        assert any("公积金基数按 [3500, 35000] 钳制" in n for n in r.notes)

    def test_inverted_bounds_rejected(self):
        with pytest.raises(ValueError):
            payroll(gross_salary=10_000, base_min=35_000, base_max=3_500)
        with pytest.raises(ValueError):
            payroll(gross_salary=10_000, housing_base_min=50_000, housing_base_max=3_500)


# ---------------------------------------------------------------------------
# 4/5. 返回结构一致性与输入校验
# ---------------------------------------------------------------------------


class TestVatShapeAndMonthValidation:
    def test_exempt_branch_has_same_shape(self):
        v = vat(sales=50_000, exempt_threshold=100_000)
        normal = vat(sales=50_000)
        assert v["method"] == "exempt"
        assert set(v) == set(normal)
        assert v["surcharge_detail"] == {
            "city_construction": 0.0,
            "education": 0.0,
            "local_education": 0.0,
        }

    @pytest.mark.parametrize("bad", ["2026-13", "2026-00", "2026-1", "2026-ab", "26-01"])
    def test_invalid_month_rejected(self, bad):
        with pytest.raises(ValueError):
            month_end_checklist(bad)

    def test_valid_month_accepted(self):
        r = month_end_checklist("2026-07")
        assert r["month"] == "2026-07"
        assert r["total"] == 12
        assert r["progress_pct"] == 0.0
