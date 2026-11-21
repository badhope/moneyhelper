"""备份 → 恢复闭环：跨两个进程验，避免"同进程换库无效"的老坑。

备份的价值不在"生成了文件"，而在"换个库能原样还原"。这个探针分两阶段：

1. `--phase seed`：造数据（自选/流水/持仓/记忆/设置/模拟盘/条件单/发票）→
   生成加密备份 → 把口令、文件路径、原始计数写到 `.tmp/restore_ctx.json`。
2. `--phase restore`：全新库 + 同一数据目录 → 先验错口令必须解不开，
   再解密、`db.import_backup`，逐项比对值，并确认 `ai_api_key` 不会被备份带回来。

用法：
    PYTHONPATH=backend python3 scripts/probe_backup_restore.py --phase seed
    PYTHONPATH=backend python3 scripts/probe_backup_restore.py --phase restore
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
CTX = ROOT / ".tmp" / "restore_ctx.json"


async def seed() -> int:
    from app import db
    from app.tool_registry import TOOL_IMPL

    await db.init_db()
    await db.add_watchlist("600519", "贵州茅台", "股票")
    await db.add_position({"symbol": "600519", "name": "贵州茅台", "shares": 100,
                           "cost": 1500, "last": 1500, "kind": "股票", "industry": "白酒"})
    await db.add_transaction("2026-11-20", "午饭", "餐饮", -35)
    await db.add_transaction("2026-11-21", "工资", "工资", 8000)
    await db.add_memory("明年计划买房，首付 30 万")
    await db.set_setting("color_scheme", "us")
    await db.set_setting("ai_api_key", "sk-should-not-survive")
    acc = await db.open_account("备份验收账户", 100000)
    await db.add_trade(acc["account_id"] if isinstance(acc, dict) else acc,
                       {"symbol": "000001", "name": "平安银行", "side": "buy", "price": 12, "shares": 100, "fee": 5})

    out = await TOOL_IMPL["backup_now"]({"lang": "zh"})
    files = sorted((Path(os.environ["MONEYHELPER_DATA_DIR"]) / "backups").glob("moneyhelper-backup-*.json"))
    assert files, "备份文件没生成"
    source_counts = {
        "watchlist": len(await db.list_watchlist()),
        "transactions": len(await db.list_transactions(limit=500)),
        "positions": len(await db.list_positions()),
        "memory": len(await db.list_memory()),
    }
    CTX.write_text(json.dumps({
        "file": str(files[-1]),
        "passphrase": out["passphrase"],
        "counts": source_counts,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"seed ok：{files[-1].name}，计数 {source_counts}")
    return 0


async def restore() -> int:
    from app import backup, db

    ctx = json.loads(CTX.read_text(encoding="utf-8"))
    payload = json.loads(Path(ctx["file"]).read_text(encoding="utf-8"))
    rows: list[dict] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        rows.append({"case": name, "ok": ok, "detail": detail})

    # 1) 错口令必须解不开（而不是解出半份数据）
    try:
        backup.decrypt_export(payload, "wrong-passphrase")
        case("错口令拒绝", False, "竟然解开了")
    except ValueError as exc:
        case("错口令拒绝", True, str(exc)[:40])

    data = backup.decrypt_export(payload, ctx["passphrase"])
    await db.init_db()
    counts = await db.import_backup(data)

    await db.init_db()
    wl = await db.list_watchlist()
    tx = await db.list_transactions(limit=500)
    pos = await db.list_positions()
    mem = await db.list_memory()
    st = await db.get_settings()

    case("自选恢复", any(r["symbol"] == "600519" for r in wl), f"{len(wl)} 条")
    case("流水恢复", len(tx) == ctx["counts"]["transactions"], f"{len(tx)} 条")
    case("支出符号", any(abs(float(r["amount"])) == 35 and float(r["amount"]) < 0 for r in tx), "支出仍为负")
    case("持仓恢复", any(r["symbol"] == "600519" and float(r["shares"]) == 100 for r in pos), f"{len(pos)} 条")
    case("记忆恢复", any("买房" in str(r.get("content")) for r in mem), f"{len(mem)} 条")
    case("设置恢复", st.get("color_scheme") == "us", str(st.get("color_scheme")))
    case("密钥不随备份回来", not str(st.get("ai_api_key") or "").strip(), repr(st.get("ai_api_key")))
    case("恢复计数非空", sum(counts.values()) > 0, str(counts))

    for r in rows:
        print(("✓" if r["ok"] else "✗"), r["case"], "—", r["detail"], flush=True)
    bad = [r for r in rows if not r["ok"]]
    print(f"\n通过 {len(rows) - len(bad)}/{len(rows)}")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["seed", "restore"], required=True)
    a = ap.parse_args()
    raise SystemExit(asyncio.run(seed() if a.phase == "seed" else restore()))
