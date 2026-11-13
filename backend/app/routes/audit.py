"""审计日志（provenance 之外的 audit_log 表）：查询与清空。

从 routes/system.py 拆出（M1.4 收尾）：原文件把 9 个互不相关的域塞在一起，
任何一个域的改动都要在 500+ 行里定位。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException

from .. import auth, db

router = APIRouter()


# ---------------------------------------------------------------------------
# 审计日志（P2 金融级治理）
# ---------------------------------------------------------------------------


@router.get("/api/audit")
async def audit_logs(limit: int = 200, action: str | None = None) -> dict:
    return {"audit": await db.list_audit_logs(limit, action)}


@router.get("/api/audit/verify")
async def verify_audit(
    _admin: dict = Depends(auth.require_instance_admin),
) -> dict:
    """校验当前租户审计哈希链（实例管理员）。"""
    return await db.verify_audit_chain()


@router.post("/api/audit/clear")
async def clear_audit_logs(
    _admin: dict = Depends(auth.require_instance_admin),
) -> dict:
    # 审计默认只追加。物理清空是开发/测试逃生口，必须显式开启；
    # 企业部署应改为归档/保留策略，而不是删除证据。
    allowed = os.getenv("MONEYHELPER_ALLOW_AUDIT_CLEAR", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                "审计日志默认不可清空（只追加）。"
                "开发环境如需清空，请显式设置 MONEYHELPER_ALLOW_AUDIT_CLEAR=1。"
            ),
        )
    return await db.clear_audit_logs()
