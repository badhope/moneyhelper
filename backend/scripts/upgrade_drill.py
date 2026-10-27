"""旧库升级演练：用「旧版 schema」造一个带数据的库，再用当前代码打开。

验证：
1. 多租户迁移后，原有数据一条不少
2. 同一 symbol 的持仓、同一 name 的目标能按租户共存
3. 旧路径（backend/app/data）的库会被搬到新位置
4. 迁移可重跑（幂等）

用法（在 backend/ 下）：
    python scripts/upgrade_drill.py
退出码 0 = 全部通过。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

# 旧版 schema（2.2.0 及更早）：无 user_id，业务字段作全局主键
OLD_SCHEMA = """
CREATE TABLE positions (
    symbol TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT '股票',
    industry TEXT NOT NULL DEFAULT '其他', shares REAL NOT NULL, cost REAL NOT NULL,
    last REAL NOT NULL, buy_date TEXT, fee REAL NOT NULL DEFAULT 0
);
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, item TEXT NOT NULL,
    category TEXT NOT NULL, amount REAL NOT NULL
);
CREATE TABLE subscriptions (
    name TEXT PRIMARY KEY, monthly REAL NOT NULL, note TEXT NOT NULL DEFAULT '',
    due_day TEXT NOT NULL DEFAULT ''
);
CREATE TABLE debts (
    name TEXT PRIMARY KEY, monthly REAL NOT NULL, balance REAL NOT NULL,
    rate REAL NOT NULL, due_day TEXT NOT NULL DEFAULT ''
);
CREATE TABLE goals (
    name TEXT PRIMARY KEY, target REAL NOT NULL, saved REAL NOT NULL DEFAULT 0,
    deadline TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE watchlist (
    symbol TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '股票', created_at TEXT NOT NULL
);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL DEFAULT '新会话', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL, question TEXT NOT NULL,
    answer TEXT NOT NULL, level TEXT NOT NULL DEFAULT '', flags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE user_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'fact', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE budgets (month TEXT NOT NULL, category TEXT NOT NULL, amount REAL NOT NULL, PRIMARY KEY(month, category));
CREATE TABLE members (
    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'member',
    avatar_color TEXT NOT NULL DEFAULT '#b8891f', created_at TEXT NOT NULL
);
CREATE TABLE member_loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_member_id INTEGER NOT NULL REFERENCES members(id),
    to_member_id INTEGER NOT NULL REFERENCES members(id),
    amount REAL NOT NULL, currency TEXT NOT NULL DEFAULT 'CNY',
    note TEXT NOT NULL DEFAULT '', settled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, settled_at TEXT
);
CREATE TABLE conversation_summary (
    thread_id TEXT PRIMARY KEY, summary TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'llm', covered_to INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE provenance_log (
    id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, action TEXT NOT NULL,
    entity_type TEXT NOT NULL, entity_id TEXT, before_json TEXT, after_json TEXT,
    source TEXT NOT NULL DEFAULT 'api', username TEXT NOT NULL DEFAULT 'system', metadata_json TEXT
);
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, action TEXT NOT NULL,
    method TEXT NOT NULL, path TEXT NOT NULL, status INTEGER NOT NULL,
    actor TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '', duration_ms INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, kind TEXT NOT NULL,
    size INTEGER NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE dept_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, report_id TEXT UNIQUE NOT NULL, question TEXT NOT NULL,
    dispatch TEXT NOT NULL DEFAULT '', verdict TEXT NOT NULL DEFAULT '', report TEXT NOT NULL DEFAULT '',
    orders_json TEXT NOT NULL DEFAULT '[]', conflicts_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending', decision_note TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE pending_actions (
    token TEXT PRIMARY KEY, tool_name TEXT NOT NULL, args TEXT NOT NULL, summary TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'zh', status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE undo_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT NOT NULL, entity_id TEXT NOT NULL,
    before_json TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
    consumed_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL, display_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'user', disabled INTEGER NOT NULL DEFAULT 0,
    last_login TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE refunds_placeholder (x TEXT);
"""

# 旧库里的真实数据（迁移后必须原样存在）
SEED = """
INSERT INTO positions(symbol,name,kind,industry,shares,cost,last) VALUES('600519','贵州茅台','股票','白酒',100,1680,1521);
INSERT INTO positions(symbol,name,kind,industry,shares,cost,last) VALUES('510300','沪深300ETF','ETF','宽基指数',8000,3.85,4.1);
INSERT INTO transactions(date,item,category,amount) VALUES('2026-10-01','旧账咖啡','餐饮',-28);
INSERT INTO transactions(date,item,category,amount) VALUES('2026-10-02','旧账工资','收入',24800);
INSERT INTO subscriptions(name,monthly,note,due_day) VALUES('Netflix',45,'4K','5');
INSERT INTO debts(name,monthly,balance,rate) VALUES('房贷',3500,500000,0.045);
INSERT INTO goals(name,target,saved,deadline,created_at) VALUES('买房',100000,20000,'2027-06','2026-01-01T00:00:00');
INSERT INTO watchlist(symbol,name,kind,created_at) VALUES('000858','五粮液','股票','2026-01-01T00:00:00');
INSERT INTO user_memory(content,kind,created_at,updated_at) VALUES('旧记忆：每月10号还房贷','fact','2026-01-01T00:00:00','2026-01-01T00:00:00');
INSERT INTO sessions(thread_id,title,created_at,updated_at) VALUES('old-thread','旧会话','2026-01-01T00:00:00','2026-01-01T00:00:00');
INSERT INTO runs(thread_id,question,answer,level,flags_json,created_at) VALUES('old-thread','旧问题','旧回答','L1 洞察','[]','2026-01-01T00:00:00');
INSERT INTO budgets(month,category,amount) VALUES('2026-10','餐饮',2000);
INSERT INTO members(username,display_name,role,avatar_color,created_at) VALUES('ming','小明','owner','#b8891f','2026-01-01');
INSERT INTO member_loans(from_member_id,to_member_id,amount,note,settled,created_at) VALUES(1,1,100,'旧借贷',0,'2026-01-01');
INSERT INTO conversation_summary(thread_id,summary,source,covered_to,updated_at) VALUES('old-thread','旧摘要','llm',1,'2026-01-01');
INSERT INTO settings(key,value) VALUES('monthly_income','24800');
INSERT INTO settings(key,value) VALUES('data_note','seed');
"""

EXPECT = {
    "positions": 2,
    "transactions": 2,
    "subscriptions": 1,
    "debts": 1,
    "goals": 1,
    "watchlist": 1,
    "user_memory": 1,
    "runs": 1,
    "sessions": 1,
    "members": 1,
    "member_loans": 1,
    "budgets": 1,
}


def build_legacy_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.executescript(SEED)
    conn.commit()
    conn.close()


def counts(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(db)
    out = {}
    for t in EXPECT:
        try:
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.Error:
            out[t] = -1
    conn.close()
    return out


async def run_migration(db_path: Path) -> dict[str, int]:
    """在子进程里用当前代码打开旧库（避免污染本进程的模块状态）。"""
    code = f"""
import asyncio, os, json
os.environ["MONEYHELPER_DB_PATH"] = r"{db_path}"
from app import db
async def main():
    await db.init_db()
    out = {{}}
    for t in {list(EXPECT)!r}:
        rows = await db.fetch_all(f"SELECT COUNT(*) AS n FROM {{t}}")
        out[t] = rows[0]["n"] if rows else 0
    # 复合主键验证：两个租户写同一 symbol
    conn = await db._conn()
    await conn.execute("INSERT INTO positions(user_id,symbol,name,shares,cost,last) VALUES(1,'600519','A',1,1,1)")
    await conn.execute("INSERT INTO positions(user_id,symbol,name,shares,cost,last) VALUES(2,'600519','B',2,2,2)")
    await conn.commit()
    out["_coexist"] = (await db.fetch_all("SELECT COUNT(*) AS n FROM positions WHERE symbol='600519'"))[0]["n"]
    print("RESULT" + json.dumps(out), flush=True)
asyncio.run(main())
import os as _os
_os._exit(0)
"""
    env = {**os.environ, "MONEYHELPER_DB_PATH": str(db_path)}
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=180,
    )
    line = next((ln for ln in (proc.stdout or "").splitlines() if ln.startswith("RESULT")), "")
    if not line:
        raise RuntimeError(f"迁移子进程失败:\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}")
    import json as _json
    return _json.loads(line[len("RESULT"):])


def await_second_start(db_path: Path, baseline: dict[str, int]) -> dict[str, int]:
    """第二次启动只统计条数，不写入任何数据。"""
    import json as _json

    code = f"""
import asyncio, os, json
os.environ["MONEYHELPER_DB_PATH"] = r"{db_path}"
from app import db
async def main():
    await db.init_db()
    out = {{}}
    for t in {list(EXPECT)!r}:
        rows = await db.fetch_all(f"SELECT COUNT(*) AS n FROM {{t}}")
        out[t] = rows[0]["n"] if rows else 0
    print("RESULT" + json.dumps(out), flush=True)
asyncio.run(main())
os._exit(0)
"""
    env = {**os.environ, "MONEYHELPER_DB_PATH": str(db_path)}
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=str(BACKEND),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=180,
    )
    line = next((ln for ln in (proc.stdout or "").splitlines() if ln.startswith("RESULT")), "")
    if not line:
        raise RuntimeError("二次启动失败: " + (proc.stderr or "")[-1200:])
    return _json.loads(line[len("RESULT"):])


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    return ok


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="xm-upgrade-"))
    failures = 0
    try:
        # --- 场景 1：旧库就地升级（同路径） ---
        print("[1] 旧库就地升级（无 user_id -> 多租户）")
        db_path = tmp / "legacy" / "wealth.db"
        build_legacy_db(db_path)
        migrated = asyncio.run(run_migration(db_path))
        # 纯启动基线（不含 run_migration 额外插入的共存验证数据）
        baseline = await_second_start(db_path, migrated)
        for table, n in EXPECT.items():
            row = migrated.get(table, -1)
            ok = check(f"{table} 保留 {n} 条", row == n, f"迁移后 {row}")
            failures += 0 if ok else 1
        ok = check(
            "复合主键可共存",
            migrated.get("_coexist") == 3,  # 原有 1 条(租户0) + 两个新租户
            f"同一 symbol 共 {migrated.get('_coexist')} 行",
        )
        failures += 0 if ok else 1

        # --- 场景 2：幂等（在同一库上重复启动，数据不重复、不丢） ---
        # 用脚本内部纯启动子进程，而不是 run_migration（后者会额外插数据做共存验证，
        # 二次运行会撞复合主键，掩盖幂等性本身的结论）。
        print("[2] 迁移幂等（重复启动）")
        again = await_second_start(db_path, baseline)
        for table in ("positions", "transactions", "goals"):
            ok = check(
                f"{table} 第二次启动仍为 {baseline.get(table)}",
                again.get(table) == baseline.get(table),
                f"{baseline.get(table)} -> {again.get(table)}",
            )
            failures += 0 if ok else 1

        # --- 场景 3：旧路径自动搬迁 ---
        print("[3] 旧路径 backend/app/data 自动搬到 MONEYHELPER_DATA_DIR")
        old_dir = BACKEND / "app" / "data"
        old_db = old_dir / "wealth.db"
        backup = None
        if old_db.exists():
            backup = tmp / "old_backup.db"
            shutil.copy2(old_db, backup)
        build_legacy_db(old_db)
        target_dir = tmp / "newdata"
        env = {**os.environ, "MONEYHELPER_DATA_DIR": str(target_dir)}
        env.pop("MONEYHELPER_DB_PATH", None)
        code = (
            "import asyncio, os\nfrom app import db\n"
            "async def m():\n    await db.init_db()\n"
            "    print('DBPATH'+str(db.DB_PATH), flush=True)\n"
            "asyncio.run(m())\n"
            # aiosqlite 的 worker 线程会拖住解释器退出，明确结束进程
            "os._exit(0)\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=str(BACKEND),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=180,
        )
        ok = check(
            "启动子进程正常退出",
            proc.returncode == 0,
            (proc.stderr or "")[-200:] if proc.returncode else "",
        )
        failures += 0 if ok else 1
        ok = check(
            "启动时指向新数据目录",
            f"DBPATH{target_dir}" in (proc.stdout or ""),
            (proc.stdout or "").strip()[:160],
        )
        failures += 0 if ok else 1
        target_db = target_dir / "wealth.db"
        ok = check("新位置已生成库", target_db.exists())
        failures += 0 if ok else 1
        if target_db.exists():
            c = counts(target_db)
            ok = check("搬迁后数据完整", c.get("positions") == 2, f"positions={c.get('positions')}")
            failures += 0 if ok else 1
        # 还原现场
        if backup is not None:
            shutil.copy2(backup, old_db)
        else:
            old_db.unlink(missing_ok=True)
            for s in ("-wal", "-shm"):
                Path(str(old_db) + s).unlink(missing_ok=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED: {failures} 项未通过")
        return 1
    print("ALL PASSED: 旧库升级路径完整")
    return 0


if __name__ == "__main__":
    sys.exit(main())
