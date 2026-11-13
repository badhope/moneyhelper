"""Casbin 影子引擎（切片 7a）：在真实请求上跑 Casbin 策略，但**只记录不拦截**。

为什么先影子、后拦截：
- 路线图选定 PyCasbin 做权限引擎，但策略必须基于稳定的权限点字典；
- 直接切拦截，一旦策略写错就是线上事故，而此时还没有足够真实流量验证过策略；
- 影子模式把"字典判定"与"代码实际放行"并排记下来，两者的差异（mismatch）
  就是切拦截之前必须先修掉的清单。

安全边界（必须守住）：
- 本模块的任何函数都不参与放行判定；调用方的真实判定结果才是最终结论；
- 记录失败（casbin 未安装、模型解析失败、写库失败）一律吞掉，绝不影响业务；
- casbin 缺失时整体降级为"不记录"，业务行为与没接影子时完全一致。

Casbin 模型：RBAC with domains，domain = tenant_id。
- `g, <user_id>, <role>, <tenant_id>`：某人在某租户里的角色；
- `p, <role>, <tenant_id>, <domain>, <action>`：角色在某租户内的权限点。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from . import authz

try:  # pragma: no cover - 取决于运行环境是否装了 casbin
    import casbin as _casbin

    _CASBIN_IMPORT_ERROR: str | None = None
except Exception as exc:  # noqa: BLE001 — 缺依赖是预期情况，走降级
    _casbin = None  # type: ignore[assignment]
    _CASBIN_IMPORT_ERROR = str(exc)

# pycasbin 每次新建 Enforcer 都会把整份模型打进 INFO 日志。
# 影子模式在每个企业域请求上都会建一次，不关掉的话日志会被模型文本刷屏。
logging.getLogger("casbin").setLevel(logging.WARNING)


# Casbin RBAC + domain 模型（tenant 作为 domain）
_CASBIN_MODEL = """
[request_definition]
r = sub, dom, obj, act

[policy_definition]
p = sub, dom, obj, act

[role_definition]
g = _, _, _

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub, r.dom) && r.dom == p.dom && (p.obj == r.obj || p.obj == "*") && (p.act == r.act || p.act == "*")
"""


def casbin_available() -> bool:
    """casbin 是否可用。不可用时影子整体停用（业务不受影响）。"""
    return _casbin is not None


def shadow_enabled() -> bool:
    """影子开关。默认开启；设 MONEYHELPER_AUTHZ_SHADOW=0 可停用。"""
    raw = os.getenv("MONEYHELPER_AUTHZ_SHADOW", "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _build_enforcer(tenant_id: int, memberships: list[tuple[int, str]]) -> Any:
    """按租户成员关系构建 Casbin 强制器。

    memberships: [(user_id, role), ...]
    同一角色只写一条策略，避免重复成员把策略集撑大。
    """
    model = _casbin.model.Model()
    model.load_model_from_text(_CASBIN_MODEL)
    enforcer = _casbin.Enforcer(model)
    dom = str(int(tenant_id))
    for user_id, role in memberships:
        enforcer.add_grouping_policy(str(int(user_id)), str(role), dom)
    seen: set[tuple[str, str, str]] = set()
    for _user_id, role in memberships:
        for permission_id in authz.role_permissions(role):
            domain, action = authz.split_permission(permission_id)
            key = (str(role), domain, action)
            if key in seen:
                continue
            seen.add(key)
            enforcer.add_policy(str(role), dom, domain, action)
    return enforcer


def evaluate(
    tenant_id: int,
    subject: str,
    role: str | None,
    permission_id: str,
) -> tuple[bool, str]:
    """按字典策略判定一次权限。返回 (是否放行, 说明)。

    没有角色 → 一律拒绝（fail-closed）。
    未知权限点 → 一律拒绝。
    """
    if not role:
        return False, "无角色（fail-closed）"
    if str(role) not in authz.ROLE_PERMISSIONS:
        return False, f"未知角色 {role}（fail-closed）"
    if not authz.known_permission(permission_id):
        return False, f"未知权限点 {permission_id}（fail-closed）"
    if _casbin is None:
        return False, "casbin 不可用（fail-closed）"
    try:
        enforcer = _build_enforcer(
            int(tenant_id), [(int(subject) if str(subject).isdigit() else 0, str(role))]
        )
        domain, action = authz.split_permission(permission_id)
        allowed = bool(
            enforcer.enforce(str(subject), str(int(tenant_id)), domain, action)
        )
        return allowed, "casbin 判定"
    except Exception as exc:  # noqa: BLE001 — 影子失败不得影响业务
        return False, f"casbin 判定失败：{exc}"


async def record_decision(
    *,
    tenant_id: int,
    user_id: int | None,
    role: str | None,
    permission_id: str,
    allowed: bool,
    reason: str = "",
    method: str = "",
    path: str = "",
) -> dict[str, Any]:
    """记录一次权限判定（只记录，不拦截）。

    返回记录结果摘要；任何异常都被吞掉，调用方不需要处理。
    """
    if not shadow_enabled() or _casbin is None:
        return {"recorded": False}
    subject = str(user_id if user_id is not None else 0)
    decision, detail = evaluate(tenant_id, subject, role, permission_id)
    mismatch = decision != bool(allowed)
    try:
        from .db import authz_shadow

        await authz_shadow.record_shadow_decision(
            tenant_id=int(tenant_id),
            user_id=user_id,
            role=role or "",
            subject=subject,
            permission_id=permission_id,
            decision="allow" if decision else "deny",
            allowed=bool(allowed),
            mismatch=mismatch,
            reason=f"{reason}｜{detail}" if reason else detail,
            method=method,
            path=path,
        )
        return {"recorded": True, "decision": decision, "mismatch": mismatch}
    except Exception:  # noqa: BLE001 — 影子写库失败不影响业务
        return {"recorded": False}


def status() -> dict[str, Any]:
    """影子引擎状态，供 API 展示。"""
    return {
        "enabled": shadow_enabled(),
        "casbin_available": casbin_available(),
        "import_error": _CASBIN_IMPORT_ERROR,
        "model": "rbac_with_domains",
        "domain_semantics": "tenant_id",
        "points": len(authz.PERMISSION_POINTS),
        "roles": list(authz.known_roles()),
    }
