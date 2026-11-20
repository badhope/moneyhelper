"""企业组织 API 门面：租户/部门/岗位/成员各成一模块，按原顺序 include。

边界：读总览对当前租户成员开放；写操作要求目标租户 owner/admin；
所有查询与写入都带 tenant_id，拒绝跨租户引用。
"""

from __future__ import annotations

from fastapi import APIRouter

from .org_departments import router as _departments_router
from .org_members import router as _members_router
from .org_positions import router as _positions_router
from .org_scope import _ints, org_admin_scope, org_read_scope  # noqa: F401 — 对外同名导出
from .org_tenants import router as _tenants_router

router = APIRouter()
router.include_router(_tenants_router)
router.include_router(_departments_router)
router.include_router(_positions_router)
router.include_router(_members_router)
