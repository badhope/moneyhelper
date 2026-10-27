"""Moneyhelper 命令行入口（M4.1 最小可用形态）。

设计要点：**直调 core，零网络**。同一条命令在本地和远程两种形态下都能用——
本态直接操作本地库（不需要起服务），远程形态走 HTTP API（`--url/--token`）。
这样 CLI 不会变成「又一个只能连服务器的薄客户端」。

用法：

    moneyhelper add "午饭 35 元"            # 一句话记账（规则解析，不花 token）
    moneyhelper ls                          # 最近流水
    moneyhelper ls --month 2026-09          # 指定月份
    moneyhelper report                      # 现金流/收支概览
    moneyhelper balance                     # 账户总览（持仓 + 净资产）
    moneyhelper ask "这个月花多了吗"        # 走问答管线（离线确定性模板）
    moneyhelper serve --port 8788           # 起本地服务

全局参数：

    --db PATH     指定数据库文件（默认 backend/data/wealth.db）
    --json        输出 JSON，便于管道处理
    --url / --token  远程模式（走 HTTP，不碰本地库）

退出码：0 成功；1 参数或数据错误；2 解析失败（记账）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


def _die(msg: str, code: int = 1) -> None:
    print(f"错误：{msg}", file=sys.stderr)
    raise SystemExit(code)


def _fmt_amount(v: Any) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{n:,.2f}"


def _out(payload: Any, as_json: bool, text: str) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(text)


def _prepare_db(db_path: str | None) -> None:
    """把 MONEYHELPER_DB_PATH 指到目标库，然后初始化连接。

    必须在任何 app.* 导入之前设置：app.db._core 在导入时就读这个环境变量。
    """
    if db_path:
        resolved = Path(db_path).expanduser().resolve()
        os.environ["MONEYHELPER_DB_PATH"] = str(resolved)


async def _remote(method: str, url: str, token: str, path: str, body: dict | None) -> Any:
    """远程模式：走 HTTP API（与前端同一套端点）。"""
    import httpx

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(base_url=url.rstrip("/"), timeout=60.0) as client:
        if method == "GET":
            resp = await client.get(path, headers=headers)
        else:
            resp = await client.post(path, headers=headers, json=body or {})
    if resp.status_code >= 400:
        _die(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------


async def cmd_add(args: argparse.Namespace) -> int:
    if args.url:
        data = await _remote("POST", args.url, args.token, "/api/nl-add", {"text": args.text})
        if not data.get("ok"):
            _die(str(data.get("error") or "记账失败"), 2)
        _out(data, args.json, f"已记账：{data.get('date')} {data.get('item')} "
                              f"{_fmt_amount(data.get('amount'))} 元（{data.get('category')}）")
        return 0

    from app import db, nlparse

    parsed = nlparse.parse(args.text)
    if parsed is None:
        _die("无法从这句话里解析出金额。试试「昨天打车 32 元」这类格式。", 2)
    await db.init_db()
    try:
        await db.add_transaction(
            parsed["date"], parsed["item"], parsed["category"], parsed["amount"]
        )
    finally:
        await db.close_db()
    _out(
        parsed,
        args.json,
        f"已记账：{parsed['date']} {parsed['item']} "
        f"{_fmt_amount(parsed['amount'])} 元（{parsed['category']}）",
    )
    return 0


async def cmd_ls(args: argparse.Namespace) -> int:
    if args.url:
        data = await _remote("GET", args.url, args.token, "/api/transactions", None)
        rows = data.get("transactions", [])
    else:
        from app import db

        await db.init_db()
        try:
            rows = await db.list_transactions()
        finally:
            await db.close_db()

    if args.month:
        rows = [r for r in rows if str(r.get("date", "")).startswith(args.month)]
    rows = rows[: args.limit]

    lines = [
        f"{r.get('date')}  {str(r.get('item') or '')[:14]:<14} "
        f"{r.get('category') or ''!s:<6} {_fmt_amount(r.get('amount'))}"
        for r in rows
    ]
    _out(rows, args.json, "\n".join(lines) if lines else "（没有记录）")
    return 0


async def cmd_report(args: argparse.Namespace) -> int:
    if args.url:
        data = await _remote("GET", args.url, args.token, "/api/dashboard", None)
        led = data.get("cashflow", {})
        text = (
            f"本月收入 {_fmt_amount(led.get('income'))} 元，"
            f"支出 {_fmt_amount(led.get('expense'))} 元，"
            f"结余 {_fmt_amount(led.get('net'))} 元"
        )
        _out(led, args.json, text)
        return 0

    from app import analysis, db

    await db.init_db()
    try:
        dash = await analysis.collect_dashboard()
    finally:
        await db.close_db()
    led = dash.get("cashflow", {})
    text = (
        f"本月收入 {_fmt_amount(led.get('income'))} 元，"
        f"支出 {_fmt_amount(led.get('expense'))} 元，"
        f"结余 {_fmt_amount(led.get('net'))} 元"
    )
    if args.json:
        _out(dash, True, text)
    else:
        print(text)
        flags = dash.get("flags") or []
        if flags:
            print("\n需关注：")
            for f in flags:
                print(f"  - {f.get('text') or f.get('message') or f}")
    return 0


async def cmd_balance(args: argparse.Namespace) -> int:
    from app import analysis, db

    await db.init_db()
    try:
        if args.live:
            dash = await analysis.collect_dashboard()
        else:
            # 默认走快照价：CLI 的定位是"离网也能用"，实时行情由 --live 显式开启。
            # collect_dashboard 会串行拉行情（东财/新浪/指数），离线环境要等超时。
            from app.quotes import snapshot_only

            with snapshot_only():
                dash = await analysis.collect_dashboard()
    finally:
        await db.close_db()
    totals = dash.get("totals", {})
    text = (
        f"组合总市值 {_fmt_amount(totals.get('total_market_value'))} 元，"
        f"浮动盈亏 {_fmt_amount(totals.get('total_pnl'))} 元"
    )
    _out(totals, args.json, text)
    return 0


async def cmd_ask(args: argparse.Namespace) -> int:
    if args.url:
        data = await _remote("POST", args.url, args.token, "/api/ask", {"question": args.question})
        _out(data, args.json, str(data.get("answer") or ""))
        return 0

    from app import db, service

    await db.init_db()

    async def _noop(_ev: dict) -> None:
        return None

    try:
        result = await service.run_question(args.question, _noop)
    finally:
        await db.close_db()
    _out(result, args.json, str(result.get("answer") or ""))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info")
    return 0


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="moneyhelper",
        description="Moneyhelper —— 一句话记账、问一句、看报告。默认直连本地库（零网络）。",
    )
    p.add_argument("--db", help="数据库文件路径（默认 backend/data/wealth.db）")
    p.add_argument("--json", action="store_true", help="输出 JSON，便于管道处理")
    p.add_argument("--url", help="远程模式：服务地址，如 http://127.0.0.1:8788")
    p.add_argument("--token", default="", help="远程模式的访问口令")

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("add", help="一句话记账")
    sp.add_argument("text", help='例如："午饭 35 元"、"昨天打车 32 元"')
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("ls", help="列出流水")
    sp.add_argument("--month", help="只看某月，格式 YYYY-MM")
    sp.add_argument("--limit", type=int, default=20, help="最多显示条数（默认 20）")
    sp.set_defaults(func=cmd_ls)

    sp = sub.add_parser("report", help="本月收支概览")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("balance", help="组合与净资产")
    sp.add_argument("--live", action="store_true", help="拉实时行情（默认用本地快照价）")
    sp.set_defaults(func=cmd_balance)

    sp = sub.add_parser("ask", help="问一句（走问答管线）")
    sp.add_argument("question")
    sp.set_defaults(func=cmd_ask)

    sp = sub.add_parser("serve", help="启动本地服务")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8788)
    sp.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _prepare_db(args.db)
    # CLI 是短进程：禁用读连接池，避免 aiosqlite 连接绑定在已关闭的事件循环上
    from app import db as _db_mod

    _db_mod.set_read_pool(False)
    return asyncio.run(_run_and_close(args))


async def _run_and_close(args) -> int:
    """跑一次命令并在同一个事件循环里关闭数据库连接。

    为什么必须关：aiosqlite 的连接/线程绑定在创建它的 loop 上。
    CLI 每次调用都 asyncio.run() 建新 loop，若不关旧连接，
    同一进程里连续跑两次命令（测试、脚本、REPL）会挂死在新 loop 上。
    """
    try:
        return await args.func(args)
    finally:
        try:
            from app import db

            await db.close_db()
        except Exception:  # noqa: BLE001 — 关闭失败不改变命令结果
            pass


if __name__ == "__main__":
    raise SystemExit(main())
