"""Studio 路由门面：资产 CRUD / 导入 / AI 生成 / 市场 / 权限 / 诊断 / 模板。

按域拆在 `studio_common.py`（标签/审计/权限）、`studio_read.py`（只读）、
`studio_import.py`（导入）、`studio_generate.py`（AI 生成），此处只装配三条子路由。
约定：写操作在「非全面放开」模式返回 403；核心安全项即使放开也拒绝。
"""

from __future__ import annotations

from fastapi import APIRouter

from .studio_common import (  # noqa: F401 — 旧引用（其他子路由仍从门面取）
    KIND_LABELS,
    _audit,
    _check_kind,
    _require_admin,
)
from .studio_generate import router as generate_router
from .studio_import import router as import_router
from .studio_read import router as read_router

router = APIRouter()
router.include_router(read_router)
router.include_router(import_router)
router.include_router(generate_router)


# 子路由按「市场 → 权限 → 设置 → 资产」顺序挂载，且资产放在最后：
# /api/studio/{kind} 会遮蔽同级静态路径，注册顺序不能变。
from .studio_assets import router as assets_router  # noqa: E402
from .studio_market import router as market_router  # noqa: E402
from .studio_permissions import router as perms_router  # noqa: E402
from .studio_settings import router as settings_router  # noqa: E402

router.include_router(market_router)
router.include_router(perms_router)
router.include_router(settings_router)
router.include_router(assets_router)
