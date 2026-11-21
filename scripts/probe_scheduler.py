"""定时任务面验收：晨报生成/归档、订阅提醒去重、调度器注册。

定时任务是"不点按钮也会跑"的那部分，单测通常只测单个函数；这里把真实入口
（`generate_report` / `_check_subscriptions_due` / `start`）按调度器的方式跑，
看的是归档落库、每月去重、job 注册三件事。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


async def main() -> int:
    from app import db, scheduler

    await db.init_db()
    rows: list[dict] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        rows.append({"case": name, "ok": ok, "detail": detail})

    # 1) 空库：定时晨报必须 skip，不能产出噪音
    empty = await scheduler.generate_report()
    case("空库晨报跳过", empty.get("skipped") is True, str(empty.get("reason")))

    # 2) 造数据（持仓 + 流水 + 一条 3 天后扣款的订阅）
    await db.add_position({"symbol": "600519", "name": "贵州茅台", "shares": 100, "cost": 1500, "last": 1485, "kind": "股票"})
    await db.add_transaction("2026-11-20", "午饭", "餐饮", -35)
    due = (datetime.now().astimezone().date() + timedelta(days=3)).day
    await db.add_subscription({"name": "视频会员", "monthly": 25, "due_day": str(due), "note": "自动续费"})

    # 3) 晨报：有数据时必须成文并归档到 cron 线程
    first = await scheduler.generate_report()
    runs = await db.list_runs(thread_id="cron", limit=10)
    case("晨报成文", bool(first.get("answer")) and not first.get("skipped"), f"{len(first.get('answer') or '')} 字")
    case("晨报归档", any(r.get("thread_id") == "cron" for r in runs), f"{len(runs)} 条")

    # 4) 订阅提醒：连跑两次，本月只能有一条（去重靠 marker）
    await scheduler._check_subscriptions_due()
    await scheduler._check_subscriptions_due()
    mem = await db.list_memory()
    due_rows = [m for m in mem if "视频会员" in str(m.get("content") or "")]
    case("订阅提醒写入", bool(due_rows), f"{len(due_rows)} 条")
    case("订阅提醒每月去重", len(due_rows) == 1, f"{len(due_rows)} 条")

    # 5) 真启动调度器：4 类 job 都要注册上，报告时间按设置落
    await db.set_setting("report_time", "07:30")
    await scheduler.start()
    jobs = scheduler._sched.get_jobs() if scheduler._sched else []
    ids = sorted(j.id for j in jobs)
    case("调度器启动", scheduler._sched is not None and scheduler._sched.running, f"{len(jobs)} 个 job")
    case("job 注册齐全", {"morning_report", "subs_due_check", "connect_auto_sync", "connect_inbox_scan", "month_end_close"} <= set(ids), str(ids))
    trig = next((str(j.trigger) for j in jobs if j.id == "morning_report"), "")
    case("晨报时间生效", "hour='7'" in trig and "minute='30'" in trig, trig)
    await scheduler.stop()

    for r in rows:
        print(("✓" if r["ok"] else "✗"), r["case"], "—", r["detail"], flush=True)
    bad = [r for r in rows if not r["ok"]]
    print(f"\n通过 {len(rows) - len(bad)}/{len(rows)}")
    (ROOT / ".tmp" / "scheduler_probe.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
