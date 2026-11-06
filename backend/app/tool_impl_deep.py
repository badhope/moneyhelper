"""v4.5 深化工具实现：财税 / 现金流 / 风控 / 对账 / 发票 / 市场温度 / 条件单。

与 tools.py 分开：工具实现按域分文件，避免单文件继续膨胀（tools.py 已 1400+ 行）。
本模块只暴露 `DEEP_TOOL_NAMES`（name, description）与 `DEEP_TOOL_IMPL`（name → 协程），
由 tools.py 合并进统一注册表。
"""

from __future__ import annotations

import json
from typing import Any

from . import db
from .calculations import cashflow_forecast, detect_anomalies, detect_subscriptions


async def tool_tax_calc(args: dict[str, Any]) -> str:
    """税负测算：增值税及附加 / 企业所得税 / 个税累计预扣 / 工资五险一金 / 综合税负。"""
    from .calculations import (
        corporate_income_tax,
        individual_income_tax,
        payroll,
        tax_summary,
        vat,
    )

    kind = str(args.get("kind") or "summary")
    try:
        if kind == "vat":
            out = vat(
                sales=float(args.get("sales") or args.get("revenue") or 0),
                purchases=float(args.get("purchases") or args.get("cost") or 0),
                rate=float(args.get("vat_rate") or 0.13),
                simple=bool(args.get("vat_simple")),
                location=str(args.get("location") or "city"),
            )
        elif kind == "cit":
            out = corporate_income_tax(
                revenue=float(args.get("revenue") or 0),
                cost=float(args.get("cost") or 0),
                expenses=float(args.get("expenses") or 0),
                category=str(args.get("cit_category") or "standard"),
            )
        elif kind == "iit":
            out = individual_income_tax(
                monthly_salary=float(args.get("monthly_salary") or 0),
                months=int(args.get("months") or 1),
                social_insurance=float(args.get("social_insurance") or 0),
                housing_fund=float(args.get("housing_fund") or 0),
                special_additional=float(args.get("special_additional") or 0),
            )
        elif kind == "payroll":
            res = payroll(
                gross_salary=float(args.get("gross_salary") or args.get("monthly_salary") or 0),
                special_additional=float(args.get("special_additional") or 0),
                months=int(args.get("months") or 1),
            )
            out = {
                "gross": res.gross,
                "employee": res.employee,
                "employer": res.employer,
                "employee_total": res.employee_total,
                "employer_total": res.employer_total,
                "income_tax": res.income_tax,
                "net_pay": res.net_pay,
                "employer_cost": res.employer_cost,
                "notes": res.notes,
            }
        else:
            out = tax_summary(
                revenue=float(args.get("revenue") or 0),
                cost=float(args.get("cost") or 0),
                expenses=float(args.get("expenses") or 0),
                vat_rate=float(args.get("vat_rate") or 0.13),
                vat_simple=bool(args.get("vat_simple")),
                location=str(args.get("location") or "city"),
                cit_category=str(args.get("cit_category") or "standard"),
                payroll_gross=float(args.get("payroll_gross") or 0),
            )
    except ValueError as exc:
        return f"税负测算失败：{exc}"
    return json.dumps({"kind": kind, "result": out}, ensure_ascii=False, default=str)


async def tool_cashflow_forecast(args: dict[str, Any]) -> str:
    """现金流三档预测：基于历史月度净流入分布，给出悲观/中性/乐观的余额路径。"""
    positions = await db.list_positions()
    cash = sum(
        float(p.get("shares", 0)) * float(p.get("last", 0))
        for p in positions
        if p.get("kind") == "现金"
    )
    opening = float(args.get("opening_balance") or 0) or cash
    out = cashflow_forecast(
        await db.list_transactions(),
        months_ahead=int(args.get("months_ahead") or 3),
        opening_balance=opening,
    )
    return json.dumps(out, ensure_ascii=False, default=str)


async def tool_scan_subscriptions(_args: dict[str, Any]) -> str:
    """识别订阅扣款：周期、金额、下次扣款日、涨价标记。"""
    out = detect_subscriptions(await db.list_transactions())
    return json.dumps(out, ensure_ascii=False, default=str)


