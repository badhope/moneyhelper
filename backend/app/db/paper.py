"""团队模拟盘持久化（v4.2）：账户 / 交易 / 快照三表存取。

事件溯源：持仓与现金不落库，从 paper_trades 重放（见 calculations/paper.py）。
账户仅存开户参数；净值曲线用 paper_snapshots 按日存档（交易后自动补点 +
GET 详情时按需补今日点）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ._core import _conn, fetch_all, fetch_one
from .tenant import current_user_id

MAX_ACCOUNTS = 12  # 每团队最多 12 个模拟账户
MAX_TRADES_PER_ACCOUNT = 500  # 每账户最多 500 笔（事件溯源重放上限）


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()[:10]  # 本地时区日期


async def open_account(name: str, initial_cash: float) -> dict[str, Any]:
    """开户：创建模拟账户。返回账户记录。"""
    uid = current_user_id()
    name = (name or "").strip() or "模拟账户"
    try:
        initial_cash = round(float(initial_cash), 2)
    except (TypeError, ValueError) as e:
        raise ValueError("initial_cash 必须是数字") from e
    if initial_cash < 1000:
        raise ValueError("初始资金至少 1000 元")

    rows = await fetch_all(
        "SELECT account_id FROM paper_accounts WHERE user_id=?", (uid,)
    )
    if len(rows) >= MAX_ACCOUNTS:
        raise ValueError(f"最多 {MAX_ACCOUNTS} 个模拟账户")

    aid = uuid.uuid4().hex[:10]
    conn = await _conn()
    await conn.execute(
        "INSERT INTO paper_accounts(user_id,account_id,name,initial_cash,created_at)"
        " VALUES(?,?,?,?,?)",
        (uid, aid, name, initial_cash, _now_iso()),
    )
    await conn.commit()
    return {"account_id": aid, "name": name, "initial_cash": initial_cash}


async def delete_account(account_id: str) -> bool:
    """删除账户（含其交易与快照）。返回是否删除过。"""
    uid = current_user_id()
    conn = await _conn()
    cur = await conn.execute(
        "DELETE FROM paper_accounts WHERE user_id=? AND account_id=?", (uid, account_id)
    )
    if cur.rowcount == 0:
        return False
    await conn.execute(
        "DELETE FROM paper_trades WHERE user_id=? AND account_id=?", (uid, account_id)
    )
    await conn.execute(
        "DELETE FROM paper_snapshots WHERE user_id=? AND account_id=?", (uid, account_id)
    )
    await conn.commit()
    return True


async def get_account(account_id: str) -> dict[str, Any] | None:
    return await fetch_one(
        "SELECT account_id,name,initial_cash,created_at FROM paper_accounts"
        " WHERE user_id=? AND account_id=?",
        (current_user_id(), account_id),
    )


async def list_accounts() -> list[dict[str, Any]]:
    return await fetch_all(
        "SELECT account_id,name,initial_cash,created_at FROM paper_accounts"
        " WHERE user_id=? ORDER BY created_at ASC",
        (current_user_id(),),
    )


async def get_trades(account_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        "SELECT id,date,symbol,name,side,price,shares,fee,amount FROM paper_trades"
        " WHERE user_id=? AND account_id=? ORDER BY id ASC",
        (current_user_id(), account_id),
    )


async def add_trade(account_id: str, trade: dict[str, Any]) -> dict[str, Any]:
    """追加一笔交易（调用方已做引擎校验）。"""
    uid = current_user_id()
    rows = await fetch_all(
        "SELECT COUNT(*) AS c FROM paper_trades WHERE user_id=? AND account_id=?",
        (uid, account_id),
    )
    if rows[0]["c"] >= MAX_TRADES_PER_ACCOUNT:
        raise ValueError(f"单账户最多 {MAX_TRADES_PER_ACCOUNT} 笔交易")
    conn = await _conn()
    cur = await conn.execute(
        "INSERT INTO paper_trades(user_id,account_id,date,symbol,name,side,price,shares,fee,amount)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            uid,
            account_id,
            _now_iso(),
            str(trade["symbol"]).upper(),
            str(trade.get("name") or ""),
            trade["side"],
            round(float(trade["price"]), 4),
            round(float(trade["shares"]), 4),
            round(float(trade.get("fee") or 0.0), 2),
            round(float(trade["price"]) * float(trade["shares"]), 2),
        ),
    )
    await conn.commit()
    return {"id": cur.lastrowid, **trade}


async def snapshot_exists(account_id: str, date: str) -> bool:
    row = await fetch_one(
        "SELECT id FROM paper_snapshots WHERE user_id=? AND account_id=? AND date=?",
        (current_user_id(), account_id, date),
    )
    return row is not None


async def save_snapshot(account_id: str, equity: float, cash: float, market_value: float) -> None:
    """按日存档净值点（同日幂等覆盖）。"""
    uid = current_user_id()
    date = _today()
    conn = await _conn()
    if await snapshot_exists(account_id, date):
        await conn.execute(
            "UPDATE paper_snapshots SET equity=?, cash=?, market_value=? WHERE user_id=? AND account_id=? AND date=?",
            (round(equity, 2), round(cash, 2), round(market_value, 2), uid, account_id, date),
        )
    else:
        await conn.execute(
            "INSERT INTO paper_snapshots(user_id,account_id,date,equity,cash,market_value)"
            " VALUES(?,?,?,?,?,?)",
            (uid, account_id, date, round(equity, 2), round(cash, 2), round(market_value, 2)),
        )
    await conn.commit()


async def list_snapshots(account_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        "SELECT date,equity,cash,market_value FROM paper_snapshots"
        " WHERE user_id=? AND account_id=? ORDER BY date ASC",
        (current_user_id(), account_id),
    )
