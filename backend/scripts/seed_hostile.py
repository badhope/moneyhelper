"""敌意 seed：绕过应用层校验，直插「现实世界会有的脏数据」进库。

用途：喂给前端做渲染级容错测试（e2e 敌意截图）。应用层校验挡住的是
「今天新写入的垃圾」，挡不住「历史版本写入的 / CSV 导入的 / 手改库的」——
渲染层必须对它们有容错，不能白屏或崩溃。

数据设计原则：每个字段族都塞满「格式化层最怕的值」：
  - 金额：0、-0、巨数（1e12）、极小正数、负数
  - 文本：空串、超长（10k）、emoji、RTL、零宽字符
  - 日期：空串、1970-01-01、9999-12-31、垃圾串
  - 数量：0.0001、-0.004（后端修复前留过 -0.0 的坑）
  - 进度：saved > target（超 100%）、target=0
  - 净值序列：0 → 巨数 → 0（图表除零高发）

用法：
    python backend/scripts/seed_hostile.py <db_path>
"""

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONEYHELPER_DATA_DIR", str(BACKEND.parent / ".tmp" / "hostile"))

from app import db  # noqa: E402

LONG = "很长的备注" * 1200          # ~10.8k 字符
WEIRD = "😀€µ¶‱þı·ⁿⅧاﻟﻋﺮﺒﻳﺔ​零宽测试"  # emoji / RTL / 零宽字符


