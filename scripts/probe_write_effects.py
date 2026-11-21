"""写工具效果验收：直接调实现 + 查落库结果。

为什么不用模型跑：agent 只暴露 40 个只读工具，写工具走「确认后执行」的
独立通道（tool_policy 判 ASK）。让模型去调它们既不符合产品设计，也测不出
真正的风险点——写工具的风险是"说成功了但库里没变"。所以这里逐个直接调
impl，再用 db 反查：到底写没写进去、写成了什么。

隔离：必须用独立库（MONEYHELPER_DB_PATH 指向 .tmp 下的文件）。脚本开头
强制校验路径里带 .tmp，避免手滑跑到真实账本上。

用法：
    PYTHONPATH=backend python3 scripts/probe_write_effects.py
    PYTHONPATH=backend python3 scripts/probe_write_effects.py --only paper
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))


async def case_add_watchlist(impl):
    return await impl({"symbol": "600519", "kind": "股票"})


async def verify_add_watchlist():
    from app import db

    rows = await db.list_watchlist()
    assert any(r["symbol"] == "600519" for r in rows), "自选里没有 600519"


async def case_remove_watchlist(impl):
    return await impl({"symbol": "600519"})


async def verify_remove_watchlist():
    from app import db

    rows = await db.list_watchlist()
    assert not any(r["symbol"] == "600519" for r in rows), "自选里还有 600519"


async def case_record_tx(impl):
    return await impl({"text": "午饭花了 35 元，微信支付"})


async def verify_record_tx():
    from app import db

    rows = await db.list_transactions(limit=200)
    # 支出按负数记账（-35），断言绝对值，避免把符号当 bug
    assert any(abs(abs(float(r.get("amount") or 0)) - 35) < 0.01 for r in rows), "没找到 35 元流水"


async def case_record_position(impl):
    return await impl({"symbol": "600519", "name": "贵州茅台", "shares": 100, "cost": 1500, "last": 1500})


async def verify_record_position():
    from app import db

    rows = await db.list_positions()
    hit = [r for r in rows if r["symbol"] == "600519"]
    assert hit and float(hit[0]["shares"]) == 100, f"持仓不对：{hit}"


async def case_sell_position(impl):
    return await impl({"symbol": "600519", "shares": 50})


async def verify_sell_position():
    from app import db

    rows = await db.list_positions()
    hit = [r for r in rows if r["symbol"] == "600519"]
    assert hit and float(hit[0]["shares"]) == 50, f"减仓后股数不对：{hit}"


async def case_memory(impl):
    return await impl({"content": "明年计划买房，首付预算 30 万"})


async def verify_memory():
    from app import db

    rows = await db.list_memory()
    assert any("买房" in str(r.get("content") or "") for r in rows), "长期记忆没写入"


async def case_setting(impl):
    return await impl({"key": "color_scheme", "value": "us"})


async def verify_setting():
    from app import db

    s = await db.get_settings()
    assert str(s.get("color_scheme")) == "us", f"设置没变：{s.get('color_scheme')}"


async def case_paper_open(impl):
    return await impl({"name": "验收小王", "initial_cash": 100000})


async def verify_paper_open():
    from app import db

    rows = await db.list_accounts()
    assert any("验收小王" in str(r.get("name") or "") for r in rows), "模拟账户没建出来"


async def case_paper_trade(impl):
    from app import db

    rows = await db.list_accounts()
    acc = next(r for r in rows if "验收小王" in str(r.get("name") or ""))
    # list_accounts 行里的主键叫 account_id，不是 id
    return await impl({"account_id": acc["account_id"], "symbol": "000001", "side": "buy", "price": 12, "shares": 100})


async def verify_paper_trade():
    from app import db

    rows = await db.list_accounts()
    acc = next(r for r in rows if "验收小王" in str(r.get("name") or ""))
    trades = await db.get_trades(acc["account_id"])
    assert any(t.get("symbol") == "000001" for t in trades), f"模拟盘没成交记录：{trades}"


async def case_backup(impl):
    return await impl({"lang": "zh"})


async def verify_backup():
    # 备份返回 {"answer","passphrase"}：answer 只含文件名，口令单传。这里验三件事：
    # 文件真的落在 BACKUP_DIR、内容真的是密文、用口令能解回本库刚写的持仓。
    import json
    from pathlib import Path

    from app import backup
    from app.tools_system import BACKUP_DIR

    out = case_backup.last
    assert isinstance(out, dict) and out.get("passphrase"), f"备份没给口令：{out}"
    files = sorted(Path(BACKUP_DIR).glob("moneyhelper-backup-*.json"))
    assert files, f"{BACKUP_DIR} 下没有备份文件"
    payload = json.loads(files[-1].read_text(encoding="utf-8"))
    assert payload.get("encrypted") is True, "备份没加密"
    assert "600519" not in files[-1].read_text(encoding="utf-8"), "密文里出现了明文标的"
    data = backup.decrypt_export(payload, out["passphrase"])
    assert "600519" in json.dumps(data, ensure_ascii=False), "解密后找不到持仓 600519"


async def case_preview(impl):
    return await impl({"symbol": "000001", "side": "buy", "quantity": 10, "limit_price": 12})


async def verify_preview():
    import json

    out = json.loads(case_preview.last)
    assert out.get("ok") is True, f"预检没放行：{out}"
    assert out.get("confirmation_token"), "预检放行却没签确认令牌"
    assert out.get("guardrails", {}).get("trading_enabled") is True, "开关没读到"
    case_preview.token = out["confirmation_token"]


async def case_submit(impl):
    # 故意不带 token：必须停在 confirmation 阶段，不能报出去
    return await impl({"symbol": "000001", "side": "buy", "quantity": 10, "limit_price": 12})


async def verify_submit():
    import json

    out = json.loads(case_submit.last)
    assert out.get("ok") is False and out.get("stage") == "confirmation", f"无 token 竟未拒绝：{out}"


async def case_submit_token(impl):
    return await impl(
        {
            "symbol": "000001",
            "side": "buy",
            "quantity": 10,
            "limit_price": 12,
            "confirmation_token": case_preview.token,
        }
    )


async def verify_submit_token():
    import json

    out = json.loads(case_submit_token.last)
    assert out.get("stage") != "confirmation", f"合法 token 被拒：{out}"


async def case_submit_mismatch(impl):
    # 为 000001 签发一枚 token，再拿去报 600000：token 绑定标的，必须拒绝
    import json

    from app.tool_registry import TOOL_IMPL

    prev = json.loads(
        await TOOL_IMPL["broker_preview_order"](
            {"symbol": "000001", "side": "buy", "quantity": 10, "limit_price": 12}
        )
    )
    assert prev.get("confirmation_token"), f"换标的预检没签 token：{prev}"
    return await impl(
        {
            "symbol": "600000",
            "side": "buy",
            "quantity": 10,
            "limit_price": 10,
            "confirmation_token": prev["confirmation_token"],
        }
    )


async def verify_submit_mismatch():
    import json

    out = json.loads(case_submit_mismatch.last)
    assert out.get("ok") is False and out.get("stage") == "confirmation", f"token 换标的竟放行：{out}"


async def case_conditional(impl):
    return await impl(
        {
            "symbol": "600519",
            "side": "sell",
            "trigger_type": "price_above",
            "trigger_value": 1600,
            "price": 1600,
            "shares": 100,
            "mode": "paper",
        }
    )


async def verify_conditional():
    from app import db

    rows = await db.list_conditionals()
    assert rows, "条件单没落库"


async def case_connect_order(impl):
    return await impl({"symbol": "600519", "side": "buy", "price": 1500, "shares": 100, "mode": "paper"})


async def verify_connect_order():
    from app import connect

    rows = await connect.list_intents(limit=50)
    assert rows, "交易意图没落库"


async def case_connect_sync(impl):
    return await impl({"connector_id": "eastmoney_quote", "sync": True})


async def verify_connect_sync():
    from app import connect

    rows = await connect.list_connections()
    assert any(r.get("connector_id") == "eastmoney_quote" for r in rows), f"连接没建立：{[r.get('connector_id') for r in rows]}"


async def case_import_holdings(impl):
    csv_text = "代码,名称,数量,成本价\n000001,平安银行,200,12.5\n"
    return await impl({"content": csv_text, "apply": True, "file_name": "holdings.csv"})


async def verify_import_holdings():
    from app import db

    rows = await db.list_positions()
    assert any(r["symbol"] == "000001" for r in rows), f"导入没合并进持仓：{[r['symbol'] for r in rows]}"


async def case_invoice(impl):
    text = (
        "发票代码 011002100311 发票号码 12345678 开票日期 2026-11-20 "
        "价税合计 1060.00 元 购买方 某某科技有限公司 销售方 某某商贸有限公司"
    )
    return await impl({"text": text, "file_name": "invoice.txt"})


async def verify_invoice():
    from app import db

    rows = await db.list_invoices()
    assert rows, "发票没归档"


async def case_categorize(impl):
    return await impl(
        {
            "rows": [
                {"item": "美团外卖", "amount": 45},
                {"item": "滴滴出行", "amount": 30},
                {"item": "星巴克", "amount": 38},
                {"item": "房租", "amount": 3000},
            ]
        }
    )


async def verify_categorize():
    out = case_categorize.last
    assert out and ("分类" in out or "category" in out.lower()), f"没有分类结果：{out[:120]}"


async def case_morning(impl):
    return await impl({"lang": "zh"})


async def verify_morning():
    out = case_morning.last
    assert out and len(out) > 20, "晨报没产出内容"


# (短名, 中文说明, 执行, 校验, 依赖的前置短名)
CASES = [
    ("watch_add", "加自选", case_add_watchlist, verify_add_watchlist, ()),
    ("watch_remove", "删自选", case_remove_watchlist, verify_remove_watchlist, ("watch_add",)),
    ("record_tx", "一句话记账", case_record_tx, verify_record_tx, ()),
    ("record_pos", "记买入持仓", case_record_position, verify_record_position, ()),
    ("sell_pos", "卖出减仓", case_sell_position, verify_sell_position, ("record_pos",)),
    ("memory", "写长期记忆", case_memory, verify_memory, ()),
    ("setting", "改设置", case_setting, verify_setting, ()),
    ("paper_open", "模拟盘开户", case_paper_open, verify_paper_open, ()),
    ("paper_trade", "模拟盘下单", case_paper_trade, verify_paper_trade, ("paper_open",)),
    ("backup", "生成加密备份", case_backup, verify_backup, ()),
    ("broker_preview", "券商下单预检", case_preview, verify_preview, ()),
    ("broker_submit", "无令牌报单必须拒绝", case_submit, verify_submit, ("broker_preview",)),
    ("broker_submit_token", "持令牌报单", case_submit_token, verify_submit_token, ("broker_preview",)),
    ("broker_submit_mismatch", "令牌换标的必须拒绝", case_submit_mismatch, verify_submit_mismatch, ("broker_preview",)),
    ("conditional", "条件单", case_conditional, verify_conditional, ()),
    ("connect_order", "交易意图", case_connect_order, verify_connect_order, ()),
    ("connect_sync", "连接并同步行情", case_connect_sync, verify_connect_sync, ()),
    ("holdings_import", "券商持仓导入", case_import_holdings, verify_import_holdings, ()),
    ("invoice", "发票归档", case_invoice, verify_invoice, ()),
    ("categorize", "批量分类", case_categorize, verify_categorize, ()),
    ("morning", "晨报生成", case_morning, verify_morning, ()),
]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    db_path = os.getenv("MONEYHELPER_DB_PATH", "")
    if ".tmp" not in db_path:
        print("拒绝执行：MONEYHELPER_DB_PATH 必须指向 .tmp 下的隔离库", file=sys.stderr)
        return 2

    from app import db
    from app.tool_registry import TOOL_IMPL

    await db.init_db()
    targets = [x for x in args.only.split(",") if x] or [c[0] for c in CASES]
    order = {c[0]: c for c in CASES}
    done: list[str] = []
    rows = []

    for name in targets:
        short, label, run, verify, _deps = order[name]
        impl = TOOL_IMPL.get(_impl_name(short, TOOL_IMPL))
        if impl is None:
            rows.append({"case": short, "ok": False, "why": "找不到实现"})
            print(f"✗ {label} 找不到实现", flush=True)
            continue
        t = time.time()
        ok, why, out = True, "", ""
        try:
            res = await run(impl)
            if isinstance(res, tuple):
                out, _extra = res
            else:
                out = res
            setattr(run, "last", out)
            await verify()
        except Exception as exc:  # noqa: BLE001 — 验收要如实记录每条失败原因
            ok, why = False, f"{type(exc).__name__}: {exc}"[:160]
        rows.append({"case": short, "label": label, "ok": ok, "why": why, "ms": int((time.time() - t) * 1000), "out": str(out)[:200]})
        done.append(short)
        mark = "✓" if ok else "✗"
        print(f"{mark} {label}({short}) {rows[-1]['ms']}ms {why}", flush=True)

    import json

    outp = os.path.join(ROOT, ".tmp", f"write_effects.{int(time.time())}.json")
    with open(outp, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
    bad = [r for r in rows if not r["ok"]]
    print(f"\n通过 {len(rows) - len(bad)}/{len(rows)}；写入 {outp}", flush=True)
    return 1 if bad else 0


def _impl_name(short: str, impl_map: dict) -> str:
    return {
        "watch_add": "add_to_watchlist",
        "watch_remove": "remove_from_watchlist",
        "record_tx": "record_transaction",
        "record_pos": "record_position",
        "sell_pos": "sell_position",
        "memory": "save_user_memory",
        "setting": "set_setting",
        "paper_open": "paper_open",
        "paper_trade": "paper_trade",
        "backup": "backup_now",
        "broker_preview": "broker_preview_order",
        "broker_submit": "broker_submit_order",
        "broker_submit_token": "broker_submit_order",
        "broker_submit_mismatch": "broker_submit_order",
        "conditional": "conditional_order",
        "connect_order": "connect_order",
        "connect_sync": "connect_sync",
        "holdings_import": "import_brokerage_holdings",
        "invoice": "parse_invoice",
        "categorize": "categorize_bills",
        "morning": "trigger_morning_report",
    }[short]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
