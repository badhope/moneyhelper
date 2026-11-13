"""用户体系：注册/查询/密码校验/登录时间。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ._core import (
    _conn,
    fetch_all,
)
from .org import ensure_personal_tenant

# --------------------------------------------------------------------------
# 用户体系（多租户基础）
# --------------------------------------------------------------------------


def _hash_password(password: str) -> str:
    """bcrypt 哈希（直接用 bcrypt 库，不经过 passlib）。

    为什么不用 passlib：passlib 1.7.4 读取 `bcrypt.__about__.__version__`，
    而 bcrypt>=4.1 已移除该属性，导致 `bcrypt.using(...).hash()` 直接抛
    "password cannot be longer than 72 bytes"（专家评审 P0-4：注册接口 500）。
    bcrypt 本身 API 稳定，直接调用更可靠。
    """
    import bcrypt

    # bcrypt 只接受前 72 字节；超长口令先截断（不改变安全性：72 字节后无意义）
    raw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode()


def _verify_password(password: str, hashed: str) -> bool:
    """校验口令，兼容 passlib 生成的 $2b$ 旧哈希。"""
    import bcrypt

    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode())
    except Exception:
        return False


async def user_create(
    username: str, password: str, display_name: str = "", role: str = "user"
) -> int:
    """创建用户，返回行 id。username 唯一；密码 bcrypt 哈希。"""
    pw_hash = _hash_password(password)
    conn = await _conn()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    cur = await conn.execute(
        "INSERT INTO users(username, password_hash, display_name, role, created_at) "
        "VALUES(?,?,?,?,?)",
        (username, pw_hash, display_name or username, role, now),
    )
    uid = int(cur.lastrowid)
    # 企业底座影子模型：每个用户同步拥有个人租户与 owner 成员资格。
    # 不改变现有鉴权；仅让组织 API 从第一天起就有完整事实。
    await ensure_personal_tenant(conn, uid, username, display_name or username, now)
    await conn.commit()
    return uid


async def user_get_by_username(username: str) -> dict[str, Any] | None:
    conn = await _conn()
    cur = await conn.execute(
        "SELECT id, username, password_hash, display_name, role, disabled, last_login, created_at "
        "FROM users WHERE username=?",
        (username,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def user_get(uid: int) -> dict[str, Any] | None:
    conn = await _conn()
    cur = await conn.execute(
        "SELECT id, username, password_hash, display_name, role, disabled, last_login, created_at "
        "FROM users WHERE id=?",
        (uid,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def user_verify_password(user: dict[str, Any], password: str) -> bool:
    return _verify_password(password, str(user.get("password_hash") or ""))


async def user_update_last_login(uid: int) -> None:
    conn = await _conn()
    await conn.execute(
        "UPDATE users SET last_login=? WHERE id=?",
        (datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), uid),
    )
    await conn.commit()


async def user_count() -> int:
    """实例内账号总数（含已停用）。

    不能用 `disabled=0` 过滤：如果全部账号都被停用，计数会变成 0，鉴权闸会
    误判为"尚未启用账号体系"并放行本机模式，等于停用账号反而打开了后门。
    登录页/鉴权闸需要的是"是否存在账号体系"，不是"有多少活跃账号"。
    """
    conn = await _conn()
    cur = await conn.execute("SELECT COUNT(*) AS n FROM users")
    row = await cur.fetchone()
    return int(row["n"]) if row else 0


async def user_list() -> list[dict[str, Any]]:
    """列出所有用户（只给管理员用的账号视图，不含密码哈希）。"""
    return await fetch_all(
        "SELECT id, username, display_name, role, disabled, last_login, created_at"
        " FROM users ORDER BY id"
    )


async def counts_by_tenant() -> dict[int, dict[str, int]]:
    """各租户的数据条数概览（只给管理员看规模，不暴露任何明细）。

    这是"管理员可见范围"的边界：条数能回答"这个实例有多少人在用、各自多少数据"，
    但不含金额、名称、流水内容——避免把隐私能力做成后门。
    """
    tables = ("positions", "transactions", "goals", "user_memory", "runs")
    out: dict[int, dict[str, int]] = {}
    for table in tables:
        rows = await fetch_all(
            f"SELECT user_id, COUNT(*) AS n FROM {table} GROUP BY user_id"
        )
        for row in rows:
            uid = int(row["user_id"])
            out.setdefault(uid, {})
            out[uid][table] = int(row["n"])
    return out
