"""长任务 API（切片 10）：创建、执行、进度、产物下载。

权限：
- 读写：目标租户有效成员（长任务会调用模型产生成本，写入口需要实例管理员）；
- 本机/共享口令按 local 放行。

任务产物落在 data/longtasks/<id>/artifacts/，由 pathguard 保证不越出数据目录。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import auth, longtask
from ._responses import bad as _bad
from ._scope import tenant_permission_scope

router = APIRouter()


def _decorate_task(task: dict[str, Any]) -> dict[str, Any]:
    """给任务补真实 active 与过期计数，并把无后台协程的 running 归一为 pending。

    进程重启后磁盘可能残留 running；如果 API 原样返回，界面会一直显示
    “执行中”并无限轮询，而实际没有任何协程在跑。
    """
    active = longtask.is_active(str(task.get("id") or ""))
    if task.get("status") == "running" and not active:
        task["status"] = "pending"
    task["active"] = active
    task["stale_count"] = sum(1 for s in task.get("stages") or [] if s.get("stale"))
    return task




async def _read_scope(
    tenant_id: int | None = None,
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    return await tenant_permission_scope(tenant_id, user, "gl:read")


async def _write_scope(
    tenant_id: int | None = None,
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    # 长任务消耗模型额度且会写文件：复用"实例管理员 + 租户成员"双重边界。
    await auth.require_instance_admin(user)
    return await tenant_permission_scope(tenant_id, user, "gl:write")


@router.get("/api/longtasks/templates")
async def list_templates() -> dict[str, Any]:
    return {"templates": longtask.list_templates()}


@router.get("/api/longtasks")
async def list_tasks(scope: int = Depends(_read_scope)) -> dict[str, Any]:
    return {"tasks": [_decorate_task(t) for t in longtask.list_tasks()]}


@router.post("/api/longtasks")
async def create_task(
    payload: dict[str, Any], scope: int = Depends(_write_scope)
) -> Any:
    data = payload or {}
    stages = data.get("stages")
    try:
        task = await longtask.create_task(
            str(data.get("kind") or "program"),
            str(data.get("title") or ""),
            str(data.get("brief") or ""),
            stages=stages if isinstance(stages, list) else None,
            success_criteria=str(data.get("success_criteria") or ""),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "task": task}


@router.get("/api/longtasks/{task_id}")
async def get_task(task_id: str, scope: int = Depends(_read_scope)) -> Any:
    try:
        return _decorate_task(longtask.get_task(task_id))
    except ValueError as exc:
        return _bad(str(exc), 404)


@router.post("/api/longtasks/{task_id}/run")
async def run_task(
    task_id: str,
    payload: dict[str, Any] | None = None,
    scope: int = Depends(_write_scope),
) -> Any:
    data = payload or {}
    raw = data.get("max_stages")
    raw_index = data.get("stage_index")
    cascade = bool(data.get("cascade"))
    stale_only = bool(data.get("stale_only"))
    try:
        limit = int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return _bad("max_stages 需为整数")
    try:
        index = int(raw_index) if raw_index not in (None, "") else None
    except (TypeError, ValueError):
        return _bad("stage_index 需为整数")
    if limit is not None and index is not None:
        return _bad("max_stages 与 stage_index 只能二选一")
    if cascade and index is None:
        return _bad("cascade 需要 stage_index")
    if stale_only and (limit is not None or index is not None or cascade):
        return _bad("stale_only 不能与 max_stages/stage_index/cascade 同用")
    try:
        if data.get("background"):
            # 长任务可能跑到一小时，不能用一次 HTTP 请求一直挂着；
            # 返回 pending 快照，前端轮询 /api/longtasks/{id}。
            task = await longtask.start_task(
                task_id,
                max_stages=limit,
                stage_index=index,
                cascade=cascade,
                stale_only=stale_only,
            )
        else:
            task = await longtask.run_task(
                task_id,
                max_stages=limit,
                stage_index=index,
                cascade=cascade,
                stale_only=stale_only,
            )
    except (ValueError, PermissionError) as exc:
        return _bad(str(exc))
    return {"ok": True, "task": _decorate_task(task)}


@router.post("/api/longtasks/{task_id}/cancel")
async def cancel_task(task_id: str, scope: int = Depends(_write_scope)) -> Any:
    try:
        task = longtask.cancel_task(task_id)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "task": _decorate_task(task)}


@router.get("/api/longtasks/{task_id}/stages/{index}/checkpoints")
async def list_checkpoints(
    task_id: str, index: int, scope: int = Depends(_read_scope)
) -> Any:
    try:
        # 先确认任务与阶段存在，避免检查点目录按任意 index 建出来。
        longtask.read_artifact(task_id, index)
        rows = longtask.list_checkpoints(task_id, index)
    except ValueError as exc:
        return _bad(str(exc), 404)
    return {"checkpoints": rows}


@router.post("/api/longtasks/{task_id}/rollback")
async def rollback(
    task_id: str, payload: dict[str, Any], scope: int = Depends(_write_scope)
) -> Any:
    data = payload or {}
    raw_index = data.get("stage_index")
    try:
        index = int(raw_index)
    except (TypeError, ValueError):
        return _bad("stage_index 需为整数")
    checkpoint_id = str(data.get("checkpoint_id") or "").strip()
    if not checkpoint_id:
        return _bad("checkpoint_id 不能为空")
    try:
        task = longtask.rollback_task(task_id, index, checkpoint_id)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "task": _decorate_task(task)}


@router.get("/api/longtasks/{task_id}/stages/{index}")
async def read_stage(task_id: str, index: int, scope: int = Depends(_read_scope)) -> Any:
    try:
        content = longtask.read_artifact(task_id, index)
    except ValueError as exc:
        return _bad(str(exc), 404)
    return {"task_id": task_id, "index": index, "content": content}
