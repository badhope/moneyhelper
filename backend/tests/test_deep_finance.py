"""v4.5 深化能力测试：税负 / 薪酬 / 现金流 / 预交易 / 持仓对账 / 发票 / 条件单。

全部为确定性引擎或本地解析，不触网（行情用构造数据或 monkeypatch）。
"""

from __future__ import annotations

import io
import zipfile

import pytest
from app import db
from app.calculations import (
    cashflow_forecast,
    corporate_income_tax,
    detect_anomalies,
    detect_subscriptions,
    individual_income_tax,
    limit_prices,
    month_end_checklist,
    payroll,
    pre_trade_check,
    rebalance_orders,
    tax_summary,
    vat,
)

# ---------------------------------------------------------------------------
# 增值税
# ---------------------------------------------------------------------------


def test_vat_general_offsets_input() -> None:
    out = vat(sales=1000, purchases=500, rate=0.13)
    assert out["output_vat"] == 130.0
    assert out["input_vat"] == 65.0
    assert out["vat_payable"] == 65.0
    # 附加税 = 65 * (7% + 3% + 2%) = 7.8
    assert out["surcharge"] == 7.8
    assert out["total"] == 72.8


def test_vat_simple_cannot_deduct() -> None:
    out = vat(sales=1000, purchases=500, simple=True, simple_rate=0.03)
    assert out["vat_payable"] == 30.0
    assert out["input_vat"] == 0.0


def test_vat_negative_payable_floors_at_zero() -> None:
    out = vat(sales=100, purchases=1000, rate=0.13)
    assert out["vat_payable"] == 0.0
    assert "留抵" in out["note"]


def test_vat_exempt_threshold() -> None:
    out = vat(sales=100, exempt_threshold=300)
    assert out["method"] == "exempt"
    assert out["total"] == 0.0


def test_vat_rejects_bad_rate_and_location() -> None:
    with pytest.raises(ValueError):
        vat(sales=100, rate=0.17)
    with pytest.raises(ValueError):
        vat(sales=100, location="mars")


# ---------------------------------------------------------------------------
# 企业所得税
# ---------------------------------------------------------------------------


def test_cit_small_micro_within_limit() -> None:
    out = corporate_income_tax(revenue=2_000_000, cost=1_200_000, expenses=300_000, category="small_micro")
    assert out["taxable_income"] == 500_000.0
    assert out["rate"] == 0.05
    assert out["tax_payable"] == 25_000.0


def test_cit_small_micro_over_limit_falls_back() -> None:
    out = corporate_income_tax(revenue=5_000_000, cost=1_000_000, category="small_micro")
    assert out["rate"] == 0.25
    assert "超过 300 万" in out["note"]


def test_cit_loss_carryforward() -> None:
    out = corporate_income_tax(revenue=1_000_000, cost=200_000, loss_carryforward=300_000)
    assert out["taxable_income"] == 500_000.0
    assert out["loss_used"] == 300_000.0


def test_cit_never_negative_taxable() -> None:
    out = corporate_income_tax(revenue=100_000, cost=500_000)
    assert out["taxable_income"] == 0.0
    assert out["tax_payable"] == 0.0


# ---------------------------------------------------------------------------
# 个人所得税
# ---------------------------------------------------------------------------


def test_iit_single_month() -> None:
    # 30000 - 5000 - 4000 - 1000 - 2000 = 18000；18000*3% = 540
    out = individual_income_tax(
        monthly_salary=30000, social_insurance=4000, housing_fund=1000, special_additional=2000
    )
    assert out["taxable_income"] == 18000.0
    assert out["current_withholding"] == 540.0


def test_iit_cumulative_twelve_months() -> None:
    out = individual_income_tax(
        monthly_salary=30000, months=12, social_insurance=4000, housing_fund=1000, special_additional=2000
    )
    # 216000 落在 144000-300000 档：216000*20% - 16920 = 26280
    assert out["taxable_income"] == 216000.0
    assert out["cumulative_tax"] == 26280.0


