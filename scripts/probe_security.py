"""安全面验收：口令闸、MCP 闸、限流、越权路径，全部走真实 HTTP。

单测里鉴权是 mock 的；这里起真服务、配真 `API_TOKEN`，从外部打进去，验的是
"中间件链真的挂上了、MCP 子应用没有绕过主闸"这类只有跑起来才看得见的事。
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8097
TOKEN = "probe-secret-123"


async def main() -> int:
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "MONEYHELPER_DB_PATH": str(ROOT / ".tmp" / "security_probe.db"),
        "MONEYHELPER_DATA_DIR": str(ROOT / ".tmp" / "security_data"),
        "API_TOKEN": TOKEN,
        "LLM_ENABLED": "0",
    }
    Path(env["MONEYHELPER_DB_PATH"]).unlink(missing_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    rows: list[dict] = []
    try:
        import httpx

        base = f"http://127.0.0.1:{PORT}"
        for _ in range(60):
            try:
                async with httpx.AsyncClient(timeout=3) as c:
                    # 有口令时连健康检查都要带 token
                    if (await c.get(f"{base}/api/health", headers={"Authorization": f"Bearer {TOKEN}"})).status_code < 500:
                        break
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.5)

        async with httpx.AsyncClient(timeout=10, base_url=base) as c:
            auth = {"Authorization": f"Bearer {TOKEN}"}

            r = await c.get("/api/settings")
            rows.append({"case": "无口令读设置", "ok": r.status_code == 401, "detail": str(r.status_code)})

            r = await c.get("/api/settings", headers=auth)
            rows.append({"case": "Bearer 口令读设置", "ok": r.status_code == 200, "detail": str(r.status_code)})

            r = await c.get("/api/settings", headers={"Authorization": "Bearer wrong"})
            rows.append({"case": "错误口令", "ok": r.status_code == 401, "detail": str(r.status_code)})

            r = await c.get(f"/api/settings?token={TOKEN}")
            rows.append({"case": "query 口令", "ok": r.status_code == 200, "detail": str(r.status_code)})

            r = await c.post("/api/watchlist", json={"symbol": "600519"})
            rows.append({"case": "无口令写接口", "ok": r.status_code == 401, "detail": str(r.status_code)})

            # MCP 子应用绕过主 middleware：必须自己走闸
            body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "probe", "version": "0"}}}
            r = await c.post("/mcp", json=body, headers={"Accept": "application/json, text/event-stream"})
            rows.append({"case": "MCP 无口令", "ok": r.status_code == 401, "detail": str(r.status_code)})

            # 限流：同一 IP 连打，至少要出现一次 429
            codes = []
            for _ in range(215):
                rr = await c.get("/api/settings", headers=auth)
                codes.append(rr.status_code)
            rows.append({"case": "限流触发", "ok": 429 in codes, "detail": f"max={max(codes)} 429×{codes.count(429)}"})

            # 登录防爆破：5 次/60s 的独立窗口，第 6 次必须 429
            login_codes = []
            for _ in range(6):
                rr = await c.post("/api/auth/login", json={"username": "probe", "password": "wrong"})
                login_codes.append(rr.status_code)
            rows.append({"case": "登录防爆破", "ok": 429 in login_codes,
                         "detail": f"{login_codes}"})

            # 路径穿越：静态/文件类接口不能把系统文件吐出来
            trav = []
            for p in ("/api/files/../../etc/passwd", "/api/attachments/../../etc/passwd", "/../../etc/passwd"):
                try:
                    rr = await c.get(p, headers=auth)
                    trav.append((p, rr.status_code, "root:" in rr.text))
                except Exception as exc:  # noqa: BLE001
                    trav.append((p, "EXC", False))
            rows.append({"case": "路径穿越", "ok": not any(t[2] for t in trav), "detail": str(trav)})
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    for r in rows:
        print(("✓" if r["ok"] else "✗"), r["case"], "—", r["detail"], flush=True)
    bad = [r for r in rows if not r["ok"]]
    print(f"\n通过 {len(rows) - len(bad)}/{len(rows)}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
