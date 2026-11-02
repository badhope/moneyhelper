"""连接中心深化路由（v4.5）：腾讯行情 / 市场温度 / 个股档案 / 预交易风控 /
券商持仓对账 / 发票归档 / 条件单。

与 routes/connect.py 分文件：连接中心基础能力（目录/连接/配对/同步/意图）已 377 行，
再往里堆会让单文件超过 400 行，违反仓库「按职责分文件」的约定。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import db
from ..auth import get_current_user
from ..calculations import (
    daily_order_amount,
    fee_for,
    pre_trade_check,
    rebalance_orders,
)
from ..connect import quote_tencent, store

router = APIRouter(dependencies=[Depends(get_current_user)])


def _bad(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


# ---------------------------------------------------------------------------
# 腾讯行情 / 市场温度 / 个股档案 / 分时 / K 线备源
# ---------------------------------------------------------------------------


@router.get("/api/connect/market/breadth")
async def market_breadth() -> dict[str, Any]:
    """市场温度：涨跌家数、涨跌停数、情绪温度 0-100。"""
    return await quote_tencent.market_breadth()


@router.get("/api/connect/stock/{symbol}/profile")
async def stock_profile(symbol: str) -> Any:
    """个股档案：价格 + PE/PB + 市值 + 换手/量比/振幅。"""
    out = await quote_tencent.profile(symbol)
    if out is None:
        return _bad(f"无法获取 {symbol} 的档案（可能不是 A 股/ETF，或行情源不可用）", 404)
    return out


@router.get("/api/connect/stock/{symbol}/minute")
async def stock_minute(symbol: str) -> Any:
    """当日分时走势。"""
    out = await quote_tencent.minute(symbol)
    if out is None:
        return _bad(f"无法获取 {symbol} 的分时数据", 404)
    return out


@router.get("/api/connect/kline")
async def connect_kline(symbol: str, period: str = "daily", limit: int = 120) -> Any:
    """K 线（腾讯前复权，作为东财 push2his 的备源）。"""
    out = await quote_tencent.kline(symbol, period, limit)
    if out is None:
        return _bad(f"无法获取 {symbol} 的 K 线", 404)
    return out


# ---------------------------------------------------------------------------
# 预交易风控
# ---------------------------------------------------------------------------


@router.get("/api/connect/risk/settings")
async def risk_settings() -> dict[str, Any]:
    return await db.get_risk_settings()


@router.put("/api/connect/risk/settings")
async def save_risk_settings(payload: dict[str, Any]) -> Any:
    try:
        return await db.save_risk_settings(payload or {})
    except ValueError as exc:
        return _bad(str(exc))


async def _today_bought(symbol: str) -> float:
    """当日模拟盘买入股数（T+1 判定）：扫所有模拟账户当日买单。"""
    today_str = datetime.now().astimezone().strftime("%Y-%m-%d")
    total = 0.0
    for acc in await db.list_accounts():
        for t in await db.get_trades(acc["account_id"]):
            if (
                str(t.get("date", ""))[:10] == today_str
                and t.get("side") == "buy"
                and str(t.get("symbol", "")).upper() == symbol
            ):
                total += float(t.get("shares") or 0)
    return total


@router.post("/api/connect/risk/check")
async def risk_check(payload: dict[str, Any]) -> Any:
    """下单前风控检查：涨跌停 / 整手 / T+1 / 集中度 / 日限额 / 重复单。

    让「AI 想下单」这件事在执行前经过确定性闸门，而不是模型说买就买。
    """
    payload = payload or {}
    symbol = str(payload.get("symbol") or "").strip().upper()
    side = str(payload.get("side") or "").strip().lower()
    try:
        price = float(payload.get("price") or 0)
        shares = float(payload.get("shares") or 0)
    except (TypeError, ValueError):
        return _bad("价格与股数必须是数字")

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
    last_price = float(q["price"]) if q else None
    prev_close = float(q["prev_close"]) if q and q.get("prev_close") else None
    position_value = 0.0
    if last_price:
        position_value = round(holdings.get(symbol, 0.0) * last_price, 2)

    intents = await store.list_intents(limit=200)
    used = daily_order_amount(
        [{"ts": i["created_at"], "price": i["price"], "shares": i["shares"]} for i in intents]
    )
    recent = [
        {
            "ts": i["created_at"],
            "symbol": i["symbol"],
            "side": i["side"],
            "price": i["price"],
            "shares": i["shares"],
        }
        for i in intents
    ]
    fee_est = fee_for(side, price * shares) if (price > 0 and shares > 0) else 0.0

    check = pre_trade_check(
        symbol=symbol,
        side=side,
        price=price,
        shares=shares,
        cash=cash,
        holdings=holdings,
        last_price=last_price,
        prev_close=prev_close,
        today_bought=await _today_bought(symbol),
        portfolio_value=total_value,
        position_value=position_value,
        daily_used_amount=used,
        daily_limit=float(settings.get("daily_limit") or 200000),
        recent_orders=recent,
        fee=fee_est,
        deviation_pct=float(settings.get("deviation_pct") or 3.0),
        concentration_pct=float(settings.get("concentration_pct") or 30.0),
    )
    check["quote"] = {"price": last_price, "prev_close": prev_close, "name": (q or {}).get("name", "")}
    check["available_cash"] = round(cash, 2)
    check["portfolio_value"] = round(total_value, 2)
    check["daily_used"] = used
    return check


@router.post("/api/connect/rebalance/orders")
async def rebalance_orders_api(payload: dict[str, Any]) -> Any:
    """把再平衡清单转成可执行委托（整手取整、先卖后买、资金不足列出缺口）。"""
    items = (payload or {}).get("items")
    if not isinstance(items, list) or not items:
        from ..calculations import compute_rebalance

        targets = await db.list_allocation_targets()
        if not targets:
            return _bad("未提供调仓清单，且尚未设置目标配置", 400)
        positions = await db.list_positions()
        prices = {str(p["symbol"]): float(p.get("last") or 0) for p in positions}
        holdings = [
            {
                "symbol": str(p["symbol"]),
                "name": str(p.get("name") or ""),
                "shares": float(p.get("shares") or 0),
                "last": float(p.get("last") or 0),
            }
            for p in positions
        ]
        plan = compute_rebalance(holdings, targets, prices)
        items = plan.get("items", [])
    return rebalance_orders(
        plan_items=items,
        available_cash=float((payload or {}).get("available_cash") or 0),
        min_order_amount=float((payload or {}).get("min_order_amount") or 1000),
    )


# ---------------------------------------------------------------------------
# 券商持仓对账导入
# ---------------------------------------------------------------------------


@router.post("/api/connect/import/holdings")
async def import_holdings(payload: dict[str, Any]) -> Any:
    """解析券商持仓/对账单并（可选）合并进持仓表。

    content 传 CSV 文本；apply=true 时按 symbol upsert。
    同一文件内容重复导入会被 record_brokerage_import 识别为 duplicate。
    """
    from ..analysis import invalidate_dashboard_cache
    from ..import_parsers.broker_holdings import parse_holdings
    from ..provenance import record_provenance

    payload = payload or {}
    content = str(payload.get("content") or "")
    if not content.strip():
        return _bad("请粘贴券商导出的持仓 CSV 内容")
    result = parse_holdings(content)
    preview = result.to_preview()
    if not payload.get("apply"):
        return {"ok": True, **preview}

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
            errors.append(f"{p.symbol} {p.name}: {exc}")

    record = await db.record_brokerage_import(
        file_name=str(payload.get("file_name") or "holdings.csv"),
        raw=content.encode("utf-8"),
        account=result.account,
        position_count=len(result.positions),
        applied=applied,
        warnings=result.warnings + errors,
    )
    await record_provenance(
        action="import_brokerage_holdings",
        entity_type="position",
        entity_id=f"batch:{applied}",
        before=None,
        after={"applied": applied, "count": len(result.positions), "account": result.account},
        source="connect",
    )
    invalidate_dashboard_cache()
    return {"ok": True, **preview, "applied": applied, "errors": errors, "record": record}


@router.get("/api/connect/import/holdings/history")
async def holdings_import_history(limit: int = 30) -> dict[str, Any]:
    return {"items": await db.list_brokerage_imports(limit)}


# ---------------------------------------------------------------------------
# 发票归档
# ---------------------------------------------------------------------------


@router.post("/api/connect/invoices")
async def upload_invoice(request: Request) -> Any:
    """上传发票（multipart，字段 file）：OFD / PDF / 文本；同一文件幂等。"""
    from ..import_parsers.invoice import parse_invoice

    content_type = (request.headers.get("content-type") or "").lower()
    if not content_type.startswith("multipart/form-data"):
        return _bad("请使用 multipart/form-data 上传（字段名 file）")
    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001
        return _bad(f"表单解析失败：{exc}")
    upload = form.get("file")
    if upload is None or not hasattr(upload, "filename"):
        return _bad("缺少 file 字段")
    raw = await upload.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        return _bad("发票文件超过 20MB")
    parsed = parse_invoice(raw, str(upload.filename or ""))
    record = await db.save_invoice(
        file_name=str(upload.filename or "invoice"),
        raw=raw,
        parsed=parsed.to_dict(),
    )
    return {
        "ok": True,
        "invoice": record,
        "parsed": parsed.to_dict(),
        "duplicate": record.get("duplicate", False),
    }


@router.post("/api/connect/invoices/text")
async def upload_invoice_text(payload: dict[str, Any]) -> Any:
    """粘贴票面文本解析（无文件场景）。"""
    from ..import_parsers.invoice import parse_invoice_text

    text = str((payload or {}).get("text") or "")
    if not text.strip():
        return _bad("请粘贴发票票面文本")
    parsed = parse_invoice_text(text)
    record = await db.save_invoice(
        file_name=str((payload or {}).get("file_name") or "invoice-text"),
        raw=text.encode("utf-8"),
        parsed=parsed.to_dict(),
    )
    return {
        "ok": True,
        "invoice": record,
        "parsed": parsed.to_dict(),
        "duplicate": record.get("duplicate", False),
    }


@router.get("/api/connect/invoices")
async def list_invoices(status: str = "", limit: int = 100) -> dict[str, Any]:
    return {"items": await db.list_invoices(limit, status), "summary": await db.invoice_summary()}


@router.patch("/api/connect/invoices/{iid}")
async def patch_invoice(iid: str, payload: dict[str, Any]) -> Any:
    try:
        return await db.update_invoice_status(
            iid,
            str((payload or {}).get("status") or "archived"),
            str((payload or {}).get("note") or ""),
        )
    except ValueError as exc:
        return _bad(str(exc), 404)


@router.delete("/api/connect/invoices/{iid}")
async def remove_invoice(iid: str) -> dict[str, Any]:
    ok = await db.delete_invoice(iid)
    if not ok:
        raise HTTPException(404, "发票不存在")
    return {"deleted": iid}


# ---------------------------------------------------------------------------
# 条件单
# ---------------------------------------------------------------------------


@router.get("/api/connect/conditionals")
async def list_conditionals(status: str = "") -> dict[str, Any]:
    return {"items": await db.list_conditionals(status)}


@router.post("/api/connect/conditionals")
async def create_conditional(payload: dict[str, Any]) -> Any:
    try:
        return await db.create_conditional(payload or {})
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/connect/conditionals/{cid}/cancel")
async def cancel_conditional(cid: str) -> Any:
    try:
        return await db.update_conditional_status(cid, "cancelled")
    except ValueError as exc:
        return _bad(str(exc), 404)


@router.delete("/api/connect/conditionals/{cid}")
async def delete_conditional(cid: str) -> dict[str, Any]:
    ok = await db.delete_conditional(cid)
    if not ok:
        raise HTTPException(404, "条件单不存在")
    return {"deleted": cid}


@router.post("/api/connect/conditionals/evaluate")
async def evaluate_conditionals() -> dict[str, Any]:
    """检查所有观察中的条件单：命中则生成待确认交易意图（不直接下单）。"""
    watching = await db.list_conditionals("watching")
    if not watching:
        return {"checked": 0, "triggered": [], "message": "没有观察中的条件单"}
    symbols = sorted({str(c["symbol"]) for c in watching})
    quotes = await quote_tencent.quotes_batch(symbols)
    triggered = []
    for c in watching:
        q = quotes.get(str(c["symbol"]).upper())
        if not q:
            continue
        price = float(q["price"])
        prev = float(q.get("prev_close") or 0)
        change_pct = (price / prev - 1) * 100 if prev > 0 else 0.0
        tv = float(c["trigger_value"])
        ttype = str(c["trigger_type"])
        hit = (
            (ttype == "price_below" and price <= tv)
            or (ttype == "price_above" and price >= tv)
            or (ttype == "pct_change_below" and change_pct <= tv)
            or (ttype == "pct_change_above" and change_pct >= tv)
        )
        if not hit:
            continue
        intent = await store.create_intent(
            {
                "symbol": c["symbol"],
                "name": c["name"],
                "side": c["side"],
                "price": c["price"],
                "shares": c["shares"],
                "mode": c["mode"],
                "note": f"条件单触发（{ttype} {tv}，当前 {price}）",
            }
        )
        updated = await db.update_conditional_status(c["id"], "triggered")
        triggered.append({"conditional": updated, "intent": intent, "market_price": price})
    return {"checked": len(watching), "triggered": triggered, "quotes_available": len(quotes)}




# ---------------------------------------------------------------------------
# v4.6：发票图片（二维码 + OCR）/ PDF 对账单 / 账单归类规则
# ---------------------------------------------------------------------------


@router.post("/api/connect/invoices/image")
async def upload_invoice_image(request: Request) -> Any:
    """图片发票识别：先读二维码（最准），再 OCR 兜底；都不行时给安装提示。"""
    from ..import_parsers.invoice_vision import invoice_from_image

    content_type = (request.headers.get("content-type") or "").lower()
    if not content_type.startswith("multipart/form-data"):
        return _bad("请使用 multipart/form-data 上传（字段名 file）")
    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001
        return _bad(f"表单解析失败：{exc}")
    upload = form.get("file")
    if upload is None or not hasattr(upload, "filename"):
        return _bad("缺少 file 字段")
    raw = await upload.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        return _bad("图片超过 20MB")

    result = invoice_from_image(raw)
    if not result["ok"]:
        return {
            "ok": False,
            "method": result["method"],
            "invoice": {},
            "warnings": [w for w in result["warnings"] if w],
            "install_hint": result["install_hint"],
        }
    record = await db.save_invoice(
        file_name=str(upload.filename or "invoice-image"),
        raw=raw,
        parsed=result["invoice"],
    )
    return {
        "ok": True,
        "method": result["method"],
        "invoice": record,
        "parsed": result["invoice"],
        "qr": result["qr"],
        "duplicate": record.get("duplicate", False),
        "install_hint": result["install_hint"],
    }


@router.get("/api/connect/invoices/vision/status")
async def vision_status() -> dict[str, Any]:
    """发票视觉能力探测：二维码解码器 / OCR 引擎 / PDF 表格是否可用。"""
    from ..import_parsers.invoice_vision import ocr_available
    from ..import_parsers.pdf_statement import parse_pdf_statement  # noqa: F401

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
    ocr = ocr_available()
    return {
        "qr": qr,
        "ocr": ocr,
        "pdf_tables": {
            "available": pdf_available,
            "note": "" if pdf_available else "安装 pdfplumber 可解析 PDF 表格对账单",
        },
        "hint": "三者全不可用时仍可用 OFD/PDF 文本层/手动粘贴",
    }


@router.post("/api/connect/import/statement-pdf")
async def import_statement_pdf(request: Request) -> Any:
    """PDF 对账单导入：抽表格 → 预览；apply=true 时入账（日期+金额+摘要去重）。"""
    from ..import_parsers.pdf_statement import parse_pdf_statement

    content_type = (request.headers.get("content-type") or "").lower()
    if not content_type.startswith("multipart/form-data"):
        return _bad("请使用 multipart/form-data 上传（字段名 file）")
    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001
        return _bad(f"表单解析失败：{exc}")
    upload = form.get("file")
    if upload is None or not hasattr(upload, "filename"):
        return _bad("缺少 file 字段")
    raw = await upload.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        return _bad("PDF 超过 20MB")

    parsed = parse_pdf_statement(raw)
    preview = parsed.to_preview()
    apply = str(form.get("apply") or "").lower() in ("1", "true", "yes")

    if not apply:
        return {"ok": True, **preview}

    existing = {(r["date"], round(float(r["amount"]), 2), r["item"]) for r in await db.list_transactions()}
    imported = 0
    duplicated = 0
    for row in parsed.rows:
        key = (row.date, round(row.amount, 2), row.item)
        if key in existing:
            duplicated += 1
            continue
        try:
            await db.add_transaction(row.date, row.item[:80], row.category or "其他", row.amount)
            existing.add(key)
            imported += 1
        except Exception as exc:  # noqa: BLE001
            parsed.warnings.append(f"{row.date} {row.item}: {exc}")
    if imported:
        from ..provenance import record_provenance

        await record_provenance(
            action="import_pdf_statement",
            entity_type="transaction",
            entity_id=f"batch:{imported}",
            before=None,
            after={"imported": imported, "duplicated": duplicated, "file": str(upload.filename or "")},
            source="connect",
        )
    return {"ok": True, **preview, "imported": imported, "duplicated": duplicated}


@router.post("/api/connect/statement/reconcile")
async def reconcile_statement(payload: dict[str, Any]) -> Any:
    """对账单 vs 账本核对（按日期+金额匹配）。"""
    from ..import_parsers.pdf_statement import statement_reconcile

    rows = (payload or {}).get("rows")
    if not isinstance(rows, list):
        return _bad("rows 必须是数组")
    ledger = await db.list_transactions()
    return statement_reconcile(rows, ledger)


@router.get("/api/connect/categorize/rules")
async def list_category_rules() -> dict[str, Any]:
    """账单归类规则：内置规则清单 + 规则数（供前端展示与调优）。"""
    from ..categorize import BUILTIN_RULES, compile_rules

    rules = compile_rules()
    return {
        "count": len(rules),
        "rules": [
            {"id": r.id, "category": r.category, "peer": r.peer, "item": r.item, "type": r.type, "specificity": r.specificity()}
            for r in rules
        ],
        "builtin_count": len(BUILTIN_RULES),
        "explain": "具体度 = 非空维度数；同分时精确匹配优先于正则",
    }


@router.post("/api/connect/categorize/preview")
async def preview_categorize(payload: dict[str, Any]) -> Any:
    """给一批交易打分类（不写库），返回命中规则与兜底比例。"""
    from ..categorize import explain

    rows = (payload or {}).get("rows")
    if not isinstance(rows, list) or not rows:
        return _bad("rows 必须是非空数组")
    return explain(rows[:500])


@router.post("/api/connect/categorize/apply")
async def apply_categorize(payload: dict[str, Any]) -> Any:
    """重新归类既有流水：只改 category，不动金额与日期；返回改动条数。"""
    from ..categorize import classify_with_rules

    rows = await db.list_transactions()
    changed = 0
    errors: list[str] = []
    for t in rows:
        r = classify_with_rules(
            peer="",
            item=str(t.get("item") or ""),
            bill_category="",
            direction="收入" if float(t.get("amount") or 0) > 0 else "支出",
            amount=float(t.get("amount") or 0),
        )
        if r.category and r.category != t.get("category") and not r.fallback:
            try:
                await db.update_transaction(int(t["id"]), category=r.category)
                changed += 1
            except Exception as exc:  # noqa: BLE001 — 单条失败不阻断，但必须回报
                errors.append(f"id={t['id']}: {type(exc).__name__}: {exc}")
    return {"ok": True, "changed": changed, "total": len(rows), "errors": errors[:10]}


__all__ = ["router"]