async def tool_debt_payoff_plan(args: dict[str, Any]) -> str:
    """债务清偿规划：按账本负债做逐月摊还模拟，给出还清顺序、月数、总利息与可省利息。"""
    from .calculations import compare_methods, plan_payoff

    debts = []
    for r in await db.list_debts():
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        debts.append(
            {
                "name": name,
                "balance": float(r.get("balance") or 0),
                "rate": float(r.get("rate") or 0),
                "min_payment": float(r.get("monthly") or 0),
            }
        )
    if not debts:
        return json.dumps(
            {
                "available": False,
                "reason": "账本里还没有负债记录，先让用户录入欠款本金、年利率与月供",
            },
            ensure_ascii=False,
        )
    extra = float(args.get("extra_payment") or 0)
    method = str(args.get("method") or "avalanche").lower()
    if args.get("compare"):
        return json.dumps(compare_methods(debts, extra), ensure_ascii=False, default=str)
    order = [x.strip() for x in str(args.get("custom_order") or "").split(",") if x.strip()]
    plan = plan_payoff(
        debts,
        extra_payment=extra,
        method=method,  # type: ignore[arg-type]
        custom_order=order or None,
        include_schedule=False,
    )
    out = plan.to_dict(include_schedule=False)
    out["available"] = True
    out["debts"] = debts
    return json.dumps(out, ensure_ascii=False, default=str)


async def tool_scan_anomalies(args: dict[str, Any]) -> str:
    """异常扣款检测：中位数 + MAD 判离群，输出异常倍数与建议。"""
    out = detect_anomalies(
        await db.list_transactions(), lookback_days=int(args.get("lookback_days") or 180)
    )
    return json.dumps(out, ensure_ascii=False, default=str)


async def tool_pretrade_check(args: dict[str, Any]) -> str:
    """下单前风控：涨跌停/整手/T+1/集中度/日限额/重复单，全通过才放行。"""
    from .calculations import fee_for, pre_trade_check
    from .connect import quote_tencent, store

    symbol = str(args.get("symbol") or "").strip().upper()
    side = str(args.get("side") or "").lower()
    price = float(args.get("price") or 0)
    shares = float(args.get("shares") or 0)

    settings = await db.get_risk_settings()
    positions = await db.list_positions()
    holdings = {
        str(p["symbol"]).upper(): float(p["shares"])
        for p in positions
        if p.get("kind") != "现金"
    }
    total_value = sum(float(p.get("shares", 0)) * float(p.get("last", 0)) for p in positions)
    cash = sum(
        float(p.get("shares", 0)) * float(p.get("last", 0))
        for p in positions
        if p.get("kind") == "现金"
    )
    q = await quote_tencent.quote(symbol)
    intents = await store.list_intents(limit=200)
    out = pre_trade_check(
        symbol=symbol,
        side=side,
        price=price,
        shares=shares,
        cash=cash,
        holdings=holdings,
        last_price=float(q["price"]) if q else None,
        prev_close=float(q["prev_close"]) if q and q.get("prev_close") else None,
        portfolio_value=total_value,
        position_value=round(holdings.get(symbol, 0.0) * float(q["price"]), 2) if q else 0.0,
        daily_used_amount=sum(float(i["price"]) * float(i["shares"]) for i in intents),
        daily_limit=float(settings.get("daily_limit") or 200000),
        recent_orders=[
            {
                "ts": i["created_at"],
                "symbol": i["symbol"],
                "side": i["side"],
                "price": i["price"],
                "shares": i["shares"],
            }
            for i in intents
        ],
        fee=fee_for(side, price * shares) if price > 0 and shares > 0 else 0.0,
        deviation_pct=float(settings.get("deviation_pct") or 3.0),
        concentration_pct=float(settings.get("concentration_pct") or 30.0),
    )
    return json.dumps(out, ensure_ascii=False, default=str)


