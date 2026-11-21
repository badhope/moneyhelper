"""CSV 账单导入验收：解析、入账、整批原子性。

产品承诺是"先全量校验，再单事务写入"——第 37 行日期非法时不能只写前 36 行。
这里用真 HTTP 打：先导一份带 BOM/引号/逗号的 CSV，再故意混一条坏日期，
确认整批被拒且账本条数不变。
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8086

CSV_OK = "\ufeff日期,项目,金额\n2026-11-20,\"午饭, 加辣\",-35\n2026-11-21,工资,8000\n"
CSV_BAD = "\ufeff日期,项目,金额\n2026-11-20,正常一笔,-10\n2026-13-45,坏日期,-20\n"


async def main() -> int:
    db_path = ROOT / ".tmp" / "import_probe.db"
    data_dir = ROOT / ".tmp" / "import_data"
    db_path.unlink(missing_ok=True)
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "MONEYHELPER_DB_PATH": str(db_path),
        "MONEYHELPER_DATA_DIR": str(data_dir),
        "LLM_ENABLED": "0",
    }
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
            p = await c.post("/api/import/generic", json={"content": CSV_OK})
            data = p.json()
            case("CSV 解析", p.status_code == 200 and data.get("total") == 2, f"{p.status_code} total={data.get('total')}")
            case("引号内逗号不被拆列", any(r["item"] == "午饭, 加辣" for r in data.get("rows", [])),
                 str([r.get("item") for r in data.get("rows", [])]))

            commit = await c.post("/api/import/commit", json={"rows": data["rows"]})
            done = (commit.json() or {}).get("imported") or []
            case("批量入账", commit.status_code == 200 and len(done) == 2, str(commit.json())[:80])

            n1 = (await c.get("/api/export")).json().get("transactions") or []
            case("入账条数", len(n1) == 2, f"{len(n1)} 条")

            # 坏批次：直接提交含非法日期的 rows，整批拒绝且零写入
            badc = await c.post(
                "/api/import/commit",
                json={"rows": [
                    {"date": "2026-11-20", "item": "正常一笔", "category": "其他", "amount": -10},
                    {"date": "2026-13-45", "item": "坏日期", "category": "其他", "amount": -20},
                ]},
            )
            after = (await c.get("/api/export")).json().get("transactions") or []
            case("坏批次整批拒绝", badc.status_code == 400, f"{badc.status_code} {str(badc.json())[:60]}")
            case("坏批次零写入", len(after) == len(n1), f"{len(n1)}→{len(after)}")
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
