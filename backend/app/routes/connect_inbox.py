"""账单收件箱：扫描自动入账与收件状态查看。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..connect import service

router = APIRouter(dependencies=[Depends(get_current_user)])

# ---------------------------------------------------------------------------
# 收件箱
# ---------------------------------------------------------------------------


@router.post("/api/connect/inbox/scan")
async def inbox_scan() -> dict[str, Any]:
    """扫描账单收件目录并自动入账（用户只需把官方导出的 CSV 放进去）。"""
    return await service.scan_import_inbox()


@router.get("/api/connect/inbox")
async def inbox_info() -> dict[str, Any]:
    root = service.inbox_dir()
    files = [
        {"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime}
        for p in sorted(root.iterdir())
        if p.is_file()
    ]
    done = root / "done"
    done_files = sorted([p.name for p in done.iterdir() if p.is_file()])[-20:] if done.exists() else []
    return {"path": str(root), "pending": files, "done": done_files}


# ---------------------------------------------------------------------------
