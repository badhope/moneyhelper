"""连接中心工具（从 tools.py 拆出）：目录、建连同步、基金净值、交易指令。

登录类平台只回官方入口 + 一次性配对码；实盘指令只出交接单，由用户自己确认。
"""

from __future__ import annotations

import json
from typing import Any


async def tool_connect_catalog(_args: dict[str, Any]) -> str:
    """查连接中心目录：支持哪些平台（行情/券商/银行/支付/发票/公司）、各自怎么接、当前连接状态。"""
    from . import connect

    cat = connect.grouped_catalog()
    rows = []
    for g in cat["groups"]:
        items = [
            {
                "id": i["id"],
                "name": i["name"],
                "kind": i["kind"],
                "automation": i["automation"],
                "control": i["control"],
                "capabilities": i["capabilities"],
                "supports_trade": i["supports_trade"],
            }
            for i in g["items"]
        ]
        rows.append({"category": g["key"], "label": g["label"], "items": items})
    connections = await connect.list_connections()
    return json.dumps(
        {
            "counts": cat["counts"],
            "groups": rows,
            "connections": [
                {"id": c["id"], "connector_id": c["connector_id"], "label": c["label"], "status": c["status"]}
                for c in connections
            ],
            "hint": "用户说「连一下支付宝/招商银行」时，用 connect_sync 建连接；需要登录的平台会自动给出配对码与官方入口。control=read/import/handoff/manual 只代表读取或导入，confirm 只允许起草交易指令；任何平台都不代登录、代转账、代下实盘单。",
        },
        ensure_ascii=False,
    )
async def tool_connect_sync(args: dict[str, Any]) -> str:
    """建立连接并同步一次：公开源直接拉数据；登录类返回官方入口 + 一次性配对码。"""
    from . import connect

    connector_id = str(args.get("connector_id") or "").strip()
    if not connector_id:
        return "需要提供 connector_id，例如 alipay / cmb / eastmoney_fund（先用 connect_catalog 查）"
    existing = [c for c in await connect.list_connections() if c["connector_id"] == connector_id]
    label = str(args.get("label") or "").strip()
    try:
        if existing and (not label or any(c["label"] == label for c in existing)):
            conn = existing[0]
        else:
            conn = await connect.create_connection(
                connector_id, label, str(args.get("account_ref") or "")
            )
    except ValueError as exc:
        return f"建立连接失败：{exc}"
    if not bool(args.get("sync", True)):
        return json.dumps({"ok": True, "connection": conn, "synced": False}, ensure_ascii=False)
    job = await connect.sync_connection(conn["id"])
    return json.dumps(
        {
            "ok": job.get("status") == "done",
            "connection_id": conn["id"],
            "connector_id": connector_id,
            "label": conn["label"],
            "job": job,
            "hint": "登录类平台：把 login_url 发给用户，配对码 10 分钟有效、用后即焚。",
        },
        ensure_ascii=False,
        default=str,
    )
async def tool_connect_fund_nav(args: dict[str, Any]) -> str:
    """查场外基金最新净值（公开接口，免登录）：支持多只代码，逗号分隔。"""
    from .connect import marketdata

    codes = str(args.get("codes") or "").strip()
    if not codes:
        return "需要提供基金代码，如 110011"
    out = await marketdata.fund_nav(codes)
    return json.dumps(out, ensure_ascii=False, default=str)
async def tool_connect_order(args: dict[str, Any]) -> str:
    """生成交易指令：paper 模式可直接在模拟盘成交；live 模式只出交接单，由用户在券商页面下单。"""
    from . import connect

    mode = str(args.get("mode") or "paper")
    try:
        intent = await connect.create_intent(
            {
                "symbol": args.get("symbol"),
                "name": args.get("name") or "",
                "side": args.get("side"),
                "price": args.get("price"),
                "shares": args.get("shares"),
                "mode": mode,
                "connector_id": args.get("connector_id") or "",
            }
        )
    except ValueError as exc:
        return f"生成交易指令失败：{exc}"

    if not bool(args.get("execute")):
        return json.dumps(
            {"ok": True, "intent": intent, "executed": False, "hint": "指令已生成，待用户确认后执行"},
            ensure_ascii=False,
        )
    res = await connect.execute_trade_intent(intent["id"])
    return json.dumps(
        {"ok": res.get("ok"), **res, "disclaimer": "交易指令不构成投资建议；实盘需用户在券商页面自行确认。"},
        ensure_ascii=False,
        default=str,
    )
