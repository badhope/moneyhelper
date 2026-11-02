"""连接中心业务服务：同步、导入收件箱、交易意图执行、书签脚本生成。

这里只做「编排」：具体取数在 marketdata，落库在 store，账本写入复用既有 db 层。
所有外部失败都转成可读的 job.result，不向调用方抛 5xx。
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .. import db
from ..csvimport import classify as auto_classify
from ..import_parsers import get_parser
from ..logging_utils import get_logger
from ..provenance import record_provenance
from . import marketdata, store

log = get_logger(__name__)

MAX_INBOX_FILE_BYTES = 20 * 1024 * 1024


def inbox_dir(user_id: int | None = None) -> Path:
    """账单收件目录：用户把导出的 CSV 放进来，后台自动扫描入账。

    按租户分目录（import-inbox/u<id>/）：多用户实例下各自看到各自的收件箱，
    不会把别人的账单扫进自己账本。
    """
    from ..db.tenant import current_user_id

    uid = current_user_id() if user_id is None else int(user_id)
    path = db.data_dir() / "import-inbox" / f"u{uid}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 浏览器代登录：书签脚本（不需要装扩展，登录后点一下就回传）
# ---------------------------------------------------------------------------


def build_bookmarklet(base_url: str, code: str, connector_id: str, lang: str = "zh") -> str:
    """生成一段 javascript: 书签脚本。

    作用：在用户已登录的目标平台页面上，抓取当前页面的可见文本/表格，
    以配对码回传本机服务。**不读取 cookie、不读取密码、不跨域偷数据**——
    它只能看到用户当前正在看的这一页，等价于用户自己复制粘贴。

    安全边界：脚本里只有回传地址与一次性配对码，没有用户凭据。
    """
    endpoint = f"{base_url.rstrip('/')}/api/connect/ingest?code={quote(code)}&connector_id={quote(connector_id)}"
    label = "回传本页" if lang != "en" else "Send this page"
    body = (
        "javascript:(function(){"
        "var t=document.body?document.body.innerText:'';"
        f"var u='{endpoint}';"
        "fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({title:document.title,url:location.href,text:t.slice(0,200000)})})"
        ".then(function(r){return r.json()})"
        ".then(function(j){alert(" + repr(label) + "+': '+(j&&j.ok?('OK '+(j.imported||0)+' rows'):('FAIL '+((j&&j.error)||''))))})"
        ".catch(function(e){alert('FAIL '+e)});"
        "})();"
    )
    return body


# ---------------------------------------------------------------------------
# 同步
# ---------------------------------------------------------------------------


async def sync_connection(connection_id: str, lang: str = "zh") -> dict[str, Any]:
    """执行一次同步，返回 job 记录（含 result）。"""
    conn = await store.get_connection(connection_id)
    if conn is None:
        raise ValueError("连接不存在")
    from .catalog import get_connector

    connector = get_connector(conn["connector_id"]) or {}
    kind = connector.get("kind", "")
    job = await store.create_job(conn["connector_id"], kind="sync", message="开始同步")

    try:
        if kind == "public_api":
            result = await _sync_public(conn, connector)
        elif kind == "file_import":
            result = await scan_import_inbox()
        else:
            result = await _handoff(conn, connector, lang=lang)
    except Exception as exc:  # noqa: BLE001 — 单个连接失败不影响其他连接
        log.warning("connect.sync_failed id=%s err=%s", connection_id, exc)
        await store.touch_sync(connection_id, ok=False, error=str(exc))
        return (await store.finish_job(job["id"], False, f"同步失败：{exc}")) or job

    ok = bool(result.get("ok", True))
    if ok:
        await store.touch_sync(connection_id, ok=True)
    else:
        await store.touch_sync(connection_id, ok=False, error=str(result.get("note") or "同步未完成"))
    finished = await store.finish_job(job["id"], ok, str(result.get("message") or ""), result)
    return finished or job


async def _sync_public(conn: dict[str, Any], connector: dict[str, Any]) -> dict[str, Any]:
    """公开数据源同步：按连接器能力拉数据并落一份任务结果。"""
    cid = connector["id"]
    cap = set(connector.get("capabilities") or [])
    summary: dict[str, Any] = {"ok": True, "message": "已刷新", "source": connector["name"]}

    if cid in ("eastmoney_fund", "ttjj") or ("quotes" in cap and connector["category"] == "fund"):
        codes = str((conn.get("meta") or {}).get("fund_codes") or "").strip()
        nav = await marketdata.fund_nav(codes or "110011")
        summary["fund_nav"] = nav
        if not nav["items"]:
            summary.update(ok=False, message=nav.get("note") or "基金净值无返回")
    elif cid in ("eastmoney_quote", "sina_quote"):
        snap = await marketdata.index_snapshot()
        summary["indices"] = snap
        if not snap["items"]:
            summary.update(ok=False, message=snap.get("note") or "指数行情无返回")
    elif cid == "eastmoney_movers":
        movers = await marketdata.market_movers("gainers", 10)
        summary["movers"] = movers
        if not movers["items"]:
            summary.update(ok=False, message=movers.get("note") or "涨跌榜无返回")
    else:
        status = await marketdata.source_status()
        summary["source_status"] = status
        ok_items = [i for i in status["items"] if i["ok"]]
        if not ok_items:
            summary.update(ok=False, message="公开数据源全部不可用，请检查网络")
    return summary


async def _handoff(
    conn: dict[str, Any], connector: dict[str, Any], lang: str = "zh"
) -> dict[str, Any]:
    """需要登录的连接：签发配对码 + 官方入口，等用户在浏览器里完成。"""
    pairing = await store.issue_pairing_code(connector["id"])
    from ..compat_env import getenv

    base = getenv("MONEYHELPER_PUBLIC_URL").strip() or "http://127.0.0.1:8788"
    bookmarklet = build_bookmarklet(base, pairing["code"], connector["id"], lang)
    return {
        "ok": True,
        "message": "已生成一次性配对码，请到官方页面登录后回传" if lang != "en" else "Pairing code ready; sign in on the official site and send the page back",
        "connector_id": connector["id"],
        "login_url": pairing["login_url"],
        "pairing": pairing,
        "bookmarklet": bookmarklet,
        "ingest_endpoint": f"{base}/api/connect/ingest",
    }


# ---------------------------------------------------------------------------
# 账单收件箱：扫描 → 解析 → 去重 → 入账 → 归档
# ---------------------------------------------------------------------------


def _detect_source(filename: str, head: str) -> str:
    """按文件名与表头猜来源，命中失败走通用解析。"""
    low = filename.lower()
    if "alipay" in low or "支付宝" in filename or "交易时间,交易分类" in head:
        return "alipay"
    if "wechat" in low or "微信" in filename:
        return "wechat"
    return "generic"


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


async def _existing_keys() -> set[tuple[str, float, str]]:
    rows = await db.list_transactions()
    return {(r["date"], round(float(r["amount"]), 2), r["item"]) for r in rows}


async def import_text(
    text: str, source: str = "generic", filename: str = "", account: str = ""
) -> dict[str, Any]:
    """解析一段账单文本并入账：返回 {imported, duplicated, skipped, errors, source}。"""
    parser = get_parser(source)
    result = parser.parse(text)
    for t in result.transactions:
        if t.category in ("", "其他", "未分类"):
            t.category = auto_classify(t.item) or "其他"

    seen = await _existing_keys()
    imported = 0
    duplicated = 0
    for t in result.transactions:
        key = (t.date, round(t.amount, 2), t.item)
        if key in seen:
            duplicated += 1
            continue
        try:
            await db.add_transaction(
                date=t.date,
                item=(t.item or "未命名")[:80],
                category=(t.category or "其他")[:20],
                amount=t.amount,
            )
            seen.add(key)
            imported += 1
        except Exception as exc:  # noqa: BLE001 — 单行失败不阻断整批
            result.errors.append(f"{t.date} {t.item}: {exc}")
    if imported:
        await record_provenance(
            action="connect_import",
            entity_type="transaction",
            entity_id=f"batch:{imported}",
            before=None,
            after={"imported": imported, "duplicated": duplicated, "source": source, "file": filename},
            source="connect",
        )
    return {
        "ok": True,
        "source": source,
        "file": filename,
        "account": account,
        "imported": imported,
        "duplicated": duplicated,
        "skipped": result.skipped,
        "errors": result.errors[:20],
    }


async def scan_import_inbox() -> dict[str, Any]:
    """扫描收件目录并自动入账；处理完的文件移到 done/ 子目录。"""
    root = inbox_dir()
    done = root / "done"
    done.mkdir(parents=True, exist_ok=True)
    files = sorted(
        [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in (".csv", ".txt")],
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        return {"ok": True, "message": "收件目录没有新账单", "files": [], "imported": 0}

    outcomes = []
    total = 0
    for path in files:
        if path.stat().st_size > MAX_INBOX_FILE_BYTES:
            outcomes.append({"file": path.name, "ok": False, "error": "文件超过 20MB"})
            continue
        try:
            text = _read_text(path)
            source = _detect_source(path.name, text[:500])
            res = await import_text(text, source=source, filename=path.name)
            total += int(res.get("imported") or 0)
            outcomes.append(res)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.move(str(path), str(done / f"{stamp}-{path.name}"))
        except Exception as exc:  # noqa: BLE001 — 坏文件留在原地，等用户处理
            outcomes.append({"file": path.name, "ok": False, "error": str(exc)})
    return {
        "ok": True,
        "message": f"处理 {len(files)} 个文件，入账 {total} 笔",
        "files": outcomes,
        "imported": total,
    }


# ---------------------------------------------------------------------------
# 交易意图执行
# ---------------------------------------------------------------------------


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