def test_iit_already_withheld_cannot_go_negative() -> None:
    out = individual_income_tax(monthly_salary=8000, already_withheld=99999)
    assert out["current_withholding"] == 0.0


def test_iit_rejects_bad_months() -> None:
    with pytest.raises(ValueError):
        individual_income_tax(monthly_salary=10000, months=13)


# ---------------------------------------------------------------------------
# 工资
# ---------------------------------------------------------------------------


def test_payroll_basic() -> None:
    out = payroll(gross_salary=30000, social_base=30000, housing_base=30000, special_additional=2000)
    # 个人：养老 2400 + 医疗 600 + 失业 150 + 公积金 3600 = 6750
    assert out.employee_total == 6750.0
    assert out.employer_total > out.employee_total
    assert out.net_pay == pytest.approx(30000 - 6750 - out.income_tax, abs=0.01)
    assert out.employer_cost == pytest.approx(30000 + out.employer_total, abs=0.01)


def test_payroll_base_clamped() -> None:
    out = payroll(gross_salary=100000, social_base=100000, housing_base=100000)
    assert any("钳制" in n for n in out.notes)


# ---------------------------------------------------------------------------
# 月结清单
# ---------------------------------------------------------------------------


def test_month_end_checklist_progress() -> None:
    out = month_end_checklist("2026-10", completed=["bank_recon", "cash_count"])
    assert out["total"] == len(out["items"])
    assert out["done"] == 2
    assert 0 < out["progress_pct"] < 100


def test_month_end_rejects_bad_month() -> None:
    with pytest.raises(ValueError):
        month_end_checklist("2026/10")


def test_tax_summary_burden() -> None:
    out = tax_summary(revenue=1_000_000, cost=400_000, expenses=200_000)
    assert out["vat"]["vat_payable"] == 78_000.0
    assert out["total_tax"] > 0
    assert 0 < out["tax_burden_pct"] < 100


# ---------------------------------------------------------------------------
# 现金流预测
# ---------------------------------------------------------------------------


def _txns(months: list[int], income: float, expense: float) -> list[dict]:
    rows = []
    for m in months:
        rows.append({"date": f"2026-{m:02d}-05", "amount": income, "item": "工资"})
        rows.append({"date": f"2026-{m:02d}-10", "amount": -expense, "item": "房租"})
    return rows


def test_forecast_insufficient_months() -> None:
    out = cashflow_forecast([{"date": "2026-10-01", "amount": -100, "item": "x"}])
    assert out["available"] is False
    assert "不足" in out["reason"]


def test_forecast_three_scenarios() -> None:
    out = cashflow_forecast(_txns([5, 6, 7, 8, 9, 10], 20000, 8000), opening_balance=50000, months_ahead=3)
    assert out["available"] is True
    assert out["stats"]["median"] == 12000.0
    assert out["scenarios"]["base"]["ending_balance"] == 86000.0
    assert set(out["scenarios"]) == {"pessimistic", "base", "optimistic"}


def test_forecast_flags_negative_balance() -> None:
    out = cashflow_forecast(_txns([5, 6, 7], 5000, 8000), opening_balance=1000, months_ahead=3)
    assert out["scenarios"]["pessimistic"]["goes_negative"] is True
    assert any("转负" in w for w in out["warnings"])


def test_forecast_excludes_large_transactions() -> None:
    rows = _txns([5, 6, 7], 10000, 5000)
    rows.append({"date": "2026-06-20", "amount": -300000, "item": "买车"})
    out = cashflow_forecast(rows, large_amount_threshold=20000)
    assert any(item["item"] == "买车" for item in out["excluded_large"])


# ---------------------------------------------------------------------------
# 订阅识别
# ---------------------------------------------------------------------------


def test_subscription_detected_with_price_hike() -> None:
    rows = [
        {"date": "2026-07-15", "amount": -25, "item": "云盘会员"},
        {"date": "2026-08-15", "amount": -25, "item": "云盘会员"},
        {"date": "2026-09-15", "amount": -30, "item": "云盘会员"},
        {"date": "2026-10-15", "amount": -30, "item": "云盘会员"},
    ]
    out = detect_subscriptions(rows)
    assert out["count"] == 1
    item = out["items"][0]
    assert item["period"] == "monthly"
    assert item["price_hike"] is True
    assert item["previous_amount"] == 25.0
    assert out["hikes"]


