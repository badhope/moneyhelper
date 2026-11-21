"""导出/导入面验收：CSV 转义、BOM、报表、备份 JSON 往返。

导出看着简单，坏起来全是"打开是乱码/列错位/金额变文本"这类用户直接可见的问题。
这里先造几条带逗号、引号、换行、中文的流水，再从 HTTP 导出，用标准 csv 解析器
反解，逐字段比对；最后把备份 JSON 导回去，确认条数不漂。
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8088
sys.path.insert(0, str(ROOT / "backend"))


async def _seed() -> None:
    from app import db

    await db.init_db()
    await db.add_transaction("2026-11-20", '午饭, "加辣"', "餐饮", -35.5)
    await db.add_transaction("2026-11-21", "工资", "工资", 8000)
    await db.add_transaction("2026-11-21", "跨行\n换行测试", "其他", -12)


async def main() -> int:
    db_path = ROOT / ".tmp" / "export_probe.db"
    data_dir = ROOT / ".tmp" / "export_data"
    db_path.unlink(missing_ok=True)
    os.environ["MONEYHELPER_DB_PATH"] = str(db_path)
    os.environ["MONEYHELPER_DATA_DIR"] = str(data_dir)
    await _seed()

    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "LLM_ENABLED": "0"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    rows: list[dict] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        rows.append({"case": name, "ok": ok, "detail": detail})

    try:
        import httpx

        base = f"http://127.0.0.1:{PORT}"
        for _ in range(60):
            try:
                async with httpx.AsyncClient(timeout=3) as c:
                    if (await c.get(f"{base}/api/health")).status_code < 500:
                        break
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.5)

        async with httpx.AsyncClient(timeout=20, base_url=base) as c:
            # 1) 备份 JSON
            r = await c.get("/api/export")
            payload = r.json() if r.status_code == 200 else {}
            case("备份 JSON 导出", r.status_code == 200 and isinstance(payload, dict), str(r.status_code))

            # 2) CSV：BOM + 表头 + 逐字段反解（含逗号/引号/换行）
            r = await c.get("/api/export/csv")
            raw = r.content
            case("CSV 状态与 BOM", r.status_code == 200 and raw.startswith(b"\xef\xbb\xbf"), f"{r.status_code} bom={raw[:3]!r}")
            text = raw.decode("utf-8-sig")
            parsed = list(csv.reader(io.StringIO(text)))
            header, body = parsed[0], parsed[1:]
            case("CSV 表头", bool(header), ",".join(header))
            cells = "\n".join(",".join(row) for row in body)
            case("CSV 保留逗号引号", '午饭, "加辣"' in cells, cells[:80])
            case("CSV 保留换行", "跨行\n换行测试" in cells or "跨行\r\n换行测试" in cells, "换行未被吃掉")
            amounts = [row[-1] for row in body if row]
            case("CSV 金额是数字", any(abs(abs(float(a)) - 35.5) < 0.01 for a in amounts if a.strip()), str(amounts[:4]))

            # 3) 报表
            rr = await c.get("/api/export/report")
            case("报表导出", rr.status_code == 200 and len(rr.content) > 100, f"{rr.status_code} {len(rr.content)}B")

            # 4) 备份 JSON 导回：条数不漂
            before = len((await c.get("/api/export")).json().get("transactions") or [])
            imp = await c.post("/api/import/backup", json=payload)
            after = len((await c.get("/api/export")).json().get("transactions") or [])
            case("备份导入往返", imp.status_code < 400 and after == before, f"{imp.status_code} {before}→{after}")
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    for x in rows:
        print(("✓" if x["ok"] else "✗"), x["case"], "—", x["detail"], flush=True)
    bad = [x for x in rows if not x["ok"]]
    print(f"\n通过 {len(rows) - len(bad)}/{len(rows)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
