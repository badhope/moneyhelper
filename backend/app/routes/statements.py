"""财报分析路由（v4.0 财务工作台）：三表分析 / 保存 / 列表 / 详情 / 删除。

输入为标准化的三表 JSON（见 calculations/financial_statements.py 口径）。
分析结果由确定性引擎产出；report_text 为模板化中文报告，模型存在时可在对话层润色。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..auth import get_current_user
from ..calculations import analyze_statements

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/api/statements/analyze")
async def statements_analyze(payload: dict[str, Any]) -> dict[str, Any]:
    """只分析不落库：body 为标准化三表 JSON。返回分析报告（含预警与文本）。"""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")
    result = analyze_statements(payload)
    if result is None:
        raise HTTPException(
            status_code=400,
            detail="invalid statement payload: expected {company, periods:[{period, balance_sheet, income_statement, cashflow_statement}]}",
        )
    return result


@router.post("/api/statements")
async def statements_save(payload: dict[str, Any]) -> dict[str, Any]:
    """分析并落库：返回 {id, company, report_text 摘要}。"""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")
    result = analyze_statements(payload)
    if result is None:
        raise HTTPException(status_code=400, detail="invalid statement payload")
    record = await db.statements.save_statement(
        company=result["company"],
        payload=payload,
        report=result["report_text"],
        currency=result["currency"],
    )
    return {
        "id": record["id"],
        "company": result["company"],
        "currency": result["currency"],
        "period_count": result["period_count"],
        "alert_count": len(result["alerts"]),
        "report_text": result["report_text"],
        "created_at": record["created_at"],
    }


@router.get("/api/statements")
async def statements_list() -> dict[str, Any]:
    """财报记录列表（不含 payload）。"""
    items = await db.statements.list_statements()
    return {"items": items, "total": len(items)}


@router.get("/api/statements/{sid}")
async def statements_get(sid: str) -> dict[str, Any]:
    """单条详情（含 payload，前端可重新分析或下载原始数据）。"""
    row = await db.statements.get_statement(sid)
    if not row:
        raise HTTPException(status_code=404, detail="statement not found")
    result = analyze_statements(row["payload"])
    if result is None:
        raise HTTPException(status_code=500, detail="stored payload no longer analyzable")
    result["created_at"] = row.get("created_at")
    result["id"] = sid
    return result


@router.delete("/api/statements/{sid}")
async def statements_delete(sid: str) -> dict[str, Any]:
    """删除单条财报记录。"""
    ok = await db.statements.delete_statement(sid)
    if not ok:
        raise HTTPException(status_code=404, detail="statement not found")
    return {"deleted": sid}
