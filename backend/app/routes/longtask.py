"""长任务 API（切片 10）：创建、执行、进度、产物下载。

权限：
- 读写：目标租户有效成员（长任务会调用模型产生成本，写入口需要实例管理员）；
- 本机/共享口令按 local 放行。

任务产物落在 data/longtasks/<id>/artifacts/，由 pathguard 保证不越出数据目录。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .. import auth, longtask
from ._scope import tenant_permission_scope

router = APIRouter()


def _bad(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


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
    return {"tasks": longtask.list_tasks()}


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
            stages=[str(s) for s in stages] if isinstance(stages, list) else None,
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "task": task}


@router.get("/api/longtasks/{task_id}")
async def get_task(task_id: str, scope: int = Depends(_read_scope)) -> Any:
    try:
        return longtask.get_task(task_id)
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
    try:
        limit = int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return _bad("max_stages 需为整数")
    try:
        task = await longtask.run_task(task_id, max_stages=limit)
    except (ValueError, PermissionError) as exc:
        return _bad(str(exc))
    return {"ok": True, "task": task}


@router.post("/api/longtasks/{task_id}/cancel")
async def cancel_task(task_id: str, scope: int = Depends(_write_scope)) -> Any:
    try:
        task = longtask.cancel_task(task_id)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "task": task}


@router.get("/api/longtasks/{task_id}/stages/{index}")
async def read_stage(task_id: str, index: int, scope: int = Depends(_read_scope)) -> Any:
    try:
        content = longtask.read_artifact(task_id, index)
    except ValueError as exc:
        return _bad(str(exc), 404)
    return {"task_id": task_id, "index": index, "content": content}
