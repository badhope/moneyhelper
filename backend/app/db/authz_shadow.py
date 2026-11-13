"""权限影子决策存储（切片 7a）：记录"字典判定"与"代码实际放行"的并排结果。

这张表是切到 Casbin 拦截之前的验收清单：
- decision = Casbin 影子引擎按权限点字典给出的判定（allow/deny）；
- allowed = 真实代码这次请求有没有放行；
- mismatch = 两者不一致。不一致的地方要么是代码漏判，要么是字典写错了，
  两种都得先修，不能带着差异切拦截。

表本身只追加、不参与任何业务判定；即使写入失败，业务路径也不能受影响。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._core import _clamp_limit, _conn, fetch_all, fetch_one, get_write_lock


async def record_shadow_decision(
    *,
    tenant_id: int,
    user_id: int | None,
    role: str,
    subject: str,
    permission_id: str,
    decision: str,
    allowed: bool,
    mismatch: bool,
    reason: str = "",
    method: str = "",
    path: str = "",
) -> dict[str, Any]:
    """写一条影子决策。返回写入的 id。

    走项目统一的写锁 + 显式事务：影子写发生在请求路径上，
    不能把别的请求尚未提交的事务顺手 commit 掉（审计模块踩过这个坑）。
    """
    conn = await _conn()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await conn.execute(
                "INSERT INTO authz_shadow_log(tenant_id,user_id,role,subject,permission_id,"
                "decision,allowed,mismatch,reason,method,path,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    int(tenant_id or 0),
                    None if user_id is None else int(user_id),
                    str(role or "")[:32],
                    str(subject or "")[:64],
                    str(permission_id or "")[:64],
                    "allow" if str(decision).lower() == "allow" else "deny",
                    1 if allowed else 0,
                    1 if mismatch else 0,
                    str(reason or "")[:200],
                    str(method or "")[:8],
                    str(path or "")[:200],
                    now,
                ),
            )
            await conn.execute("COMMIT")
        except BaseException:
            try:
                await conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            raise
    return {"ok": True, "id": cur.lastrowid}


async def list_shadow_decisions(
    tenant_id: int | None = None,
    limit: int = 200,
    only_mismatch: bool = False,
) -> list[dict[str, Any]]:
    """列影子决策（新→旧）。tenant_id 为 None 时不限租户。"""
    clamped = _clamp_limit(limit, default=200)
    where = []
    params: list[Any] = []
    if tenant_id is not None:
        where.append("tenant_id=?")
        params.append(int(tenant_id))
    if only_mismatch:
        where.append("mismatch=1")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(clamped)
    return await fetch_all(
        f"SELECT * FROM authz_shadow_log{clause} ORDER BY id DESC LIMIT ?",
        params,
    )


async def shadow_summary(tenant_id: int | None = None) -> dict[str, Any]:
    """影子决策汇总：总量、allow/deny 数、不一致数、按权限点分组。"""
    where = ""
    params: list[Any] = []
    if tenant_id is not None:
        where = " WHERE tenant_id=?"
        params.append(int(tenant_id))
    row = await fetch_one(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN decision='allow' THEN 1 ELSE 0 END) AS allows,"
        " SUM(CASE WHEN decision='deny' THEN 1 ELSE 0 END) AS denies,"
        " SUM(CASE WHEN mismatch=1 THEN 1 ELSE 0 END) AS mismatches"
        f" FROM authz_shadow_log{where}",
        params,
    )
    totals = dict(row) if row is not None else {}
    by_permission = await fetch_all(
        "SELECT permission_id, decision, COUNT(*) AS n,"
        " SUM(CASE WHEN mismatch=1 THEN 1 ELSE 0 END) AS mismatches"
        f" FROM authz_shadow_log{where}"
        " GROUP BY permission_id, decision ORDER BY n DESC",
        params,
    )
    mismatch_clause = f"{where} AND mismatch=1" if where else " WHERE mismatch=1"
    mismatches = await fetch_all(
        "SELECT permission_id, role, decision, allowed, reason, method, path, created_at"
        f" FROM authz_shadow_log{mismatch_clause}"
        " ORDER BY id DESC LIMIT 50",
        params,
    )
    return {
        "total": int(totals.get("total") or 0),
        "allows": int(totals.get("allows") or 0),
        "denies": int(totals.get("denies") or 0),
        "mismatches": int(totals.get("mismatches") or 0),
        "by_permission": by_permission,
        "mismatch_samples": mismatches,
    }


async def clear_shadow_decisions(tenant_id: int | None = None) -> dict[str, Any]:
    """清空影子决策（仅影子数据，不触碰审计链）。"""
    conn = await _conn()
    if tenant_id is None:
        cur = await conn.execute("DELETE FROM authz_shadow_log")
    else:
        cur = await conn.execute(
            "DELETE FROM authz_shadow_log WHERE tenant_id=?", (int(tenant_id),)
        )
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount or 0}
