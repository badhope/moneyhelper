"""配对码：短时效一次性码的签发与兑换（只换令牌，不落密码）。"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from ..db._core import _conn, fetch_one, get_write_lock
from ..db.tenant import current_user_id
from ..timeutil import now_iso as _now
from .catalog import get_connector
from .store_common import (
    PAIRING_TTL_MINUTES,
)


async def issue_pairing_code(connector_id: str) -> dict[str, Any]:
    """签发一次性配对码：10 分钟有效，用后即焚。

    配对码只证明「回传的数据属于这个用户」，不携带任何平台凭据；
    即使泄露，攻击者也只能往账本里写数据，不能读出数据或下单。
    """
    connector = get_connector(connector_id)
    if connector is None:
        raise ValueError(f"未知的连接器：{connector_id}")
    code = secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:12].upper()
    now = datetime.now().astimezone()
    expires = (now + timedelta(minutes=PAIRING_TTL_MINUTES)).isoformat(timespec="seconds")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO connect_pairings(user_id,code,connector_id,expires_at,used_at,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (current_user_id(), code, connector["id"], expires, "", now.isoformat(timespec="seconds")),
        )
        await conn.commit()
    return {
        "code": code,
        "connector_id": connector["id"],
        "connector_name": connector["name"],
        "expires_at": expires,
        "ttl_minutes": PAIRING_TTL_MINUTES,
        "login_url": connector.get("login_url") or connector.get("data_url") or "",
    }


async def redeem_pairing_code(code: str, connector_id: str = "") -> dict[str, Any]:
    """校验并消费配对码。返回 {user_id, connector_id, connector}。

    注意：这里按 code 全局查（不按当前租户过滤），因为书签脚本回传走免登录
    通道，请求上下文里没有 JWT。配对码本身就是「一次性能力凭据」：
    只能触发写入，不能读出任何数据，且 10 分钟过期、用后即焚。
    """
    raw = str(code or "").strip().upper()
    if not raw:
        raise ValueError("配对码不能为空")
    row = await fetch_one("SELECT * FROM connect_pairings WHERE code=?", (raw,))
    if not row:
        raise ValueError("配对码不存在")
    if str(row["used_at"] or "").strip():
        raise ValueError("配对码已被使用，请重新生成")
    try:
        expires = datetime.fromisoformat(str(row["expires_at"]))
    except ValueError:
        raise ValueError("配对码已损坏，请重新生成") from None
    if datetime.now().astimezone() > expires:
        raise ValueError("配对码已过期，请重新生成")
    if connector_id and str(row["connector_id"]) != str(connector_id):
        raise ValueError("配对码与连接器不匹配")

    uid = int(row["user_id"] or 0)
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "UPDATE connect_pairings SET used_at=? WHERE user_id=? AND code=?",
            (_now(), uid, raw),
        )
        await conn.commit()
    connector = get_connector(str(row["connector_id"])) or {}
    return {"user_id": uid, "connector_id": str(row["connector_id"]), "connector": connector}
