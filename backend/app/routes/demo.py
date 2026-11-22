"""演示账本路由：进入演示（重建独立租户）与真实/演示计数。

演示模式本身由请求头 `X-Demo-Mode` 切换（见 mw_auth），这里只负责把演示区
重建到已知状态，并返回两边真实计数，供设置页说明“演示没有盖住真实数据”。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from .. import analysis, db

router = APIRouter()


@router.post("/api/demo/enter")
async def enter_demo() -> dict:
    """重建演示租户并返回计数；真实租户不动。"""
    counts = await db.reset_demo_ledger()
    analysis.invalidate_dashboard_cache()
    return {"ok": True, "mode": "demo", "counts": counts}


@router.get("/api/demo/status")
async def demo_status(request: Request) -> dict:
    """真实账本与演示账本各自的计数。

    `request.state.real_tenant_id` 由鉴权中间件在切到演示租户前留下：
    这样即使当前请求正处在演示模式，也能如实报出真实账本有多少数据。
    """
    real_id = int(getattr(request.state, "real_tenant_id", getattr(request.state, "tenant_id", 0)) or 0)
    active = bool(getattr(request.state, "demo_mode", False))
    return {
        "active": active,
        "real": await db.demo_ledger_counts(real_id),
        "demo": await db.demo_ledger_counts(db.DEMO_USER_ID),
    }
