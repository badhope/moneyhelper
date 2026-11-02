"""v4.6 攻坚测试：发票二维码/OCR、PDF 对账单、账单规则引擎、券商适配层与护栏。

原则：
- 二维码/OCR/PDF 测试**不依赖**可选依赖是否安装：安装了就验证真实识别，
  未安装就验证降级提示准确（两条路径都必须绿）。
- 券商适配器测试只验证「本机可用的适配器」与护栏逻辑，不尝试真实下单。
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from app import broker_adapter as ba
from app.categorize import (
    BUILTIN_RULES,
    classify_with_rules,
    compile_rules,
    explain,
)
from app.import_parsers.invoice_vision import (
    decode_qr_from_image,
    invoice_from_image,
    ocr_available,
    parse_invoice_qr,
)
from app.import_parsers.pdf_statement import parse_pdf_statement, statement_reconcile

# ---------------------------------------------------------------------------
# 发票二维码
# ---------------------------------------------------------------------------

QR_PAYLOAD = "01,011002100311,12345678,100.00,20261015,123456,abc"


def test_parse_invoice_qr_full() -> None:
    out = parse_invoice_qr(QR_PAYLOAD).to_dict()
    assert out["invoice_code"] == "011002100311"
    assert out["invoice_number"] == "12345678"
    assert out["amount"] == 100.0
    assert out["invoice_date"] == "2026-10-15"
    assert out["checksum"] == "123456"
    assert out["warnings"] == []


def test_parse_invoice_qr_without_header() -> None:
    out = parse_invoice_qr("011002100311,12345678,88.50,20261020,654321").to_dict()
    assert out["invoice_number"] == "12345678"
    assert out["invoice_date"] == "2026-10-20"


def test_parse_invoice_qr_garbage() -> None:
    out = parse_invoice_qr("https://example.com/not-an-invoice").to_dict()
    assert out["invoice_number"] == ""
    assert out["warnings"]


def test_parse_invoice_qr_empty() -> None:
    assert parse_invoice_qr("").warnings


def _make_qr_png(payload: str) -> bytes | None:
    try:
        import qrcode  # type: ignore
    except ImportError:
        return None
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_decode_qr_from_generated_image_or_degrade() -> None:
    raw = _make_qr_png(QR_PAYLOAD)
    if raw is None:
        pytest.skip("未安装 qrcode，跳过图片生成")
    out = decode_qr_from_image(raw)
    if not out["available"]:
        # 没有解码器时必须是明确提示，而不是异常
        assert "未安装" in out["note"]
        return
    assert out["payload"].startswith("01,")
    assert out["decoder"] in ("opencv", "pyzbar")


def test_invoice_from_image_end_to_end_or_hint() -> None:
    raw = _make_qr_png(QR_PAYLOAD)
    if raw is None:
        pytest.skip("未安装 qrcode，跳过图片生成")
    out = invoice_from_image(raw)
    if not out["ok"]:
        assert out["install_hint"]
        return
    assert out["invoice"]["invoice_number"] == "12345678"
    assert out["invoice"]["amount"] == 100.0


def test_invoice_from_non_image_degrades() -> None:
    out = invoice_from_image(b"definitely-not-an-image")
    assert out["ok"] is False
    assert out["install_hint"]


def test_ocr_probe_never_raises() -> None:
    info = ocr_available()
    assert "available" in info and "engines" in info


# ---------------------------------------------------------------------------
# PDF 对账单
# ---------------------------------------------------------------------------


def _make_statement_pdf() -> bytes | None:
    try:
        from reportlab.lib.pagesizes import A4  # type: ignore
        from reportlab.pdfgen import canvas  # type: ignore
    except ImportError:
        return None
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    rows = [
        ["Date", "Description", "Amount"],
        ["2026-09-01", "Ride", "-35.00"],
        ["2026-09-02", "Salary", "20000.00"],
    ]
    x0, y0, rh = 40, 780, 22
    colw = [120, 220, 100]
    c.setFont("Helvetica", 10)
    for ri, row in enumerate(rows):
        x = x0
        for ci, cell in enumerate(row):
            c.rect(x, y0 - (ri + 1) * rh, colw[ci], rh)
            c.drawString(x + 4, y0 - (ri + 1) * rh + 6, cell)
            x += colw[ci]
    c.save()
    return buf.getvalue()


def test_pdf_statement_parse_or_degrade() -> None:
    raw = _make_statement_pdf()
    if raw is None:
        pytest.skip("未安装 reportlab，跳过 PDF 生成")
    out = parse_pdf_statement(raw)
    if out.method == "":
        assert any("pdfplumber" in w or "扫描件" in w for w in out.warnings)
        return
    assert len(out.rows) == 2
    assert out.rows[0].amount == -35.0
    assert out.rows[1].amount == 20000.0


def test_pdf_statement_rejects_empty() -> None:
    out = parse_pdf_statement(b"")
    assert out.warnings and out.rows == []


def test_pdf_statement_garbage_degrades() -> None:
    out = parse_pdf_statement(b"not a pdf at all")
    assert out.warnings or out.rows == []


def test_statement_reconcile_matches_by_date_amount() -> None:
    rows = [
        {"date": "2026-09-01", "amount": -35.0, "item": "打车"},
        {"date": "2026-09-02", "amount": 20000.0, "item": "工资"},
    ]
    ledger = [{"date": "2026-09-01", "amount": -35.0, "item": "DIDI"}]
    out = statement_reconcile(rows, ledger)
    assert out["matched"] == 1
    assert len(out["missing_in_ledger"]) == 1
    assert out["missing_in_ledger"][0]["date"] == "2026-09-02"
    assert out["balanced"] is False


def test_statement_reconcile_balanced() -> None:
    rows = [{"date": "2026-09-01", "amount": -35.0}]
    ledger = [{"date": "2026-09-01", "amount": -35.0}]
    assert statement_reconcile(rows, ledger)["balanced"] is True


# ---------------------------------------------------------------------------
# 账单规则引擎
# ---------------------------------------------------------------------------


def test_rules_sorted_by_specificity() -> None:
    rules = compile_rules()
    specs = [r.specificity() for r in rules]
    assert specs == sorted(specs, reverse=True)
    assert len(rules) == len(BUILTIN_RULES)


def test_classify_ridehail() -> None:
    out = classify_with_rules(peer="滴滴出行", item="滴滴快车", direction="支出", amount=-35)
    assert out.category == "交通"
    assert out.rule_id == "transport-ridehail"
    assert out.fallback is False


def test_classify_salary_income() -> None:
    out = classify_with_rules(item="工资入账", direction="收入", amount=20000)
    assert out.category == "收入"


def test_classify_fallback_marks_review() -> None:
    out = classify_with_rules(item="某个没见过的商户", direction="支出", amount=-10)
    assert out.fallback is True
    assert out.rule_id == "fallback"
    assert "needs_review" in out.tags


def test_classify_direction_filter() -> None:
    # 「转账」规则只按 item 命中；方向不参与该规则，所以正负都能命中
    assert classify_with_rules(item="转账给朋友", direction="支出", amount=-100).category == "转账"


def test_custom_rules_override_builtin() -> None:
    rules = compile_rules(
        [{"id": "custom", "peer": "星巴克", "item": "咖啡", "category": "商务招待"}]
    )
    out = classify_with_rules(peer="星巴克", item="拿铁咖啡", direction="支出", amount=-32, rules=rules)
    assert out.category == "商务招待"
    assert out.rule_id == "custom"


def test_bad_regex_does_not_crash() -> None:
    rules = compile_rules([{"id": "bad", "item": "([", "category": "x"}])
    out = classify_with_rules(item="anything", rules=rules)
    assert out.fallback is True


def test_explain_reports_fallback_pct() -> None:
    rows = [
        {"item": "工资", "amount": 20000},
        {"item": "完全未知的商户", "amount": -10},
    ]
    out = explain(rows)
    assert out["total"] == 2
    assert out["fallback"] == 1
    assert out["fallback_pct"] == 50.0
    assert out["hint"]


def test_explain_low_fallback_no_hint() -> None:
    out = explain([{"item": "工资", "amount": 20000}])
    assert out["fallback"] == 0
    assert out["hint"] == ""


# ---------------------------------------------------------------------------
# 券商适配层与护栏
# ---------------------------------------------------------------------------


def test_adapters_registry_and_probe() -> None:
    adapters = {a["id"]: a for a in ba.list_adapters()}
    assert set(adapters) == set(ba.ALLOWED_BROKERS)
    assert adapters["null"]["available"] is True
    assert adapters["null"]["supports_trading"] is False
    # 实盘适配器在无客户端环境必须报不可用并给出问题清单
    for name in ("xtquant", "easytrader"):
        assert adapters[name]["supports_trading"] is True
        if not adapters[name]["available"]:
            assert adapters[name]["problems"]


def test_build_unknown_adapter_rejected() -> None:
    with pytest.raises(ValueError):
        ba.build_adapter("magic")


def test_default_guardrails_are_safe() -> None:
    g = ba.default_guardrails()
    assert g["trading_enabled"] is False
    assert g["dry_run"] is True
    assert g["broker"] == "null"
    assert g["max_order_amount"] > 0


def _req(**over):
    base = dict(symbol="000001", side=ba.OrderSide.BUY, quantity=100, limit_price=Decimal("11.44"))
    base.update(over)
    return ba.OrderRequest(**base)


def test_guardrail_switch_off_blocks() -> None:
    out = ba.guarded_submit(adapter=ba.build_adapter("paper"), req=_req(), guardrails=ba.default_guardrails())
    assert out["ok"] is False
    assert out["stage"] == "switch"


def test_guardrail_dry_run_default() -> None:
    g = {**ba.default_guardrails(), "trading_enabled": True, "broker": "paper"}
    out = ba.guarded_submit(adapter=ba.build_adapter("paper"), req=_req(), guardrails=g)
    assert out["ok"] is True
    assert out["stage"] == "dry_run"
    assert out["result"]["status"] == "submitted"


def test_guardrail_max_order() -> None:
    g = {**ba.default_guardrails(), "trading_enabled": True, "broker": "paper", "max_order_amount": 100}
    out = ba.guarded_submit(adapter=ba.build_adapter("paper"), req=_req(), guardrails=g)
    assert out["stage"] == "max_order"


def test_guardrail_max_daily() -> None:
    g = {**ba.default_guardrails(), "trading_enabled": True, "broker": "paper"}
    out = ba.guarded_submit(
        adapter=ba.build_adapter("paper"), req=_req(), guardrails=g, daily_used_amount=49_000
    )
    assert out["stage"] == "max_daily"


def test_guardrail_position_ratio() -> None:
    g = {
        **ba.default_guardrails(),
        "trading_enabled": True,
        "broker": "paper",
        "max_position_ratio": 0.01,
    }
    out = ba.guarded_submit(
        adapter=ba.build_adapter("paper"),
        req=_req(),
        guardrails=g,
        portfolio_value=100_000,
        position_value=0,
    )
    assert out["stage"] == "position_ratio"


def test_guardrail_confirmation_required_then_consumed() -> None:
    g = {**ba.default_guardrails(), "trading_enabled": True, "broker": "paper", "dry_run": False}
    adapter = ba.build_adapter("paper")
    req = _req()

    no_token = ba.guarded_submit(adapter=adapter, req=req, guardrails=g)
    assert no_token["stage"] == "confirmation"

    conf = ba.issue_confirmation(req)
    ok = ba.guarded_submit(adapter=adapter, req=req, guardrails=g, confirmation_token=conf.token)
    assert ok["ok"] is True and ok["stage"] == "submitted"

    replay = ba.guarded_submit(adapter=adapter, req=req, guardrails=g, confirmation_token=conf.token)
    assert replay["stage"] == "confirmation"


def test_confirmation_binds_order_content() -> None:
    req = _req()
    conf = ba.issue_confirmation(req)
    other = _req(quantity=200)
    g = {**ba.default_guardrails(), "trading_enabled": True, "broker": "paper", "dry_run": False}
    out = ba.guarded_submit(
        adapter=ba.build_adapter("paper"), req=other, guardrails=g, confirmation_token=conf.token
    )
    assert out["stage"] == "confirmation"
    assert "不一致" in out["message"]


def test_guardrail_broker_mismatch() -> None:
    g = {**ba.default_guardrails(), "trading_enabled": True, "broker": "xtquant"}
    out = ba.guarded_submit(adapter=ba.build_adapter("paper"), req=_req(), guardrails=g)
    assert out["stage"] == "whitelist"


def test_null_broker_never_trades() -> None:
    null = ba.build_adapter("null")
    assert null.submit(_req()).status == ba.OrderStatus.REJECTED
    assert null.preview(_req()).status == ba.OrderStatus.REJECTED
    assert null.get_cash() == Decimal("0")
    assert null.get_positions() == []


def test_trading_status_shape() -> None:
    st = ba.trading_status()
    assert st["guardrails"]["dry_run"] is True
    assert st["current"]["id"] == "null"
    assert "不会产生任何真实委托" in st["note"]


def test_paper_broker_returns_order_id() -> None:
    paper = ba.build_adapter("paper")
    res = paper.submit(_req())
    assert res.status == ba.OrderStatus.SUBMITTED
    assert res.broker_order_id and res.broker_order_id.startswith("paper-")


def test_xtquant_probe_reports_problems_without_env() -> None:
    info = ba.XtQuantBroker().probe()
    if not info["available"]:
        assert info["problems"]
        assert any("xtquant" in p or "QMT" in p for p in info["problems"])


def test_easytrader_probe_reports_problems_without_env() -> None:
    info = ba.EasytraderBroker().probe()
    if not info["available"]:
        assert info["problems"]


def test_qr_invoice_maps_amount_to_total_amount() -> None:
    """回归：二维码字段叫 amount，归档表叫 total_amount；漏映射会让金额静默丢失。"""
    from app.import_parsers.invoice_vision import invoice_from_image

    raw = _make_qr_png(QR_PAYLOAD)
    if raw is None:
        pytest.skip("未安装 qrcode")
    out = invoice_from_image(raw)
    if not out["ok"]:
        pytest.skip("本机无二维码解码器")
    assert out["invoice"]["total_amount"] == 100.0
    assert out["invoice"]["confidence"] == "high"
