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
from ..calculations.report_from_gl import statements_from_trial_balance
from ..db.tenant import current_tenant_id

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


@router.post("/api/statements/from-gl")
async def statements_from_ledger(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """零输入出报表：按总账已过账凭证还原三表并分析，返回 {payload, analysis}。

    产品定位：用户不该为了看财报而手抄一份资产负债表。凭证本来就是系统按
    报销 / 采购 / 银行流水自动生成的，这里只是把它们按科目汇总成报表口径。

    - 不传 `period_id` 时取**最新一期**；总账里没有任何期间时返回 409，
      提示"先在总账里过账"，而不是返回一份全 0 的假报表。
    - 返回的 `payload` 可直接再 POST 到 `/api/statements` 存档，前端用它做预览。
    """
    body = payload or {}
    tenant = current_tenant_id()
    periods = await db.gl_list_periods(tenant)
    setup = None
    if not periods and body.get("auto_setup", True):
        # 连账套都还没有：先替他把科目表与当期期间铺好，再判断有没有数据。
        # 这是"零操作"的最后一步——用户不该被要求"先去总账建科目"。
        setup = await db.gl_bootstrap(tenant)
        periods = await db.gl_list_periods(tenant)
    if body.get("period_id"):
        period = next((p for p in periods if int(p["id"]) == int(body["period_id"])), None)
        if period is None:
            raise HTTPException(status_code=404, detail="会计期间不存在")
    elif periods:
        period = periods[0]
    else:
        raise HTTPException(
            status_code=409,
            detail=(
                f"已自动建好账套（{setup['accounts_created']} 个科目、"
                f"{setup['period']['year']}年{setup['period']['month']}月期间），"
                "但本月还没有任何凭证：导入银行流水或记一笔就能出报表"
                if setup
                else "总账还没有任何会计期间（可加 auto_setup=true 由系统自动建账）"
            ),
        )

    setup_note = (
        f"系统已自动建好账套（{setup['accounts_created']} 个科目、"
        f"{period['year']}年{period['month']}月期间）· "
        if setup
        else ""
    )

    posted_now = 0
    if int(period.get("posted_entries") or 0) == 0:
        # 草稿是系统按报销/采购/银行流水自动生成的，用户不该被要求"先自己去过账"。
        # 传 auto_post=true 时这里直接替他过账（幂等：重复调用时已过账的不会再动）。
        if not body.get("auto_post"):
            drafts = int(period.get("draft_entries") or 0)
            raise HTTPException(
                status_code=409,
                detail=(
                    setup_note
                    + (
                        f"{period['year']}年{period['month']}月有 {drafts} 张草稿凭证还没过账，"
                        "无法出报表（可加 auto_post=true 由系统自动过账）"
                        if drafts
                        else f"{period['year']}年{period['month']}月还没有任何凭证："
                        "导入银行流水或记一笔就能出报表"
                    )
                ),
            )
        for e in await db.gl_list_entries(tenant, int(period["id"]), 500):
            if str(e.get("status")) == "draft":
                await db.gl_post_entry(tenant, int(e["id"]))
                posted_now += 1

    tb = await db.gl_trial_balance(tenant, int(period["id"]))
    label = f"{period['year']}-{int(period['month']):02d}"
    payload_out = statements_from_trial_balance(
        tb.get("items") or [],
        company=str(body.get("company") or "本企业"),
        currency=str(body.get("currency") or "CNY"),
        period=label,
    )
    analysis = analyze_statements(payload_out)
    return {
        "period": tb.get("period"),
        "payload": payload_out,
        "analysis": analysis,
        "auto_posted": posted_now,
        "auto_setup": (
            {"accounts_created": setup["accounts_created"]} if setup else None
        ),
    }


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
