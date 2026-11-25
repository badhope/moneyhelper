"""AI 托管台 API（4.26.0）。

只暴露“策略 + 评估 + 执行”三层：
- 策略是用户预先给的边界，服务端按策略决定能不能直接做；
- 评估总是先出计划与阻断原因；
- 执行复用既有 external_delivery / automation_runner，不另写发送逻辑。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import autopilot
from ..auth import get_current_user
from .gl import gl_read_scope, gl_write_scope

router = APIRouter(dependencies=[Depends(get_current_user)])


class PolicyIn(BaseModel):
    mode: str = "manual"
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class RunIn(BaseModel):
    confirm: bool = False
    dry_run: bool = False
    period: str = ""


@router.get("/api/autopilot/overview")
async def autopilot_overview(_: int = Depends(gl_read_scope)):
    return await autopilot.overview()


@router.get("/api/autopilot/policies")
async def autopilot_policies(_: int = Depends(gl_read_scope)):
    return {"items": await autopilot.list_policies()}


@router.put("/api/autopilot/policies/{action_key}")
async def autopilot_save_policy(
    action_key: str,
    body: PolicyIn,
    _: int = Depends(gl_write_scope),
):
    try:
        item = await autopilot.save_policy(
            action_key, mode=body.mode, enabled=body.enabled, config=body.config
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.post("/api/autopilot/actions/{action_key}/run")
async def autopilot_run_action(
    action_key: str,
    body: RunIn,
    _: int = Depends(gl_write_scope),
):
    try:
        return await autopilot.run_action(
            action_key,
            confirm=body.confirm,
            period=body.period,
            dry_run=body.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/autopilot/run-all")
async def autopilot_run_all(body: RunIn, _: int = Depends(gl_write_scope)):
    try:
        return await autopilot.run_all(
            confirm=body.confirm, period=body.period, dry_run=body.dry_run
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/autopilot/decisions")
async def autopilot_decisions(limit: int = 30, _: int = Depends(gl_read_scope)):
    from .. import db

    return {"items": await db.autopilot_list_decisions(limit)}