async def tool_import_brokerage_holdings(args: dict[str, Any]) -> str:
    """导入券商持仓对账单：解析 CSV，可选直接合并进持仓。"""
    from .import_parsers.broker_holdings import parse_holdings

    content = str(args.get("content") or "")
    if not content.strip():
        return "需要提供券商导出的持仓 CSV 全文（content）"
    result = parse_holdings(content)
    preview = result.to_preview()
    if not args.get("apply"):
        return json.dumps({"preview": preview, "applied": 0}, ensure_ascii=False, default=str)

    applied = 0
    errors: list[str] = []
    for p in result.positions:
        try:
            await db.add_position(
                {
                    "symbol": p.symbol,
                    "name": p.name,
                    "kind": p.kind,
                    "industry": "未分类",
                    "shares": p.shares,
                    "cost": p.cost,
                    "last": p.last,
                }
            )
            applied += 1
        except Exception as exc:  # noqa: BLE001 — 单行失败不阻断整批
            errors.append(f"{p.symbol}: {exc}")
    return json.dumps(
        {"preview": preview, "applied": applied, "errors": errors}, ensure_ascii=False, default=str
    )


async def tool_parse_invoice(args: dict[str, Any]) -> str:
    """解析发票票面文本并归档：提取代码/号码/日期/金额/购销方。"""
    from .import_parsers.invoice import parse_invoice_text

    text = str(args.get("text") or "")
    if not text.strip():
        return "需要提供发票票面文本（text）"
    parsed = parse_invoice_text(text)
    record = await db.save_invoice(
        file_name=str(args.get("file_name") or "invoice-text"),
        raw=text.encode("utf-8"),
        parsed=parsed.to_dict(),
    )
    return json.dumps(
        {
            "parsed": parsed.to_dict(),
            "invoice_id": record.get("id"),
            "duplicate": record.get("duplicate"),
        },
        ensure_ascii=False,
        default=str,
    )


async def tool_market_breadth(_args: dict[str, Any]) -> str:
    """市场温度：涨跌家数、涨跌停数、情绪温度与冷热判断。"""
    from .connect import quote_tencent

    return json.dumps(await quote_tencent.market_breadth(), ensure_ascii=False, default=str)


async def tool_stock_profile(args: dict[str, Any]) -> str:
    """个股档案：价格、PE/PB、总/流通市值、换手、量比、振幅、涨跌停价。"""
    from .connect import quote_tencent

    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol:
        return "需要提供 6 位证券代码"
    out = await quote_tencent.profile(symbol)
    if out is None:
        return f"无法获取 {symbol} 的档案（可能不是 A 股/ETF，或行情源不可用）"
    return json.dumps(out, ensure_ascii=False, default=str)


async def tool_conditional_order(args: dict[str, Any]) -> str:
    """创建条件单：价格/涨跌幅触发后生成待确认意图（不直接下单）。"""
    try:
        out = await db.create_conditional(args or {})
    except ValueError as exc:
        return f"创建条件单失败：{exc}"
    return json.dumps(
        {"ok": True, "conditional": out, "hint": "系统按行情检查触发，命中后生成待确认交易意图"},
        ensure_ascii=False,
        default=str,
    )


