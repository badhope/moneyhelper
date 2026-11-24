"""自动化工作流执行器：把真实后台任务串成可审计、可补跑的工作流。

只编排既有确定性任务，不在这里重写结账、同步或报税口径。
每一步的返回值原样进入 `automation_runs.steps_json`，失败也留痕，不吞异常。
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta
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

# 只对可安全重放的步骤自动重试：月结本身幂等，快照只读；
# 同步/收件箱可能产生重复导入，失败后只进死信告警，由人工决定是否重放。
STEP_MAX_ATTEMPTS: dict[str, int] = {
    "月度自动结账": 3,
    "关账状态快照": 2,
}
RETRY_BASE_SECONDS = 0.5


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
        max_attempts = max(1, int(STEP_MAX_ATTEMPTS.get(name, 1)))
        attempts = 0
        last_error = ""
        last_result: Any = None
        step_started = time.perf_counter()
        while attempts < max_attempts:
            attempts += 1
            try:
                last_result = await fn()
                failed, last_error = _step_failed(last_result)
            except Exception as exc:  # noqa: BLE001 — 单步失败也要留痕并继续收尾
                failed, last_error = True, str(exc)[:300]
                last_result = None
            if not failed:
                break
            if attempts < max_attempts:
                # 指数退避：0.5s、1s；只对幂等步骤生效。
                await asyncio.sleep(RETRY_BASE_SECONDS * (2 ** (attempts - 1)))
        steps.append(
            {
                "name": name,
                "ok": not failed,
                "attempts": attempts,
                "duration_ms": round((time.perf_counter() - step_started) * 1000),
                "result": last_result,
                "error": "" if not failed else last_error[:300],
            }
        )
        if failed:
            errors.append(f"{name}: {last_error}")

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
    if status in {"failed", "partial"}:
        await automation_db.create_alert(
            run["id"],
            key,
            severity="error" if status == "failed" else "warning",
            message="; ".join(errors)[:300] or f"{item['name']}未完成",
        )
    await automation_db.prune_runs()
    return finished or {
        **run,
        "status": status,
        "steps": steps,
        "duration_ms": duration_ms,
    }


async def replay_run(run_id: str) -> dict[str, Any]:
    """人工重放一次失败/部分失败的运行；每次重放生成新 run，不覆盖原证据。"""
    run = await automation_db.get_run(run_id)
    if run is None:
        raise ValueError("运行记录不存在")
    if run.get("status") == "running":
        raise ValueError("运行仍在进行，不能重放")
    if str(run.get("status")) not in {"failed", "partial"}:
        raise ValueError("只有失败或部分失败的运行可以重放")
    token = int(time.time() * 1000)
    return await run_workflow(
        str(run["workflow"]),
        trigger="replay",
        idempotency_key=f"replay:{run_id}:{token}",
    )


async def recover_missed_month_end(
    today: date | None = None,
    *,
    hour: int | None = None,
) -> dict[str, Any]:
    """启动补偿：只在“上月期间存在且未关账、本月尚无成功定时运行”时补跑月结。

    - 每小时同步/十分钟收件箱不补跑，避免停机后一次性爆发重复导入；
    - 月结幂等（已关账直接 skipped），因此可以安全补跑；
    - 同一天用日期做幂等键，进程反复重启不会制造多条运行。
    """
    local = datetime.now().astimezone()
    today = today or local.date()
    current_hour = local.hour if hour is None else hour
    if today.day == 1 and current_hour < 2:
        return {"status": "before_window"}

    prev_end = today.replace(day=1) - timedelta(days=1)
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
        return {"status": "skipped", "reason": "no_period"}
    if str(target.get("status")) == "closed":
        return {"status": "skipped", "reason": "already_closed"}

    month_start = today.replace(day=1).isoformat()
    last = await automation_db.latest_scheduled_run("enterprise_month_end", month_start)
    if last is not None and str(last.get("status")) in {"done", "partial"}:
        return {"status": "skipped", "reason": "already_ran", "run_id": last.get("id")}
    return await run_workflow(
        "enterprise_month_end",
        trigger="catchup",
        idempotency_key=f"catchup:month-end:{today.isoformat()}",
    )


async def run_scheduled_month_end() -> dict[str, Any]:
    """APScheduler 入口：月结走同一条可审计工作流，不另写一套逻辑。"""
    return await run_workflow("enterprise_month_end", trigger="schedule")