def test_subscription_requires_three_samples() -> None:
    rows = [
        {"date": "2026-09-15", "amount": -25, "item": "云盘会员"},
        {"date": "2026-10-15", "amount": -25, "item": "云盘会员"},
    ]
    assert detect_subscriptions(rows)["count"] == 0


def test_variable_amount_not_subscription() -> None:
    rows = [
        {"date": "2026-07-15", "amount": -20, "item": "超市"},
        {"date": "2026-08-15", "amount": -200, "item": "超市"},
        {"date": "2026-09-15", "amount": -35, "item": "超市"},
        {"date": "2026-10-15", "amount": -180, "item": "超市"},
    ]
    assert detect_subscriptions(rows)["count"] == 0


# ---------------------------------------------------------------------------
# 异常检测
# ---------------------------------------------------------------------------


def test_anomaly_detected_by_mad() -> None:
    amounts = [30, 28, 32, 31, 300]
    rows = [
        {"date": f"2026-{m:02d}-05", "amount": -a, "item": "咖啡"}
        for m, a in zip([6, 7, 8, 9, 10], amounts, strict=False)
    ]
    out = detect_anomalies(rows)
    assert out["count"] == 1
    assert out["items"][0]["amount"] == 300.0
    assert out["items"][0]["multiple"] > 5


def test_anomaly_needs_min_samples() -> None:
    rows = [
        {"date": "2026-09-05", "amount": -30, "item": "咖啡"},
        {"date": "2026-10-05", "amount": -300, "item": "咖啡"},
    ]
    assert detect_anomalies(rows)["count"] == 0


# ---------------------------------------------------------------------------
# 预交易风控
# ---------------------------------------------------------------------------


def _base_kwargs(**over):
    kw = dict(
        symbol="600519",
        side="buy",
        price=1500.0,
        shares=100.0,
        cash=500000.0,
        holdings={},
        last_price=1495.0,
        prev_close=1490.0,
        portfolio_value=500000.0,
        position_value=0.0,
    )
    kw.update(over)
    return kw


def test_pretrade_passes_clean_order() -> None:
    out = pre_trade_check(**_base_kwargs())
    assert out["ok"] is True
    assert out["blocking"] == []


def test_pretrade_blocks_non_lot_buy() -> None:
    out = pre_trade_check(**_base_kwargs(shares=150))
    assert out["ok"] is False
    assert any(b["id"] == "lot" for b in out["blocking"])


def test_pretrade_blocks_price_outside_limit() -> None:
    out = pre_trade_check(**_base_kwargs(price=2000.0))
    assert any(b["id"] == "price_limit" for b in out["blocking"])


def test_pretrade_warns_on_price_deviation() -> None:
    out = pre_trade_check(**_base_kwargs(price=1550.0, last_price=1495.0))
    assert out["ok"] is True
    assert any(w["id"] == "deviation" for w in out["warnings"])


def test_pretrade_blocks_insufficient_cash() -> None:
    out = pre_trade_check(**_base_kwargs(cash=1000.0))
    assert any(b["id"] == "cash" for b in out["blocking"])


def test_pretrade_blocks_t_plus_1_sell() -> None:
    out = pre_trade_check(
        **_base_kwargs(side="sell", holdings={"600519": 100.0}, today_bought=100.0)
    )
    assert out["ok"] is False
    assert any(b["id"] in ("holdings", "t_plus_1") for b in out["blocking"])


def test_pretrade_blocks_duplicate_order() -> None:
    from datetime import datetime, timedelta

    out = pre_trade_check(
        **_base_kwargs(
            recent_orders=[
                {
                    "ts": datetime.now() - timedelta(seconds=5),
                    "symbol": "600519",
                    "side": "buy",
                    "price": 1500.0,
                    "shares": 100.0,
                }
            ]
        )
    )
    assert any(b["id"] == "duplicate" for b in out["blocking"])


