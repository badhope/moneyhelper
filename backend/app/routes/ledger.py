"""数据录入域路由门面：仪表盘 / 持仓 / 流水 / 一句话记账 / CSV 入账 / 撤回 / 体检。

实现按域拆到 ledger_positions / ledger_transactions / ledger_imports / ledger_undo；
本模块注册仪表盘、财务体检与持仓重置，并按原文件顺序 include 子路由
（`/api/{entity:path}/batch-undo` 这类通配路径的匹配顺序因此不变）。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import analysis, auth, db, quotes
from ..quotes import invalidate_quotes_cache
from .ledger_imports import router as imports_router
from .ledger_positions import router as positions_router
from .ledger_transactions import router as transactions_router
from .ledger_undo import router as undo_router

router = APIRouter()


@router.get("/api/dashboard")
async def dashboard(lang: str = "zh") -> dict:
    # lang 仅影响 flags/来源标签等展示文案的语言，不增加任何查询/往返开销
    return await analysis.collect_dashboard(lang=lang or "zh")


router.include_router(positions_router)
router.include_router(transactions_router)
router.include_router(imports_router)
router.include_router(undo_router)


@router.get("/api/health-check")
async def health_check(lang: str = "zh") -> dict:
    lang = lang.strip() or "zh"
    positions = await db.list_positions()
    # 空库保护与图内一致：没有任何持仓/流水时不给「分数体检」假象
    if not positions and not await db.fetch_all("SELECT 1 FROM transactions LIMIT 1"):
        return analysis.health_check(None, None, [], await db.list_goals(), lang=lang)
    live = await quotes.live_quotes(positions)
    settings = await db.get_settings()
    m = analysis.market_view(positions, live)
    led = analysis.ledger_view(
        await db.list_transactions(),
        await db.list_subscriptions(),
        await db.list_debts(),
        settings,
        positions,
        live,
    )
    flags = analysis.risk_checks(m, led)
    return analysis.health_check(m, led, flags, await db.list_goals(), lang=lang)


@router.post("/api/portfolio/reset")
async def reset_portfolio(request: Request) -> dict:
    """恢复示例数据（**只影响当前租户的账本**）。

    鉴权要求（专家评审 P0-5）：这是清空账本的操作。
    - 启用多用户（已有注册用户）时：必须登录，且只清自己的数据；
    - 单机模式（没有任何用户）时：允许，仍只清默认租户 0。
    此前无任何校验，任何能访问端口的人都能抹掉全部数据。
    """
    if await db.user_count() > 0:
        user = await auth.get_current_user(request)
        if not user:
            return JSONResponse({"error": "需要登录"}, status_code=401)
    out = await db.reset_to_seed()
    await invalidate_quotes_cache()
    analysis.invalidate_dashboard_cache()
    return out
