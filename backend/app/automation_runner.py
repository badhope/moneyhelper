"""自动化工作流执行器：把真实后台任务串成可审计、可补跑的工作流。

只编排既有确定性任务，不在这里重写结账、同步或报税口径。
每一步的返回值原样进入 `automation_runs.steps_json`，失败也留痕，不吞异常。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any

from . import db
from .db import automation as automation_db
from .db.tenant import current_tenant_id
from .scheduler_background import (
    _month_end_close,
    _scan_connect_inbox,
    _sync_connect_sources,
)
from .scheduler_subs import _check_subscriptions_due


async def _month_end_snapshot() -> dict[str, Any]:
    """读取上月结账后的真实状态，不做任何写操作。"""
    today = datetime.now().astimezone().date()
    prev_end = today.replace(day=1) - timedelta(days=1)
    month = f"{prev_end.year}-{prev_end.month:02d}"
    tenant = current_tenant_id()
    periods = await db.gl_list_periods(tenant)
    target = next(
        (
            p
            for p in periods
            if int(p["year"]) == prev_end.year and int(p["month"]) == prev_end.month
        ),
        None,
    )
    if target is None:
        return {"month": month, "period": "missing", "entries": 0, "drafts": 0}
    entries = await db.gl_list_entries(tenant, int(target["id"]), limit=500)
    return {
        "month": month,
        "period": str(target.get("status")),
        "entries": len(entries),
        "drafts": sum(1 for e in entries if str(e.get("status")) == "draft"),
    }


WORKFLOWS: dict[str, dict[str, Any]] = {
    "personal_daily": {
        "name": "个人日常自动化",
        "scope": "personal",
        "description": "订阅到期提醒、公开数据源同步、账单收件箱扫描；只读/导入，不自动交易。",
        "steps": [
            ("订阅到期巡检", _check_subscriptions_due),
            ("连接源自动同步", _sync_connect_sources),
            ("账单收件箱扫描", _scan_connect_inbox),
        ],
    },
    "enterprise_month_end": {
        "name": "企业月度结账",
        "scope": "enterprise",
        "description": "草稿凭证先过账再关账，随后读取关账后的期间状态与凭证数。",
        "steps": [
            ("月度自动结账", _month_end_close),
            ("关账状态快照", _month_end_snapshot),
        ],
    },
}


def list_workflows() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "name": item["name"],
            "scope": item["scope"],
            "description": item["description"],
            "steps": [name for name, _ in item["steps"]],
        }
        for key, item in WORKFLOWS.items()
    ]


_LOCKS: dict[str, asyncio.Lock] = {}


def _step_failed(result: Any) -> tuple[bool, str]:
    if isinstance(result, dict):
        if result.get("status") == "failed":
            return True, str(
                result.get("error") or result.get("reason") or "步骤返回失败"
            )
        if result.get("error"):
            return True, str(result["error"])
    return False, ""


async def run_workflow(
    key: str,
    *,
    trigger: str = "manual",
    idempotency_key: str = "",
) -> dict[str, Any]:
    """执行一条工作流并落审计台账；同一工作流串行，未知 key 抛 ValueError。"""
    if key not in WORKFLOWS:
        raise ValueError(f"未知工作流：{key}")
    async with _LOCKS.setdefault(key, asyncio.Lock()):
        return await _run_workflow(
            key, trigger=trigger, idempotency_key=idempotency_key
        )


async def _run_workflow(
    key: str,
    *,
    trigger: str,
    idempotency_key: str,
) -> dict[str, Any]:
    item = WORKFLOWS[key]
    run = await automation_db.start_run(
        key,
        item["name"],
        trigger=trigger,
        idempotency_key=idempotency_key,
    )
    if run.get("status") != "running":
        return {**run, "deduplicated": True}

    t0 = time.perf_counter()
    steps: list[dict[str, Any]] = []
    errors: list[str] = []
    for name, fn in item["steps"]:
        s0 = time.perf_counter()
        try:
            result = await fn()
            failed, reason = _step_failed(result)
            steps.append(
                {
                    "name": name,
                    "ok": not failed,
                    "duration_ms": round((time.perf_counter() - s0) * 1000),
                    "result": result,
                    "error": reason,
                }
            )
            if failed:
                errors.append(f"{name}: {reason}")
        except Exception as exc:  # noqa: BLE001 — 单步失败也要留痕并继续收尾
            steps.append(
                {
                    "name": name,
                    "ok": False,
                    "duration_ms": round((time.perf_counter() - s0) * 1000),
                    "result": None,
                    "error": str(exc)[:300],
                }
            )
            errors.append(f"{name}: {exc}")

    status = (
        "done"
        if not errors
        else ("partial" if any(s["ok"] for s in steps) else "failed")
    )
    duration_ms = round((time.perf_counter() - t0) * 1000)
    finished = await automation_db.finish_run(
        run["id"],
        status=status,
        duration_ms=duration_ms,
        steps=steps,
        error="; ".join(errors)[:500],
    )
    await automation_db.prune_runs()
    return finished or {
        **run,
        "status": status,
        "steps": steps,
        "duration_ms": duration_ms,
    }


async def run_scheduled_month_end() -> dict[str, Any]:
    """APScheduler 入口：月结走同一条可审计工作流，不另写一套逻辑。"""
    return await run_workflow("enterprise_month_end", trigger="schedule")
