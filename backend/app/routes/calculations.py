"""金融计算引擎路由门面：净值 / 收益率 / 健康评分与目标进度 / 净值历史。

所有数值计算由 calculations 包完成（纯确定性），本层只负责 I/O 拉取与结果包装。
子模块各挂自己的 router，按原文件顺序 include，路径匹配关系不变。
"""

from __future__ import annotations

from fastapi import APIRouter

from .calculations_health import router as _health_router
from .calculations_networth import router as _networth_router
from .calculations_networth_past import router as _past_router
from .calculations_returns import router as _returns_router

router = APIRouter()
router.include_router(_networth_router)
router.include_router(_returns_router)
router.include_router(_health_router)
router.include_router(_past_router)
