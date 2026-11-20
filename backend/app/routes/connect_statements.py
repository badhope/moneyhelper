"""连接中心·账单：PDF 对账单导入、对账与归类规则。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import db
from ..auth import get_current_user
from ._responses import bad as _bad

router = APIRouter(dependencies=[Depends(get_current_user)])

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

    # pdfplumber 抽表 + 抽文本：20MB/多页 PDF 可达数十秒，推入线程池。
    parsed = await asyncio.to_thread(parse_pdf_statement, raw)
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