async def _prepare(db_path: Path) -> None:
    db._core.DB_PATH = db_path
    await db.close_db()
    await db.init_db()

    conn = sqlite3.connect(str(db_path))
    uid = 0  # LOCAL_USER_ID：单用户模式默认租户

    # ------------------------------------------------------------------
    # transactions：金额与文本的所有边界
    # ------------------------------------------------------------------
    tx_rows = [
        (uid, "2026-01-01", "零金额流水", "测试", 0.0, None, 0),
        (uid, "2026-01-02", "负零", "测试", -0.0, None, 0),
        (uid, "1970-01-01", "纪元日期", "测试", 12.5, None, 0),
        (uid, "9999-12-31", "未来日期", "测试", 8.0, None, 0),
        (uid, "2026-01-03", LONG, "测试", 45.0, None, 0),
        (uid, "2026-01-04", WEIRD, "😀分类", 88.0, None, 0),
        (uid, "2026-01-05", "万亿级流水", "测试", 999_999_999_999.0, None, 0),
        (uid, "2026-01-06", "极小金额", "测试", 0.0001, None, 0),
        (uid, "2026-01-07", "负数流水", "测试", -45.0, None, 0),
    ]
    conn.executemany(
        "INSERT INTO transactions (user_id, date, item, category, amount, owner_id, is_shared)"
        " VALUES (?,?,?,?,?,?,?)",
        tx_rows,
    )

    # ------------------------------------------------------------------
    # positions：数量/成本/现价边界 + 超长名 + 完全正常对照行
    # ------------------------------------------------------------------
    pos_rows = [
        (uid, "600519", "正常持仓对照", "股票", "白酒", 100, 1600.0, 1650.0, "2026-01-01", 5.0),
        (uid, "000001", LONG, "股票", "测试行业", 0.0001, 0.0, 1.5, "", 1e9),
        (uid, "000002", "", "", "", 0, 0.0, 0.0, "2026-13-45", 0.0),
        (uid, "300750", WEIRD, "😀", "😀行业", 1e-4, 0.0, 1e12, "1970-01-01", 1e9),
        (uid, "510300", "负数费用", "ETF", "", 100, 4.0, 3.5, "", -0.0),
    ]
    conn.executemany(
        "INSERT INTO positions (user_id, symbol, name, kind, industry, shares, cost, last, buy_date, fee)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        pos_rows,
    )

    # ------------------------------------------------------------------
    # goals / budgets / subscriptions / debts：进度超 100%、target=0、垃圾日期
    # ------------------------------------------------------------------
    conn.executemany(
        "INSERT INTO goals (user_id, name, target, saved, deadline, created_at) VALUES (?,?,?,?,?,?)",
        [
            (uid, "进度超100%", 100.0, 350.0, "2026-12-31", "2026-01-01"),
            (uid, "target为0", 0.0, 0.0, "1999-09-09", "2026-01-01"),
            (uid, "deadline垃圾", 100.0, 50.0, "not-a-date", "2026-01-01"),
            (uid, LONG, 1e12, 1e11, "9999-12-31", "2026-01-01"),
        ],
    )
    conn.executemany(
        "INSERT INTO budgets (user_id, month, category, amount) VALUES (?,?,?,?)",
        [
            (uid, "2026-01", "餐饮", 0.0),
            (uid, "2026-01", WEIRD, 1e12),
            (uid, "2026-01", LONG, 1e12),
        ],
    )
    conn.executemany(
        "INSERT INTO subscriptions (user_id, name, monthly, note, due_day) VALUES (?,?,?,?,?)",
        [
            (uid, "零宽订阅", 0.0, "", ""),
            (uid, "垃圾 due_day", 33.0, "", "32"),
            (uid, "10k 备注", 33.0, LONG, "31"),
            (uid, "巨数月费", 1e12, "", "31"),
        ],
    )
    conn.executemany(
        "INSERT INTO debts (user_id, name, monthly, balance, rate, due_day) VALUES (?,?,?,?,?,?)",
        [
            (uid, "零利率债", 0.0, 50000.0, 0.0, "28"),
            (uid, "巨率债", 50000.0, 1e12, 1e12, "32"),
            (uid, "负月供", -3000.0, 1e11, -0.0, ""),
        ],
    )

    # ------------------------------------------------------------------
    # net_worth_snapshots：0 → 巨数 → 0 的过山车（图表除零高发）
    # ------------------------------------------------------------------
    snap_rows = []
    for i, (assets, liab) in enumerate([
        (0.0, 0.0), (1e12, 0.0), (0.0, 1e12), (1e6, 1e6), (1e12, 1e11),
    ]):
        snap_rows.append((uid, f"2026-01-0{i+1}", assets, liab, assets - liab, assets, assets * 0.6, "test", ""))
    conn.executemany(
        "INSERT INTO net_worth_snapshots (user_id, date, total_assets, total_liabilities,"
        " net_worth, cash, market_value, source, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        snap_rows,
    )

    # ------------------------------------------------------------------
    # watchlist / dca_plans / paper：名字垃圾 + 极端参数
    # ------------------------------------------------------------------
    conn.executemany(
        "INSERT INTO watchlist (user_id, symbol, name, kind, created_at) VALUES (?,?,?,?,?)",
        [
            (uid, "510300", "", "", "2026-01-01"),
            (uid, "159915", WEIRD, "ETF", "2026-01-01"),
        ],
    )
    conn.executemany(
        "INSERT INTO dca_plans (user_id, id, symbol, name, amount, frequency, day, start_date, note, active, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (uid, 1, "510300", "", 0.0, "monthly", "", "", "", 1, ""),
            (uid, 2, "159915", WEIRD, 1e12, "weekly", "99", "1970-01-01", LONG, 1, ""),
        ],
    )
    conn.executemany(
        "INSERT INTO paper_accounts (user_id, account_id, name, initial_cash, created_at) VALUES (?,?,?,?,?)",
        [
            (uid, "hostile-a", "零本金账户", 0.0, ""),
            (uid, "hostile-b", "巨本金", 1e12, ""),
        ],
    )
    conn.executemany(
        "INSERT INTO paper_trades (id, user_id, account_id, date, symbol, name, side, price, shares, fee, amount)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, uid, "hostile-a", "2026-01-05", "600519", "零本金买入", "buy", 0.0, 0.0, 0.0, 0.0),
            (2, uid, "hostile-b", "2026-01-06", "000001", "巨价买入", "buy", 1e12, 1e9, 1e11, 1e21),
        ],
    )

    conn.commit()
    await db.close_db()
    print("hostile seed OK:", db_path)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BACKEND.parent / ".tmp" / "hostile" / "hostile.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    asyncio.run(_prepare(target))
    # aiosqlite 的 worker 线程在 Windows 上偶尔不随 close_db 退出，
    # threading._shutdown 会一直等——数据已 commit 落盘，直接强退。
    os._exit(0)