DEEP_TOOL_NAMES: tuple[tuple[str, str], ...] = (
    (
        "tax_calc",
        "税负测算：增值税及附加（一般/简易计税）、企业所得税（标准/高新/小微）、个税（累计预扣法）、"
        "工资五险一金核算、综合税负率。适合「算一下这个月要交多少税」「税后工资多少」「公司税负多少」。",
    ),
    (
        "debt_payoff_plan",
        "债务清偿规划：按账本负债做逐月摊还模拟，对比雪崩法（按利率，省利息最多）与雪球法（按余额），"
        "输出还清顺序、几个月还清、总利息、相比只付最低月供能省多少。适合「先还哪笔」「多久能还清」「多还 2000 能省多少」。",
    ),
    (
        "cashflow_forecast",
        "现金流预测：按最近几个月真实收支分布，给出未来 1-12 个月悲观/中性/乐观三档余额。"
        "适合「我下个月会不会不够花」「未来三个月现金够不够」。",
    ),
    ("scan_subscriptions", "订阅识别：从流水里找周期性固定扣款，输出下次扣款日与涨价标记。适合「我都有哪些订阅」「哪个会员涨价了」。"),
    ("scan_anomalies", "异常扣款检测：按商户用中位数+MAD 找异常大额支出。适合「这个月有没有异常消费」「哪笔钱花得不对劲」。"),
    ("pretrade_check", "下单前风控检查：涨跌停、整手、T+1、集中度、日限额、重复单。适合在下单前问「这笔能不能买」「为什么下不了单」。"),
    (
        "import_brokerage_holdings",
        "导入券商持仓对账单 CSV：解析代码/名称/数量/成本/现价，可预览或直接合并进持仓。适合「把我的券商持仓导进来」。",
    ),
    ("parse_invoice", "解析并归档发票票面文本：提取发票代码/号码/日期/价税合计/购销方。适合「这张发票帮我记一下」。"),
    ("market_breadth", "市场温度：涨跌家数、涨跌停数量、情绪温度 0-100 与冷热档位。适合「今天市场怎么样」「情绪冷不冷」。"),
    ("stock_profile", "个股档案：PE/PB、总市值/流通市值、换手率、量比、振幅、涨跌停价。适合「茅台现在估值多少」「这只票基本面指标」。"),
    ("conditional_order", "创建条件单：价格跌破/突破或涨跌幅达到阈值时生成待确认指令。适合「跌到 1300 提醒我买」「涨 5% 就卖」。"),
)

DEEP_TOOL_IMPL: dict[str, Any] = {
    "tax_calc": tool_tax_calc,
    "cashflow_forecast": tool_cashflow_forecast,
    "scan_subscriptions": tool_scan_subscriptions,
    "scan_anomalies": tool_scan_anomalies,
    "pretrade_check": tool_pretrade_check,
    "import_brokerage_holdings": tool_import_brokerage_holdings,
    "parse_invoice": tool_parse_invoice,
    "market_breadth": tool_market_breadth,
    "stock_profile": tool_stock_profile,
    "conditional_order": tool_conditional_order,
}


# ---------------------------------------------------------------------------
# v4.6：账单规则归类 / 券商执行状态 / 发票视觉能力
# ---------------------------------------------------------------------------


async def tool_categorize_bills(args: dict[str, Any]) -> str:
    """按规则引擎给一批交易打分类（不写库），返回命中规则与兜底比例。"""
    from .categorize import explain

    rows = args.get("rows")
    if not isinstance(rows, list) or not rows:
        return "需要提供 rows（交易数组），每项至少含 item 与 amount"
    return json.dumps(explain(rows[:200]), ensure_ascii=False, default=str)


async def tool_broker_status(_args: dict[str, Any]) -> str:
    """券商执行层状态：交易开关、dry-run、各适配器本机可用性与问题清单。"""
    from . import broker_adapter

    return json.dumps(broker_adapter.trading_status(), ensure_ascii=False, default=str)


async def tool_broker_preview_order(args: dict[str, Any]) -> str:
    """券商下单预检：跑全部护栏 + 适配器预检，返回是否放行与确认令牌。

    默认 dry_run=true，不会产生真实委托。真实报单需用户自行开启环境变量。
    """
    from decimal import Decimal

    from . import broker_adapter, db

    try:
        req = broker_adapter.OrderRequest(
            symbol=str(args.get("symbol") or "").strip().upper(),
            side=broker_adapter.OrderSide(str(args.get("side") or "buy").lower()),
            quantity=int(args.get("quantity") or 0),
            limit_price=Decimal(str(args.get("limit_price") or 0)),
        )
    except Exception as exc:  # noqa: BLE001 — 参数问题给可读错误
        return f"预检参数无效：{exc}"

    g = broker_adapter.default_guardrails()
    adapter = broker_adapter.build_adapter(g["broker"])
    positions = await db.list_positions()
    total = sum(float(p.get("shares", 0)) * float(p.get("last", 0)) for p in positions)
    held = next((p for p in positions if str(p.get("symbol", "")).upper() == req.symbol), None)
    position_value = float(held.get("shares", 0)) * float(held.get("last", 0)) if held else 0.0
    out = broker_adapter.guarded_submit(
        adapter=adapter,
        req=req,
        guardrails=g,
        portfolio_value=total,
        position_value=position_value,
    )
    if out["ok"] and not g["dry_run"]:
        conf = broker_adapter.issue_confirmation(req, int(g["confirmation_ttl_seconds"]))
        out["confirmation_token"] = conf.token
    out["guardrails"] = g
    return json.dumps(out, ensure_ascii=False, default=str)


