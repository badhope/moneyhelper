"""企业组织影子模型（切片 1）。

只建立租户/成员/部门/岗位事实，不改变现有 `user_id` 鉴权与账本解析：

- 租户 0 = 本机账本；
- 每个现有用户 = 一个个人租户（id 与 user_id 对齐）+ owner 成员；
- 部门/岗位/成员均按 tenant_id 隔离；
- 暂不声明外键，等 current_user_id -> tenant_id 切换时再补。
"""

from __future__ import annotations

from typing import Any

ORG_ROLES = ("owner", "admin", "accountant", "approver", "viewer", "member")
ORG_STATUSES = ("active", "archived")
_UNSET = object()




def _text(value: Any, limit: int = 60, *, required: bool = True) -> str:
    s = str(value or "").strip()
    if not s and required:
        raise ValueError("名称不能为空")
    return s[:limit]


def _status(value: Any) -> str:
    s = str(value or "").strip().lower()
    if s not in ORG_STATUSES:
        raise ValueError("状态只能是 active / archived")
    return s


def _role(value: Any) -> str:
    s = str(value or "").strip().lower()
    if s not in ORG_ROLES:
        raise ValueError(f"角色只能是 {'/'.join(ORG_ROLES)}")
    return s


# ---------------------------------------------------------------------------
# 回填与个人租户
# ---------------------------------------------------------------------------




















# ---------------------------------------------------------------------------
# 读
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------














# ---------------------------------------------------------------------------
# 部门
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# 岗位
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# 成员
# ---------------------------------------------------------------------------


# 租户/部门/成员三组已拆出；import 触发并以同名属性保留（db 门面与 routes 直接用 org.xxx）
# 时间戳策略测试要求本模块暴露统一时钟（拆分后实际写入在 org_* 子模块）
from ..timeutil import now_str as _now  # noqa: F401,E402
from .org_dept import (  # noqa: F401,E402
    get_department,
    get_member,
    get_position,
    org_create_department,
    org_create_position,
    org_delete_department,
    org_delete_position,
    org_update_department,
    org_update_position,
)
from .org_member import (  # noqa: F401,E402
    org_add_member,
    org_remove_member,
    org_update_member,
)
from .org_tenant import (  # noqa: F401,E402
    backfill_org_shadow,
    ensure_personal_tenant,
    get_active_tenant,
    get_tenant,
    list_user_tenants,
    org_overview,
    org_role,
    resolve_tenant_id,
    set_active_tenant,
)
