"""流水路由：增删改查、按月合并、一句话记账（规则优先 + AI 兜底）。"""

from __future__ import annotations

import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import analysis, db
from ..quotes import invalidate_quotes_cache

router = APIRouter()

@router.post("/api/transactions")
async def create_transaction(payload: dict) -> dict:
    date = str(payload.get("date") or "").strip()
    item = str(payload.get("item") or "").strip()
    category = str(payload.get("category") or "其他").strip() or "其他"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return JSONResponse({"error": "日期需为 YYYY-MM-DD 格式"}, status_code=400)
    if not item:
        return JSONResponse({"error": "名称必填"}, status_code=400)
    try:
        amount = float(payload.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return JSONResponse({"error": "金额不合法"}, status_code=400)
    if amount == 0:
        return JSONResponse({"error": "金额不能为 0"}, status_code=400)
    # owner_id 显式传入 or 自动取活跃成员
    owner_id = payload.get("owner_id")
    if owner_id is not None:
        try:
            owner_id = int(owner_id)
        except (TypeError, ValueError):
            return JSONResponse({"error": "owner_id 必须为整数"}, status_code=400)
    is_shared = payload.get("is_shared")
    try:
        return await db.add_transaction(
            date,
            item,
            category,
            amount,
            owner_id=owner_id,
            is_shared=is_shared,
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.get("/api/transactions")
async def get_transactions(member_id: int | None = None) -> dict:
    """查询交易流水。member_id 有值时按家庭可见性过滤（shared=1 OR owner=自己）。"""
    rows = await db.list_transactions(member_id=member_id)
    return {"transactions": rows, "count": len(rows)}


@router.delete("/api/transactions/{tx_id}")
async def remove_transaction(tx_id: int) -> dict:
    return await db.delete_transaction(tx_id)


@router.put("/api/transactions/{tx_id}")
async def update_transaction(tx_id: int, payload: dict) -> dict:
    p = payload or {}
    owner_id = p.get("owner_id")
    if owner_id is not None:
        try:
            owner_id = int(owner_id)
        except (TypeError, ValueError):
            return JSONResponse({"error": "owner_id 必须为整数"}, status_code=400)
    is_shared = p.get("is_shared")
    try:
        return await db.update_transaction(
            tx_id,
            date=p.get("date"),
            item=p.get("item"),
            category=p.get("category"),
            amount=p.get("amount"),
            owner_id=owner_id,
            is_shared=is_shared,
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/api/transactions/merge")
async def merge_transactions(payload: dict) -> dict:
    p = payload or {}
    month = str(p.get("month") or "").strip()
    if not month:
        return JSONResponse({"error": "month 必填，格式 YYYY-MM"}, status_code=400)
    try:
        out = await db.merge_transactions(month, p.get("category"))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    await invalidate_quotes_cache()
    analysis.invalidate_dashboard_cache()
    return out


@router.post("/api/nl-add")
async def nl_add(payload: dict) -> dict:
    """一句话记账：规则解析优先（秒回），规则拿不到金额时升级 AI，AI 也失败则 422 提示。"""
    from .. import nlparse

    text = str((payload or {}).get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "请输入一句话记账内容"}, status_code=400)

    # 先试多笔：「午餐 45 打车 28」必须落成两条，不能压成「打车 −45」。
    many = nlparse.parse_many(text)
    if many:
        try:
            inserted = await db.add_transactions_batch(
                [{"date": m["date"], "item": m["item"], "category": m["category"],
                  "amount": m["amount"]} for m in many]
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=400)
        analysis.invalidate_dashboard_cache()
        return {"ok": True, "source": "rule-multi", "transactions": inserted,
                "count": len(inserted)}

    parsed = nlparse.parse(text)
    source = "rule"
    if parsed is None:
        # 规则拿不到金额 → AI 兜底
        parsed = await nlparse.parse_with_ai(text)
        source = "ai" if parsed else None
    elif parsed["category"] == "其他" and parsed["amount"] < 0:
        # 规则拿到金额但分类不明确（非收入）→ AI 补分类，失败仍用规则结果入账
        ai = await nlparse.parse_with_ai(text)
        if ai is not None:
            parsed, source = ai, "ai"
    if parsed is None:
        return JSONResponse(
            {
                "error": "没读懂这句话，试试「昨天打车 32 元」「工资 8000 已到账」这样的说法"
            },
            status_code=422,
        )
    try:
        ins = await db.add_transaction(
            parsed["date"], parsed["item"], parsed["category"], parsed["amount"]
        )
        rows = await db.fetch_all("SELECT * FROM transactions WHERE id=?", (ins["id"],))
        tx = rows[0] if rows else {"id": ins["id"], **parsed}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    analysis.invalidate_dashboard_cache()
    return {"ok": True, "source": source, "transaction": tx}
