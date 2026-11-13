"""企业权限点字典（切片 7a）：把「谁能做什么」固化成一张可审计的表。

为什么需要这张表：
- 组织 / 总账 / 报销 / 付款 / 对账 5 个域各自用 `_require_role(user, roles)` 判定，
  角色表散落在 5 个路由模块里。新增一个角色或新增一个域时，
  没人能一句话回答"会计到底能不能过账"；
- 路线图把 PyCasbin 定为权限引擎，但 Casbin 策略必须先有稳定的权限点字典，
  否则写出来的 p 规则只是把一个没定稿的模型固化进代码。

设计：
- 权限点 = `<域>:<动作>`，例如 `gl:post`（过账与反冲）、`expense:approve`（审核报销）；
- 角色 → 权限点是纯数据 + 纯函数，无 I/O，便于单测；
- 未知角色 / 未知权限点一律 fail-closed（空集 / False）；
- 字典描述的是**目标策略**。真实代码里的判定若与之不符，
  由影子模式（app/authz_engine.py）记成 mismatch 暴露出来，而不是在这里偷偷放行。

本机单用户与共享口令统一用 LOCAL_ROLE：它们是实例所有者，
但只能操作本机租户；租户隔离由调用方的租户校验负责，字典不越权放行。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionPoint:
    """一个权限点：`domain:action`。"""

    id: str
    domain: str
    action: str
    description: str


# ---------------------------------------------------------------------------
# 权限点全集
# ---------------------------------------------------------------------------
# 划分原则：一个动作只要能被"通过 / 不通过"影响，就该是独立权限点，
# 不要把过账和关账混成一个 write——它们的职责分离要求不同。

PERMISSION_POINTS: tuple[PermissionPoint, ...] = (
    # 组织架构
    PermissionPoint("org:read", "org", "read", "查看部门/岗位/成员"),
    PermissionPoint("org:write", "org", "write", "维护部门/岗位/成员"),
    # 复式总账
    PermissionPoint("gl:read", "gl", "read", "查看科目/期间/凭证/试算表"),
    PermissionPoint("gl:write", "gl", "write", "维护科目/期间与凭证草稿"),
    PermissionPoint("gl:post", "gl", "post", "过账与反冲凭证"),
    PermissionPoint("gl:close", "gl", "close", "关闭会计期间"),
    # 报销
    PermissionPoint("expense:read", "expense", "read", "查看报销单"),
    PermissionPoint("expense:create", "expense", "create", "新建与提交报销单"),
    PermissionPoint("expense:approve", "expense", "approve", "审核与驳回报销单"),
    # 付款（出纳执行，不改总账）
    PermissionPoint("payment:read", "payment", "read", "查看付款记录"),
    PermissionPoint("payment:create", "payment", "create", "登记付款"),
    # 银行流水
    PermissionPoint("bank:read", "bank", "read", "查看银行流水"),
    PermissionPoint("bank:write", "bank", "write", "新增与导入银行流水"),
    PermissionPoint("bank:match", "bank", "match", "匹配与取消匹配银行流水"),
    # 对账签核
    PermissionPoint("reconciliation:read", "reconciliation", "read", "查看对账记录"),
    PermissionPoint("reconciliation:write", "reconciliation", "write", "新建对账会话"),
    PermissionPoint("reconciliation:sign", "reconciliation", "sign", "签核关账"),
    # 采购（切片 8）：采购单审核只代表采购获批，不直接改总账
    PermissionPoint("procurement:read", "procurement", "read", "查看供应商与采购单"),
    PermissionPoint("procurement:write", "procurement", "write", "维护供应商、创建与提交采购单"),
    PermissionPoint("procurement:approve", "procurement", "approve", "审核采购单"),
    # 应付（切片 8）：审核生成应付凭证草稿，付款生成付款凭证草稿
    PermissionPoint("payable:read", "payable", "read", "查看应付单"),
    PermissionPoint("payable:write", "payable", "write", "创建与提交应付单"),
    PermissionPoint("payable:approve", "payable", "approve", "审核应付单"),
    PermissionPoint("payable:pay", "payable", "pay", "登记应付付款"),
)

PERMISSION_IDS: frozenset[str] = frozenset(p.id for p in PERMISSION_POINTS)

# 本机单用户 / 共享口令：实例所有者
LOCAL_ROLE = "local"

_ALL_PERMISSIONS = frozenset(PERMISSION_IDS)

# ---------------------------------------------------------------------------
# 角色 → 权限点
# ---------------------------------------------------------------------------
# 与各路由模块 docstring 声明的策略保持一致（这是"目标策略"）：
# - org：读=任意有效成员，写=owner/admin
# - gl：读=任意有效成员，写=owner/admin/accountant
# - expense：读/创建=任意有效成员，审核=owner/admin/approver
# - payment / bank / reconciliation：读=任意有效成员，写=owner/admin/accountant
#
# 与实现的已知差异（由影子模式暴露，不在这里抹平）：
# - viewer 目前也能新建报销单（实现按"任意成员"放行），按只读语义不应有 expense:create；
# - 会计目前不能审核报销（实现里 approver 角色不含 accountant），保持不变。

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    # 所有者 / 管理员：域内全部权限
    "owner": _ALL_PERMISSIONS,
    "admin": _ALL_PERMISSIONS,
    # 会计：总账全流程 + 付款/流水/对账，**不含审批**
    "accountant": frozenset(
        {
            "org:read",
            "gl:read",
            "gl:write",
            "gl:post",
            "gl:close",
            "expense:read",
            "expense:create",
            "payment:read",
            "payment:create",
            "bank:read",
            "bank:write",
            "bank:match",
            "reconciliation:read",
            "reconciliation:write",
            "reconciliation:sign",
            "procurement:read",
            "procurement:write",
            "payable:read",
            "payable:write",
            "payable:pay",
        }
    ),
    # 审批人：普通成员权限 + 审核报销
    # （成员权限是底座：审批人也是员工，不能因为"只负责审批"就报不了自己的差旅）
    "approver": frozenset(
        {
            "org:read",
            "gl:read",
            "expense:read",
            "expense:create",
            "expense:approve",
            "payment:read",
            "bank:read",
            "reconciliation:read",
            "procurement:read",
            "procurement:approve",
            "payable:read",
            "payable:approve",
        }
    ),
    # 只读旁观：只有读权限
    "viewer": frozenset(
        {
            "org:read",
            "gl:read",
            "expense:read",
            "payment:read",
            "bank:read",
            "reconciliation:read",
            "procurement:read",
            "payable:read",
        }
    ),
    # 普通成员：只读 + 建自己的报销单
    "member": frozenset(
        {
            "org:read",
            "gl:read",
            "expense:read",
            "expense:create",
            "payment:read",
            "bank:read",
            "reconciliation:read",
            "procurement:read",
            "payable:read",
        }
    ),
    # 本机所有者 / 共享口令
    LOCAL_ROLE: _ALL_PERMISSIONS,
}


def role_permissions(role: str | None) -> frozenset[str]:
    """角色拥有的权限点集合；未知/空角色返回空集（fail-closed）。"""
    if not role:
        return frozenset()
    return ROLE_PERMISSIONS.get(str(role).strip().lower(), frozenset())


def allows(role: str | None, permission_id: str | None) -> bool:
    """该角色是否拥有该权限点。未知权限点一律 False。"""
    if not permission_id:
        return False
    return str(permission_id) in role_permissions(role)


def split_permission(permission_id: str) -> tuple[str, str]:
    """`gl:post` → `("gl", "post")`；无冒号时整体当域。"""
    domain, _, action = str(permission_id or "").partition(":")
    return domain, action


def known_permission(permission_id: str | None) -> bool:
    """权限点是否在字典内。"""
    return str(permission_id or "") in PERMISSION_IDS


def known_roles() -> tuple[str, ...]:
    return tuple(ROLE_PERMISSIONS)


def roles_with(permission_id: str, *, include_local: bool = False) -> tuple[str, ...]:
    """拥有该权限点的角色集合——**从字典派生，不手写角色列表**。

    手写角色列表的代价：新增权限点时容易漏掉某个域，于是同一件事在不同模块
    要求的角色不一样（报销要 owner/admin/approver，总账要 owner/admin/accountant），
    没人说得清为什么。字典派生之后，权限点只有一处定义。

    include_local=False 时排除 LOCAL_ROLE（本机/共享口令）：那不是一种成员资格，
    本机模式的放行由调用方单独处理，不该混进角色白名单。
    """
    roles = tuple(r for r, perms in ROLE_PERMISSIONS.items() if permission_id in perms)
    if not include_local:
        roles = tuple(r for r in roles if r != LOCAL_ROLE)
    return roles


def describe() -> dict[str, object]:
    """字典快照，供 API / 前端展示。"""
    return {
        "points": [
            {
                "id": p.id,
                "domain": p.domain,
                "action": p.action,
                "description": p.description,
                # 反向索引：谁能做这件事（管理员排查权限问题时的第一视角）
                "roles": list(roles_with(p.id)),
            }
            for p in PERMISSION_POINTS
        ],
        "roles": {role: sorted(ids) for role, ids in ROLE_PERMISSIONS.items()},
        "local_role": LOCAL_ROLE,
    }
