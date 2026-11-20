"""晨报 / 调度器状态 / 定时产出收件箱。

从 routes/system.py 拆出（M1.4 收尾）：原文件把 9 个互不相关的域塞在一起，
任何一个域的改动都要在 500+ 行里定位。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import db, scheduler
from ..logging_utils import get_logger

log = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# 晨报 / 调度器 / 定时产出收件箱
# ---------------------------------------------------------------------------


@router.get("/api/reports")
async def reports(limit: int = 20) -> dict:
    return {"reports": await db.list_runs("cron", limit)}


@router.post("/api/reports/generate")
async def generate_report_now() -> dict:
    try:
        result = await scheduler.generate_report()
    except Exception as exc:  # noqa: BLE001 — 手动触发失败要给可读错误
        # 手动触发失败此前只回一句 error，服务端没有任何日志，排查只能靠猜
        log.exception("reports.generate_failed: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    if result.get("skipped"):
        # 空库不生成（前端据此提示「还没有数据」而非假装成功）
        return {"ok": True, "skipped": True, "reason": result.get("reason", "no_data")}
    return {"ok": True, "answer": result["answer"], "level": result["level"]}


@router.get("/api/scheduler")
async def scheduler_status() -> dict:
    return scheduler.status()


@router.get("/api/scheduled-outputs")
async def scheduled_outputs(limit: int = 30) -> dict:
    """定时产出统一收件箱：晨报 + 技能触发合并时间线（最新在前）。

    每项带 kind（report/skill）与 skill_id/skill_name（技能产出时解析）；
    与「问AI」会话列表隔离（这些线程不建会话行），此处是它们的统一可见入口。
    """
    from .. import agent_config

    runs = await db.list_scheduled_runs(limit)
    cfg = await agent_config.get_config()
    skills = cfg.get("skills") or {}
    items: list[dict] = []
    for r in runs:
        tid = str(r.get("thread_id") or "")
        if tid == "cron":
            items.append({**r, "kind": "report", "skill_id": None, "skill_name": None})
        else:
            sid = tid.split(":", 1)[1] if ":" in tid else tid
            skill = skills.get(sid) or {}
            items.append(
                {
                    **r,
                    "kind": "skill",
                    "skill_id": sid,
                    "skill_name": str(skill.get("name") or sid),
                }
            )
    return {"outputs": items}