def test_pretrade_daily_limit() -> None:
    out = pre_trade_check(**_base_kwargs(daily_used_amount=199_000.0, daily_limit=200_000.0))
    assert any(b["id"] == "daily_limit" for b in out["blocking"])


def test_limit_prices_by_board() -> None:
    assert limit_prices("600519", 100)["up"] == 110.0
    assert limit_prices("300750", 100)["up"] == 120.0
    assert limit_prices("830799", 100)["up"] == 130.0
    assert limit_prices("600519", 100, is_st=True)["up"] == 105.0


def test_rebalance_orders_sells_before_buys() -> None:
    out = rebalance_orders(
        plan_items=[
            {"symbol": "600519", "name": "茅台", "action": "buy", "amount": 50000, "price": 1500},
            {"symbol": "000001", "name": "平安", "action": "sell", "amount": 20000, "price": 11.4},
        ],
        available_cash=10000,
    )
    assert len(out["sells"]) == 1
    # 卖出 20000 + 现金 10000 = 30000，买不起 50000（整手 100 股需 150000）
    assert out["buys"] == []
    assert out["skipped"]


def test_rebalance_buy_rounds_to_lot() -> None:
    out = rebalance_orders(
        plan_items=[{"symbol": "000001", "name": "平安", "action": "buy", "amount": 12000, "price": 11.4}],
        available_cash=20000,
    )
    assert out["buys"][0]["shares"] == 1000  # floor(12000/11.4/100)*100


# ---------------------------------------------------------------------------
# 券商持仓解析
# ---------------------------------------------------------------------------


HOLDINGS_CSV = """资金账号:88888888
证券代码,证券名称,持仓数量,可用数量,成本价,现价,市值,浮动盈亏
600519,贵州茅台,100,100,1680.00,1347.33,134733.00,-33267.00
SH510300,沪深300ETF,8000,8000,3.85,4.06,32480.00,1680.00
000001,平安银行,500,0,11.00,11.44,5720.00,220.00
合计,,,,-,-,172933.00,-
"""


def test_parse_holdings_csv() -> None:
    from app.import_parsers.broker_holdings import parse_holdings

    out = parse_holdings(HOLDINGS_CSV)
    assert out.account == "88888888"
    assert len(out.positions) == 3
    assert out.skipped == 1
    symbols = [p.symbol for p in out.positions]
    assert symbols == ["600519", "510300", "000001"]
    assert out.positions[1].kind == "ETF"


def test_parse_holdings_without_header() -> None:
    from app.import_parsers.broker_holdings import parse_holdings

    out = parse_holdings("日期,金额\n2026-10-01,-100\n")
    assert out.positions == []
    assert any("持仓表头" in w for w in out.warnings)


# ---------------------------------------------------------------------------
# 发票解析
# ---------------------------------------------------------------------------


INVOICE_TEXT = """增值税电子普通发票
发票代码 011002100311
发票号码 12345678
开票日期 2026年10月15日
购买方名称 某某科技有限公司
销售方名称 某某餐饮有限公司
项目名称 餐饮服务
价税合计 ¥ 106.00
合计税额 6.00
税率 6%
"""


def test_parse_invoice_text_fields() -> None:
    from app.import_parsers.invoice import parse_invoice_text

    inv = parse_invoice_text(INVOICE_TEXT).to_dict()
    assert inv["invoice_number"] == "12345678"
    assert inv["invoice_date"] == "2026-10-15"
    assert inv["total_amount"] == 106.0
    assert inv["kind"] == "vat_normal"
    assert inv["confidence"] == "high"


def test_parse_invoice_missing_fields_low_confidence() -> None:
    from app.import_parsers.invoice import parse_invoice_text

    inv = parse_invoice_text("一些无关文本").to_dict()
    assert inv["confidence"] == "low"
    assert inv["warnings"]


def test_parse_ofd_zip() -> None:
    from app.import_parsers.invoice import parse_ofd

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Doc_0/Doc_1.xml", "<root><t>发票号码 87654321</t><t>价税合计 88.00</t></root>")
    out = parse_ofd(buf.getvalue())
    assert out.invoice_number == "87654321"
    assert out.total_amount == 88.0


