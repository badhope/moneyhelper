"""投资策略路由门面：诊断 / 定投 / FIRE / 沙盒四个子路由按原顺序挂载。

数值一律由 calculations 包确定性计算；本层只做取数与组装。
所有端点都允许在行情不可用时降级（返回 available=false 与原因），
绝不因为外部行情失败返回 500。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

from .strategy_dca import router as _dca_router  # noqa: E402
from .strategy_fire import router as _fire_router  # noqa: E402
from .strategy_risk import router as _risk_router  # noqa: E402 — 子路由需在标准 import 之后
from .strategy_sandbox import router as _sandbox_router  # noqa: E402

for _r in (_risk_router, _dca_router, _fire_router, _sandbox_router):
    router.include_router(_r)
