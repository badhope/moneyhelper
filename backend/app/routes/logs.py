"""运行日志查看与清空。

从 routes/system.py 拆出（M1.4 收尾）：原文件把 9 个互不相关的域塞在一起，
任何一个域的改动都要在 500+ 行里定位。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import auth
from ..logging_utils import clear_logs, read_log_lines
from ..logging_utils import get_logger as _get_logger

log = _get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# 日志查看接口
# ---------------------------------------------------------------------------


@router.get("/api/logs")
async def get_logs(
    limit: int = 200, user: dict = Depends(auth.require_instance_admin)
) -> dict:
    """返回日志文件最近 limit 行（仅实例管理员）。

    日志是进程级全局文件，包含所有租户的工具参数、用户问题片段与 LLM 错误。
    此前任何登录用户都能读——等于任意租户可窥探他人操作；也更不能让
    任意用户清空全实例日志（破坏审计证据）。

    用 require_instance_admin 而非 admin_only：本机单用户模式没有 JWT，
    admin_only 会 401，导致设置页「日志」一打开就弹口令框（实测缺陷）。
    """
    lines = read_log_lines(min(max(1, limit), 1000))
    return {"lines": lines, "total": len(lines)}


@router.post("/api/logs/clear")
async def clear_logs_endpoint(
    user: dict = Depends(auth.require_instance_admin),
) -> dict:
    """清空日志文件（仅实例管理员），返回清空前行数。"""
    cleared = clear_logs()
    log.info("logs cleared by admin %s (%d lines removed)", user.get("username"), cleared)
    return {"ok": True, "cleared_lines": cleared}