def test_parse_invoice_rejects_bad_zip() -> None:
    from app.import_parsers.invoice import parse_ofd

    out = parse_ofd(b"not a zip")
    assert out.warnings


# ---------------------------------------------------------------------------
# DB：发票幂等 / 条件单 / 风控设置
# ---------------------------------------------------------------------------


async def test_save_invoice_is_idempotent(temp_db) -> None:
    from app.import_parsers.invoice import parse_invoice_text

    parsed = parse_invoice_text(INVOICE_TEXT).to_dict()
    first = await db.save_invoice(file_name="a.txt", raw=b"same-bytes", parsed=parsed)
    assert first["duplicate"] is False
    second = await db.save_invoice(file_name="a.txt", raw=b"same-bytes", parsed=parsed)
    assert second["duplicate"] is True
    assert second["id"] == first["id"]
    summary = await db.invoice_summary()
    assert summary["count"] == 1
    assert summary["total_amount"] == 106.0


async def test_invoice_status_validation(temp_db) -> None:
    from app.import_parsers.invoice import parse_invoice_text

    saved = await db.save_invoice(
        file_name="b.txt", raw=b"another", parsed=parse_invoice_text(INVOICE_TEXT).to_dict()
    )
    updated = await db.update_invoice_status(saved["id"], "archived")
    assert updated["status"] == "archived"
    with pytest.raises(ValueError):
        await db.update_invoice_status(saved["id"], "bogus")


async def test_conditional_order_lifecycle(temp_db) -> None:
    cond = await db.create_conditional(
        {
            "symbol": "600519",
            "name": "贵州茅台",
            "side": "buy",
            "trigger_type": "price_below",
            "trigger_value": 1300,
            "price": 1300,
            "shares": 100,
            "mode": "paper",
        }
    )
    assert cond["status"] == "watching"
    watching = await db.list_conditionals("watching")
    assert [c["id"] for c in watching] == [cond["id"]]

    triggered = await db.update_conditional_status(cond["id"], "triggered")
    assert triggered["status"] == "triggered"
    assert triggered["triggered_at"]

    assert await db.delete_conditional(cond["id"]) is True
    assert await db.list_conditionals() == []


async def test_conditional_validation(temp_db) -> None:
    with pytest.raises(ValueError):
        await db.create_conditional({"symbol": "abc", "side": "buy", "trigger_value": 1, "price": 1, "shares": 1})
    with pytest.raises(ValueError):
        await db.create_conditional(
            {"symbol": "600519", "side": "hold", "trigger_value": 1, "price": 1, "shares": 1}
        )
    with pytest.raises(ValueError):
        await db.create_conditional(
            {"symbol": "600519", "side": "buy", "trigger_type": "nope", "trigger_value": 1, "price": 1, "shares": 1}
        )


async def test_risk_settings_defaults_and_save(temp_db) -> None:
    defaults = await db.get_risk_settings()
    assert defaults["daily_limit"] == 200_000.0
    assert defaults["concentration_pct"] == 30.0

    saved = await db.save_risk_settings({"daily_limit": 50_000, "deviation_pct": 2.0})
    assert saved["daily_limit"] == 50_000.0
    assert saved["deviation_pct"] == 2.0
    # 未传的键保持原值
    assert saved["concentration_pct"] == 30.0

    with pytest.raises(ValueError):
        await db.save_risk_settings({"deviation_pct": 200})
    with pytest.raises(ValueError):
        await db.save_risk_settings({"concentration_pct": 0})


async def test_brokerage_import_dedup(temp_db) -> None:
    first = await db.record_brokerage_import(
        file_name="h.csv", raw=b"csv-bytes", account="8888", position_count=3, applied=3, warnings=[]
    )
    assert first["duplicate"] is False
    second = await db.record_brokerage_import(
        file_name="h.csv", raw=b"csv-bytes", account="8888", position_count=3, applied=3, warnings=[]
    )
    assert second["duplicate"] is True
    history = await db.list_brokerage_imports()
    assert len(history) == 1
