"""账单导入与预算体检路由：通用 CSV 预览/确认入账、确定性规则体检。"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import db, evaluate

router = APIRouter()

@router.post("/api/import/generic")
async def import_csv_parse(payload: dict) -> dict:
    """解析通用 CSV → 识别列映射 + 预览（前 15 条）+ 可导入条数统计。

    历史说明：该实现原挂在 /api/import/csv，后被 routes/import_routes.py 的
    源感知解析（微信/支付宝/银行）以同名路径先注册遮蔽，导致通用导入实际不可用。
    M1.4 收尾时迁移到显式路径 /api/import/generic（前端 EntryView 调用）。
    """
    from .. import csvimport

    content = str((payload or {}).get("content") or "").strip()
    if not content:
        return JSONResponse({"error": "请粘贴账单 CSV 内容"}, status_code=400)
    try:
        parsed = csvimport.parse_csv(content)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    mapping = csvimport.detect_mapping(parsed["columns"])
    if mapping["amount"] < 0 or mapping["date"] < 0:
        return JSONResponse(
            {"error": "没能识别出日期/金额列，请确认表头包含「日期」「金额」等关键词"},
            status_code=422,
        )
    year = datetime.now().astimezone().strftime("%Y-%m")
    rows, skips = csvimport.build_rows(
        mapping, parsed["columns"], parsed["rows"], year_fill=year
    )
    return {
        "ok": True,
        "columns": parsed["columns"],
        "mapping": mapping,
        "preview": rows[:15],
        "rows": rows,
        "total": len(rows),
        "skipped": len(skips),
    }


@router.post("/api/import/commit")
async def import_csv_commit(payload: dict) -> dict:
    """按前端确认的 rows 批量入账：**先全量校验，再单事务写入**。

    原实现边校验边写：第 37 行日期非法时，前 36 笔已经 commit 了，
    用户看到 200 + imported=36，以为导入成功一半是"部分失败"，实际是半截账本；
    再导一次就重复记账。现在任何一行不合法 → 整批拒绝并返回具体行号，
    全部合法 → 一个事务落库（失败整批回滚）。
    """
    rows = (payload or {}).get("rows")
    if not isinstance(rows, list) or not rows:
        return JSONResponse({"error": "没有可导入的数据"}, status_code=400)

    cleaned: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for idx, r in enumerate(rows, start=1):
        if not isinstance(r, dict):
            errors.append({"row": idx, "reason": "不是对象"})
            continue
        date = str(r.get("date") or "").strip()
        item = str(r.get("item") or "其他").strip()[:40] or "其他"
        category = str(r.get("category") or "其他").strip() or "其他"
        try:
            amount = float(r.get("amount", 0) or 0)
        except (TypeError, ValueError):
            errors.append({"row": idx, "item": item, "reason": "金额不是数字"})
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            errors.append({"row": idx, "item": item, "reason": "日期格式应为 YYYY-MM-DD"})
            continue
        if not math.isfinite(amount) or amount == 0:
            errors.append({"row": idx, "item": item, "reason": "金额必须是有限非零数字"})
            continue
        cleaned.append({"date": date, "item": item, "category": category, "amount": amount})

    if errors:
        return JSONResponse(
            {
                "ok": False,
                "error": f"{len(errors)} 行数据不合法，已整批取消（未写入任何数据）",
                "errors": errors[:50],
                "total_errors": len(errors),
            },
            status_code=400,
        )

    try:
        out = await db.add_transactions_batch(cleaned)
    except Exception as e:  # noqa: BLE001 — 批量写入失败整批回滚
        return JSONResponse({"ok": False, "error": f"写入失败，已回滚：{e}"}, status_code=500)
    return {"ok": True, "imported": out, "failed": []}


@router.get("/api/evaluate")
async def get_evaluate(month: str | None = None) -> dict:
    """运行确定性规则引擎，返回行动项列表（按优先级排序）。

    可选 ?month=YYYY-MM，默认本月。结果为纯本地计算，不调用 LLM。
    """
    m = (month or "").strip()
    if m and not re.fullmatch(r"(20\d{2}|19\d{2})-(0[1-9]|1[0-2])", m):
        return JSONResponse({"error": "月份需为 YYYY-MM（01–12）"}, status_code=400)
    return await evaluate.evaluate_all(month=m)
