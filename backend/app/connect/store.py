"""连接中心持久化：连接账户 / 配对码 / 同步任务 / 交易意图。

表设计原则：
- 全部按租户隔离（user_id 复合主键），与仓库其他业务表口径一致；
- 平台密码、支付密码、短信验证码**永远不落库**：只存用户自己填的展示备注
  与「账号后四位」这类辨识信息；
- 任务与意图都是事件记录，不可变字段只追加，状态机单向推进；
- 每张表都带 created_at/updated_at，前端按时间排序不依赖 id。
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from ..db._core import _conn, _mark_user_data, fetch_all, fetch_one, get_write_lock
from ..db.tenant import current_user_id
from ..logging_utils import get_logger
from .catalog import get_connector

log = get_logger(__name__)

CONNECTION_STATUSES = ("unconfigured", "connected", "expiring", "error", "disabled")
INTENT_STATUSES = ("draft", "awaiting_confirm", "executed", "rejected", "expired")
JOB_STATUSES = ("queued", "running", "done", "failed")

PAIRING_TTL_MINUTES = 10
MAX_CONNECTIONS = 60
MAX_INTENTS = 500


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _dumps(v: Any) -> str:
    return json.dumps(v or {}, ensure_ascii=False, default=str)


def _loads(raw: Any) -> dict[str, Any]:
    try:
        val = json.loads(raw or "{}")
        return val if isinstance(val, dict) else {}
    except (TypeError, ValueError):
        return {}


# ---------------------------------------------------------------------------
# 连接账户
# ---------------------------------------------------------------------------


async def list_connections() -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM connect_accounts WHERE user_id=? ORDER BY created_at ASC",
        (current_user_id(),),
    )
    out = []
    for r in rows:
        row = dict(r)
        row["meta"] = _loads(row.pop("meta_json", "{}"))
        out.append(row)
    return out


async def get_connection(cid: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM connect_accounts WHERE user_id=? AND id=?",
        (current_user_id(), str(cid)),
    )
    if not row:
        return None
    out = dict(row)
    out["meta"] = _loads(out.pop("meta_json", "{}"))
    return out


async def create_connection(
    connector_id: str,
    label: str = "",
    account_ref: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """新增一条连接。connector_id 必须存在于内置目录，否则拒绝（防脏数据）。"""
    connector = get_connector(connector_id)
    if connector is None:
        raise ValueError(f"未知的连接器：{connector_id}")

    uid = current_user_id()
    rows = await fetch_all(
        "SELECT id FROM connect_accounts WHERE user_id=?", (uid,)
    )
    if len(rows) >= MAX_CONNECTIONS:
        raise ValueError(f"最多 {MAX_CONNECTIONS} 个连接")

    # 同一连接器允许建多条（多张卡/多个账户），但标签不能完全相同
    clean_label = (label or connector["name"]).strip()[:40] or connector["name"]
    dup = await fetch_one(
        "SELECT id FROM connect_accounts WHERE user_id=? AND connector_id=? AND label=?",
        (uid, connector["id"], clean_label),
    )
    if dup:
        raise ValueError(f"已存在同名连接：{clean_label}")

    cid = _new_id("conn")
    now = _now()
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO connect_accounts"
            "(user_id,id,connector_id,label,kind,status,account_ref,meta_json,last_sync_at,last_error,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uid,
                cid,
                connector["id"],
                clean_label,
                connector["kind"],
                "unconfigured",
                str(account_ref or "").strip()[:60],
                _dumps(meta),
                "",
                "",
                now,
                now,
            ),
        )
        await _mark_user_data(conn)
        await conn.commit()
    log.info("connect.created id=%s connector=%s", cid, connector["id"])
    return (await get_connection(cid)) or {}


async def update_connection(cid: str, patch: dict[str, Any]) -> dict[str, Any]:
    """更新连接：状态 / 标签 / 备注 / 错误信息。未知字段忽略。"""
    cur = await get_connection(cid)
    if cur is None:
        raise ValueError("连接不存在")

    status = str(patch.get("status") or cur["status"]).strip()
    if status not in CONNECTION_STATUSES:
        raise ValueError(f"状态只能是 {'/'.join(CONNECTION_STATUSES)}")

    label = str(patch.get("label") or cur["label"]).strip()[:40] or cur["label"]
    account_ref = str(patch.get("account_ref") or cur.get("account_ref") or "").strip()[:60]
    meta = patch.get("meta")
    meta_json = _dumps({**(cur.get("meta") or {}), **meta}) if isinstance(meta, dict) else _dumps(cur.get("meta") or {})
    last_error = str(patch.get("last_error", cur.get("last_error") or ""))[:300]

    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "UPDATE connect_accounts SET label=?, status=?, account_ref=?, meta_json=?, last_error=?, updated_at=?"
            " WHERE user_id=? AND id=?",
            (label, status, account_ref, meta_json, last_error, _now(), current_user_id(), cid),
        )
        await conn.commit()
    return (await get_connection(cid)) or {}


async def delete_connection(cid: str) -> bool:
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "DELETE FROM connect_accounts WHERE user_id=? AND id=?", (current_user_id(), cid)
        )
        await conn.commit()
        return cur.rowcount > 0


async def touch_sync(cid: str, ok: bool, error: str = "") -> None:
    """记录一次同步结果：成功刷新 last_sync_at 并置 connected，失败置 error。"""
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "UPDATE connect_accounts SET status=?, last_sync_at=?, last_error=?, updated_at=?"
            " WHERE user_id=? AND id=?",
            (
                "connected" if ok else "error",
                _now() if ok else "",
                "" if ok else error[:300],
                _now(),
                current_user_id(),
                cid,
            ),
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# 配对码（浏览器代登录 / 书签脚本回传的一次性凭据）
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 同步任务
# ---------------------------------------------------------------------------


async def create_job(connector_id: str, kind: str = "sync", message: str = "") -> dict[str, Any]:
    connector = get_connector(connector_id)
    if connector is None:
        raise ValueError(f"未知的连接器：{connector_id}")
    jid = _new_id("job")
    now = _now()
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO connect_jobs"
            "(user_id,id,connector_id,kind,status,progress,message,result_json,created_at,finished_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (current_user_id(), jid, connector["id"], str(kind)[:20], "queued", 0.0, str(message)[:200], "{}", now, ""),
        )
        await conn.commit()
    return {
        "id": jid,
        "connector_id": connector["id"],
        "kind": str(kind),
        "status": "queued",
        "progress": 0.0,
        "message": str(message),
        "created_at": now,
    }


async def finish_job(
    job_id: str,
    ok: bool,
    message: str = "",
    result: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "UPDATE connect_jobs SET status=?, progress=?, message=?, result_json=?, finished_at=?"
            " WHERE user_id=? AND id=?",
            (
                "done" if ok else "failed",
                1.0 if ok else 0.0,
                str(message)[:300],
                _dumps(result),
                _now(),
                current_user_id(),
                job_id,
            ),
        )
        await conn.commit()
    rows = await fetch_all(
        "SELECT * FROM connect_jobs WHERE user_id=? AND id=?", (current_user_id(), job_id)
    )
    if not rows:
        return None
    out = dict(rows[0])
    out["result"] = _loads(out.pop("result_json", "{}"))
    return out


async def list_jobs(limit: int = 30) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM connect_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (current_user_id(), max(1, min(int(limit), 200))),
    )
    out = []
    for r in rows:
        row = dict(r)
        row["result"] = _loads(row.pop("result_json", "{}"))
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# 交易意图（把「买/卖」变成可审计的指令，而不是直接下单）
# ---------------------------------------------------------------------------


async def create_intent(payload: dict[str, Any]) -> dict[str, Any]:
    """创建交易意图：标的 / 方向 / 价格 / 股数 / 执行方式（paper 模拟盘，live 实盘交接）。"""
    connector_id = str(payload.get("connector_id") or "").strip()
    if connector_id:
        connector = get_connector(connector_id)
        if connector is None:
            raise ValueError(f"未知的连接器：{connector_id}")
        if not connector.get("supports_trade"):
            raise ValueError(f"{connector['name']} 不支持交易委托")

    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        raise ValueError("标的不为空")
    side = str(payload.get("side") or "").strip().lower()
    if side not in ("buy", "sell"):
        raise ValueError("方向只能是 buy / sell")
    try:
        price = float(payload.get("price") or 0)
        shares = float(payload.get("shares") or 0)
    except (TypeError, ValueError):
        raise ValueError("价格与股数必须是数字") from None
    if price <= 0 or shares <= 0:
        raise ValueError("价格与股数必须大于 0")

    mode = str(payload.get("mode") or "paper").strip()
    if mode not in ("paper", "live"):
        raise ValueError("mode 只能是 paper / live")

    rows = await fetch_all("SELECT id FROM connect_intents WHERE user_id=?", (current_user_id(),))
    if len(rows) >= MAX_INTENTS:
        # 只清理最老的已终结记录，保留待确认与已执行（审计需要）
        conn = await _conn()
        async with get_write_lock():
            await conn.execute(
                "DELETE FROM connect_intents WHERE user_id=? AND status IN ('rejected','expired')"
                " AND id IN (SELECT id FROM connect_intents WHERE user_id=? AND status IN ('rejected','expired')"
                " ORDER BY created_at ASC LIMIT ?)",
                (current_user_id(), current_user_id(), max(1, len(rows) - MAX_INTENTS + 1)),
            )
            await conn.commit()

    iid = _new_id("ord")
    now = _now()
    amount = round(price * shares, 2)
    status = "awaiting_confirm"
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO connect_intents"
            "(user_id,id,connector_id,symbol,name,side,price,shares,amount,mode,status,note,result_json,created_at,executed_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                current_user_id(),
                iid,
                connector_id,
                symbol,
                str(payload.get("name") or "").strip()[:40],
                side,
                round(price, 4),
                round(shares, 4),
                amount,
                mode,
                status,
                str(payload.get("note") or "").strip()[:200],
                "{}",
                now,
                "",
            ),
        )
        await _mark_user_data(conn)
        await conn.commit()
    return (await get_intent(iid)) or {}


async def get_intent(iid: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM connect_intents WHERE user_id=? AND id=?",
        (current_user_id(), str(iid)),
    )
    if not row:
        return None
    out = dict(row)
    out["result"] = _loads(out.pop("result_json", "{}"))
    return out


async def list_intents(limit: int = 50, status: str = "") -> list[dict[str, Any]]:
    params: list[Any] = [current_user_id()]
    sql = "SELECT * FROM connect_intents WHERE user_id=?"
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    rows = await fetch_all(sql, tuple(params))
    out = []
    for r in rows:
        row = dict(r)
        row["result"] = _loads(row.pop("result_json", "{}"))
        out.append(row)
    return out


async def update_intent(
    iid: str,
    status: str,
    note: str = "",
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in INTENT_STATUSES:
        raise ValueError(f"状态只能是 {'/'.join(INTENT_STATUSES)}")
    cur = await get_intent(iid)
    if cur is None:
        raise ValueError("交易意图不存在")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "UPDATE connect_intents SET status=?, note=?, result_json=?, executed_at=?"
            " WHERE user_id=? AND id=?",
            (
                status,
                (note or cur.get("note") or "")[:200],
                _dumps(result if result is not None else cur.get("result")),
                _now() if status == "executed" else (cur.get("executed_at") or ""),
                current_user_id(),
                iid,
            ),
        )
        await conn.commit()
    return (await get_intent(iid)) or {}
