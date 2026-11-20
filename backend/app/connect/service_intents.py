"""交易意图执行：paper 直接写模拟盘，live 只生成交接单。"""

from __future__ import annotations

from typing import Any

from .. import db
from ..logging_utils import get_logger
from ..provenance import record_provenance
from . import store

log = get_logger(__name__)

async def _pick_paper_account() -> str:
    """取一个模拟盘账户；没有就用 10 万虚拟资金开一个「连接中心」账户。"""
    accounts = await db.list_accounts()
    if accounts:
        return str(accounts[0]["account_id"])
    acc = await db.open_account("连接中心自动执行", 100000.0)
    return str(acc["account_id"])


async def execute_trade_intent(intent_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """执行交易意图。

    paper：直接写模拟盘（整手/资金/持仓校验由 calculations.paper 负责）。
    live ：不代下单，返回券商入口 + 交接信息，状态保持待确认，由用户回填成交。
    """
    from ..calculations.paper import estimate, fee_for, validate_trade

    payload = payload or {}
    intent = await store.get_intent(intent_id)
    if intent is None:
        raise ValueError("交易意图不存在")
    if intent["status"] not in ("awaiting_confirm", "draft"):
        raise ValueError(f"当前状态不可执行：{intent['status']}")

    connector = None
    if intent.get("connector_id"):
        from .catalog import get_connector

        connector = get_connector(str(intent["connector_id"]))

    if intent["mode"] == "live":
        from ..compat_env import getenv

        base = getenv("MONEYHELPER_PUBLIC_URL").strip() or "http://127.0.0.1:8788"
        url = (connector or {}).get("login_url") or ""
        result = {
            "mode": "live",
            "handoff_url": url,
            "connector": (connector or {}).get("name", ""),
            "instruction": "请到券商页面按以下指令手动下单，成交后回到本页点「已成交」回填实际价格与数量",
            "order": {
                "symbol": intent["symbol"],
                "side": intent["side"],
                "price": intent["price"],
                "shares": intent["shares"],
                "amount": intent["amount"],
            },
            "ingest_endpoint": f"{base}/api/connect/intents/{intent_id}/confirm",
        }
        updated = await store.update_intent(intent_id, "awaiting_confirm", note="已生成实盘交接单", result=result)
        return {"ok": True, "intent": updated, "handoff": result}

    account_id = str(payload.get("account_id") or "") or await _pick_paper_account()
    account = await db.get_account(account_id)
    if account is None:
        raise ValueError("模拟盘账户不存在")

    trades = await db.get_trades(account_id)
    symbol = str(intent["symbol"]).upper()
    price = float(intent["price"])
    shares = float(intent["shares"])
    side = str(intent["side"])
    err = validate_trade(account["initial_cash"], trades, side, symbol, price, shares)
    if err:
        updated = await store.update_intent(intent_id, "rejected", note=err, result={"ok": False, "error": err})
        return {"ok": False, "error": err, "intent": updated}

    amount = price * shares
    fee = fee_for(side, amount)
    trade = await db.add_trade(
        account_id,
        {
            "symbol": symbol,
            "name": str(intent.get("name") or ""),
            "side": side,
            "price": price,
            "shares": shares,
            "fee": fee,
        },
    )
    est = estimate(account["initial_cash"], await db.get_trades(account_id))
    await db.save_snapshot(account_id, est["equity"], est["cash"], est["market_value"])
    result = {
        "mode": "paper",
        "account_id": account_id,
        "trade_id": trade.get("id"),
        "fee": fee,
        "fill_price": price,
        "fill_shares": shares,
        "estimate": est,
    }
    updated = await store.update_intent(intent_id, "executed", note="模拟盘已成交", result=result)
    await record_provenance(
        action="connect_execute_intent",
        entity_type="trade_intent",
        entity_id=intent_id,
        before={"status": intent["status"]},
        after={"status": "executed", "symbol": symbol, "side": side, "shares": shares, "price": price},
        source="connect",
    )
    return {
        "ok": True,
        "intent": updated,
        "trade": trade,
        "fee": fee,
        "estimate": est,
        "valuation_source": "last_trade",
    }