async def tool_broker_submit_order(args: dict[str, Any]) -> str:
    """券商报单（需 preview 的 token；默认 dry_run 不会真实下单）。"""
    from decimal import Decimal

    from . import broker_adapter

    try:
        req = broker_adapter.OrderRequest(
            symbol=str(args.get("symbol") or "").strip().upper(),
            side=broker_adapter.OrderSide(str(args.get("side") or "buy").lower()),
            quantity=int(args.get("quantity") or 0),
            limit_price=Decimal(str(args.get("limit_price") or 0)),
        )
    except Exception as exc:  # noqa: BLE001
        return f"报单参数无效：{exc}"
    g = broker_adapter.default_guardrails()
    adapter = broker_adapter.build_adapter(g["broker"])
    out = broker_adapter.guarded_submit(
        adapter=adapter,
        req=req,
        guardrails=g,
        confirmation_token=str(args.get("confirmation_token") or ""),
    )
    return json.dumps(out, ensure_ascii=False, default=str)


async def tool_invoice_vision_status(_args: dict[str, Any]) -> str:
    """探测发票识别能力：二维码解码器 / OCR 引擎 / PDF 表格是否可用。"""
    from .import_parsers.invoice_vision import ocr_available

    qr = {"available": False, "decoders": []}
    for name, module in (("opencv", "cv2"), ("pyzbar", "pyzbar.pyzbar")):
        try:
            __import__(module)
            qr["available"] = True
            qr["decoders"].append(name)
        except ImportError:
            continue
    pdf_available = False
    try:
        import pdfplumber  # type: ignore  # noqa: F401

        pdf_available = True
    except ImportError:
        pass
    return json.dumps(
        {"qr": qr, "ocr": ocr_available(), "pdf_tables": {"available": pdf_available}},
        ensure_ascii=False,
        default=str,
    )


DEEP_TOOL_NAMES = (
    *DEEP_TOOL_NAMES,
    (
        "categorize_bills",
        "账单智能归类：按规则引擎（商户/摘要/收支/金额多维匹配）给交易打分类，返回命中规则与兜底比例。适合「帮我看看这些账单怎么归类」「哪些消费没分类」。",
    ),
    ("broker_status", "券商执行层状态：交易开关、dry-run、各券商适配器（QMT/easytrader）本机可用性与缺失项。适合「能不能自动下单」「需要装什么」。"),
    ("broker_preview_order", "券商下单预检：跑资金上限/日限额/集中度/白名单/二次确认等全部护栏，返回放行结果与确认令牌（默认 dry-run，不下单）。"),
    ("broker_submit_order", "券商报单：必须带预检令牌；默认 dry-run 只返回模拟结果，真实开启需用户配置环境变量。"),
    ("invoice_vision_status", "探测发票识别能力：二维码解码器、OCR 引擎、PDF 表格解析是否可用，缺失时给安装建议。"),
)

DEEP_TOOL_IMPL = {
    **DEEP_TOOL_IMPL,
    "categorize_bills": tool_categorize_bills,
    "broker_status": tool_broker_status,
    "broker_preview_order": tool_broker_preview_order,
    "broker_submit_order": tool_broker_submit_order,
    "invoice_vision_status": tool_invoice_vision_status,
    "debt_payoff_plan": tool_debt_payoff_plan,
}
