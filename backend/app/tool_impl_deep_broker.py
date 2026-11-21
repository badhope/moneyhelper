"""深化工具·执行层与票据能力：账单归类、券商状态/预检/报单、发票视觉探测。"""

from __future__ import annotations

import json
from typing import Any

from . import db


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

    from . import broker_adapter

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
        preview_only=True,
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
