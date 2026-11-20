"""财务部门模式：实况事件流与呈批件查询/审批。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import db
from ..logging_utils import get_logger as _get_logger
from .qa_sse import sse_stream

log = _get_logger(__name__)

router = APIRouter()

@router.post("/api/department/stream")
async def department_stream(payload: dict):
    """部门模式实况事件流：工单状态变更实时推送（供前端工位图）。

    与 /api/department/run 的区别：
    - run    返回一次性 JSON（含完整呈批件与全部事件）
    - stream 边执行边推送事件，前端能看到"哪个部门正在跑"

    事件序列：
      dept_start  → 派工完成，带工单清单
      dept        → 某工单状态变更（running/done/failed），带 metrics
      dept_final  → 秘书汇总完成，带结论与冲突
    """
    from .. import department

    question = str((payload or {}).get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "question 必填"}, status_code=400)
    if len(question) > 2000:
        return JSONResponse({"error": "问题过长（最多 2000 字）"}, status_code=400)
    lang = str((payload or {}).get("lang") or "zh").strip() or "zh"

    async def runner(emit) -> None:
        report = await department.run_department_mode(question, emit, lang=lang)
        # 落库后才能跨请求审批（老板离开页面再回来仍可批）
        try:
            report_id = await db.dept_report_save(question, report)
            # 必须带上 status：前端据此决定是否显示审批按钮（pending 才有）。
            # 新落库的记录状态一定是 pending，与 db 层默认值一致。
            report = {**report, "report_id": report_id, "status": "pending"}
        except Exception:  # noqa: BLE001 — 落库失败不阻断交付，但如实标注
            log.exception("dept_report save failed")
            report = {**report, "report_id": ""}
        # 最终呈批件单独发一条，前端不必从 dept_final 事件里拼
        await emit({"type": "dept_report", "report": report})

    return await sse_stream(None, runner)

@router.get("/api/department/reports")
async def dept_reports(status: str | None = None, limit: int = 20) -> dict:
    """列出呈批件（最新在前）。status=pending 只看待批的。"""
    return {"reports": await db.dept_report_list(status, limit)}

@router.get("/api/department/reports/{report_id}")
async def dept_report_detail(report_id: str) -> Any:
    report = await db.dept_report_get(report_id)
    if report is None:
        return JSONResponse({"error": "呈批件不存在"}, status_code=404)
    return report

@router.post("/api/department/reports/{report_id}/decide")
async def dept_report_decide(report_id: str, payload: dict) -> Any:
    """审批呈批件：approve（批准）/ reject（驳回，可附理由）/ inquire（追问）。

    - approve：结论被采纳，审计链记账
    - reject ：附理由驳回；理由会写进审计与呈批件
    - inquire：把追问内容作为新问题重新跑一轮部门模式，产生**新**呈批件
      （原呈批件保留为历史，审批链不被覆盖）

    并发安全：条件 UPDATE 保证同一份呈批件只能被审批一次，第二个请求返回 409。
    """
    from .. import department, provenance

    decision = str((payload or {}).get("decision") or "").strip()
    note = str((payload or {}).get("note") or "").strip()
    if decision not in db.DEPT_DECISIONS:
        return JSONResponse(
            {"error": f"decision 必须是 {'/'.join(db.DEPT_DECISIONS)} 之一"},
            status_code=400,
        )
    if decision in ("reject", "inquire") and not note:
        return JSONResponse(
            {"error": "驳回与追问都必须说明理由"}, status_code=400
        )

    report = await db.dept_report_get(report_id)
    if report is None:
        return JSONResponse({"error": "呈批件不存在"}, status_code=404)

    updated = await db.dept_report_decide(report_id, decision, note)
    if updated is None:
        return JSONResponse(
            {"error": "该呈批件已被处理", "status": report["status"]},
            status_code=409,
        )

    # 审计链：老板的决策与数字产出在同一条链上（"可复核"的一部分）
    try:
        await provenance.record_provenance(
            action=f"dept_report_{decision}",
            entity_type="dept_report",
            entity_id=report_id,
            before={"status": report["status"]},
            after={"status": updated["status"], "note": note},
            source="api",
        )
    except Exception:  # noqa: BLE001 — 审计失败不影响审批结果
        log.warning("dept_report audit failed: %s", report_id)

    out: dict[str, Any] = {"ok": True, "report": updated}
    if decision == "inquire":
        # 追问 = 带上追问内容重跑一轮，产出新呈批件
        followup_q = f"{report['question']}\n\n（老板追问：{note}）"
        new_report = await department.run_department_mode(followup_q)
        new_id = await db.dept_report_save(followup_q, new_report)
        out["followup_report_id"] = new_id
        # 同样补 status：前端切到追问产生的新件时要能继续审批
        out["followup_report"] = {**new_report, "report_id": new_id, "status": "pending"}
    return out
