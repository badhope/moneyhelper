"""真实外部依赖探针（不依赖模型密钥，可随时跑）。

单测里外部依赖全被 mock 掉了，所以"行情源改版 / 备份恢复在大库上超时"这类问题
只有真连一次才看得见。本脚本只做两件低风险的事：

1. 行情：真实拉一次 A 股快照，核对价格落在合理区间，并打印命中的源
   （网络受限的机器上东财不通会自动落到新浪，这正是需要观测的事实）。
2. 备份：造 5000 条流水 → 导出 → 导入到另一个空库 → 比对条数，
   确认"恢复不丢数据"在真实数据量下成立。

用法（在仓库根）：
    python3 scripts/live_probe.py            # 两项都跑
    python3 scripts/live_probe.py quotes     # 只跑行情
    python3 scripts/live_probe.py backup     # 只跑备份

退出码：0 通过；1 有断言失败；2 参数错误。

注意：备份这一段必须用子进程。`app.db` 在 import 时就把库路径读进模块常量，
同进程内改 `MONEYHELPER_DB_PATH` 不会生效——那样"导出库"和"导入库"其实是同一个库，
测试会假绿。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
FAILURES: list[str] = []

# 子进程末尾 os._exit(0)：aiosqlite 的连接线程在解释器退出阶段会拖住 shutdown
# （实测数据写完、日志已落盘，进程仍不返回）。探针只关心已落盘的 JSON，跳过清理。
_SEED_CODE = """
import asyncio, json, os, time
from app import db

async def main():
    await db.init_db()
    t = time.time()
    for i in range(5000):
        await db.add_transaction("2026-11-01", f"探针{i}", "餐饮", -1)
    data = await db.export_data()
    json.dump({"count": len(data.get("transactions") or []), "seed_s": round(time.time()-t, 1),
               "data": data}, open("__OUT__", "w"), ensure_ascii=False)
asyncio.run(main())
os._exit(0)
"""

_IMPORT_CODE = """
import asyncio, json, os, time
from app import db

async def main():
    data = json.load(open("__INP__"))["data"]
    await db.init_db()
    t = time.time()
    counts = await db.import_backup(data)
    rows = await db.list_transactions()
    json.dump({"count": len(rows), "settings": counts.get("settings", 0),
               "skipped": counts.get("settings_skipped", 0),
               "import_s": round(time.time()-t, 2),
               "first": rows[0]["item"] if rows else None}, open("__OUT__", "w"), ensure_ascii=False)
asyncio.run(main())
os._exit(0)
"""


def ok(msg: str) -> None:
    print(f"  ✓ {msg}", flush=True)


def bad(msg: str) -> None:
    FAILURES.append(msg)
    print(f"  ✗ {msg}", flush=True)


def _run(code: str, db_path: str, **fmt: str) -> dict:
    """跑一个隔离子进程。

    子进程的输出**写文件**而不是 PIPE：这个环境里 capture_output 会让子进程在
    退出阶段挂住（父进程未读完管道时 aiosqlite/日志线程仍在写），实测 60s 不返回；
    重定向到文件后同样的作业 1s 完成。失败时把日志尾部带进异常，便于定位。
    """
    env = dict(os.environ, MONEYHELPER_DB_PATH=db_path, PYTHONPATH=BACKEND)
    log = os.path.join(os.path.dirname(fmt.get("OUT") or db_path), "child.log")
    cmd = [
        sys.executable,
        "-c",
        code.replace("__OUT__", fmt.get("OUT", "")).replace("__INP__", fmt.get("INP", "")),
    ]
    with open(log, "w") as fh:
        proc = subprocess.run(cmd, env=env, stdout=fh, stderr=subprocess.STDOUT, timeout=600)
    if proc.returncode != 0:
        with open(log, encoding="utf-8", errors="replace") as lf:
            tail = lf.read()[-1200:]
        raise RuntimeError(f"子进程失败 (rc={proc.returncode}):\n{tail}")
    with open(fmt.get("OUT") or "") as of:
        return json.load(of)


async def probe_quotes() -> None:
    from app import quotes

    print("\n==> 行情（真实网络）", flush=True)
    for symbol, lo, hi in (("600519", 500.0, 4000.0), ("000001", 3.0, 60.0)):
        t = time.time()
        q = await quotes.quote_now(symbol)
        if not q or not q.get("price"):
            bad(f"{symbol} 未取到价格")
            continue
        price = float(q["price"])
        if not (lo <= price <= hi):
            bad(f"{symbol} 价格 {price} 超出合理区间 {lo}-{hi}（疑似解析错位）")
            continue
        ok(
            f"{symbol} {q.get('name')} {price} ({q.get('change_pct')}%) "
            f"源={q.get('source')} {round(time.time() - t, 1)}s"
        )
    us = await quotes.quote_now("AAPL")
    if us is None:
        ok("AAPL 无数据时返回 None（不编造价格）")
    else:
        ok(f"AAPL 有数据：{json.dumps(us, ensure_ascii=False)[:80]}")


def probe_backup() -> None:
    print("\n==> 备份 / 恢复（5000 条真实数据量，双库隔离）", flush=True)
    work = tempfile.mkdtemp(prefix="mh-probe-")
    src = os.path.join(work, "src.db")
    dst = os.path.join(work, "dst.db")
    dump = os.path.join(work, "dump.json")
    result = os.path.join(work, "restore.json")

    seeded = _run(_SEED_CODE, src, OUT=dump)
    if seeded["count"] != 5000:
        bad(f"导出条数不符：{seeded['count']} != 5000")
        return
    ok(f"导出 {seeded['count']} 条，{seeded['seed_s']}s")

    restored = _run(_IMPORT_CODE, dst, INP=dump, OUT=result)
    if restored["count"] != 5000:
        bad(f"恢复后条数不符：{restored['count']} != 5000")
        return
    if restored["first"] != "探针0":
        bad(f"恢复后首条内容错位：{restored['first']}")
        return
    if restored["settings"] <= 0:
        bad("设置未恢复")
        return
    ok(
        f"导入 {restored['count']} 条 + 设置 {restored['settings']} 项"
        f"（跳过敏感 {restored['skipped']} 项），{restored['import_s']}s"
    )


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which not in ("all", "quotes", "backup"):
        print("用法: live_probe.py [all|quotes|backup]", file=sys.stderr)
        return 2
    sys.path.insert(0, BACKEND)
    if which in ("all", "quotes"):
        asyncio.run(probe_quotes())
    if which in ("all", "backup"):
        probe_backup()
    print()
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：", *FAILURES, sep="\n  - ")
        return 1
    print("真实依赖探针全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
