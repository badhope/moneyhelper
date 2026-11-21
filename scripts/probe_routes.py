"""REST 路由面验收：把 OpenAPI 里所有"无路径参数"的 GET 路由真打一遍。

单测是按功能点写的，容易漏掉"某个页面在空库/首次启动时会 500"这类问题。
这里换一个角度：照 OpenAPI 清单逐条打，任何 5xx 都算问题（4xx 是业务拒绝，
如鉴权失败、参数缺失，属正常）。全程隔离库，只打 GET，不触发写操作。

用法：
    PYTHONPATH=backend python3 scripts/probe_routes.py
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8098


async def main() -> int:
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "MONEYHELPER_DB_PATH": str(ROOT / ".tmp" / "routes_probe.db"),
        "MONEYHELPER_DATA_DIR": str(ROOT / ".tmp" / "routes_data"),
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
        else:
            print("服务没起来", file=sys.stderr)
            return 2

        SKIP = ("/mcp", "/qa", "/chat", "/agent", "/ai/", "/search", "/webhook",
                "/backtest", "/research", "/interpret", "/eval")

        async with httpx.AsyncClient(timeout=20, base_url=base) as c:
            spec = (await c.get("/openapi.json")).json()
            paths = spec.get("paths", {})
            targets = [
                p for p, item in paths.items()
                if "get" in item and "{" not in p and not p.startswith("/mcp")
            ]
            bad = []
            for p in targets:
                try:
                    r = await c.get(p)
                except Exception as exc:  # noqa: BLE001 — 超时/连接断开也算失败
                    bad.append((p, f"EXC {type(exc).__name__}"))
                    continue
                if r.status_code >= 500:
                    bad.append((p, f"{r.status_code} {r.text[:80]}"))

            # POST 面：空对象打一轮，只抓 5xx（422 是正常的参数校验，4xx 是业务拒绝）
            posts = [
                p for p, item in paths.items()
                if "post" in item and "{" not in p and not any(k in p for k in SKIP)
            ]
            bad_posts = []
            for p in posts:
                try:
                    r = await c.post(p, json={})
                except Exception as exc:  # noqa: BLE001
                    bad_posts.append((p, f"EXC {type(exc).__name__}"))
                    continue
                if r.status_code >= 500:
                    bad_posts.append((p, f"{r.status_code} {r.text[:80]}"))

            # 带路径参数的路由：占位值打一遍，只抓 5xx（404/422 是正常的"没有这个对象"）
            import re as _re

            param_routes = []
            for p, item in paths.items():
                if "{" not in p or any(k in p for k in SKIP):
                    continue
                filled = _re.sub(r"{[^}]+}", "probe-missing-id", p)
                for m in ("get", "post", "put", "patch", "delete"):
                    if m in item:
                        param_routes.append((m, p, filled))
            bad_params = []
            for m, p, filled in param_routes:
                try:
                    r = await c.request(m.upper(), filled, json={} if m != "get" else None)
                except Exception as exc:  # noqa: BLE001
                    bad_params.append((m.upper(), p, f"EXC {type(exc).__name__}"))
                    continue
                if r.status_code >= 500:
                    bad_params.append((m.upper(), p, f"{r.status_code} {r.text[:60]}"))

        print(f"GET 路由 {len(targets)} 条，5xx {len(bad)} 条", flush=True)
        for p, why in bad_posts:
            print("✗ POST", p, "—", why, flush=True)
        print(f"POST 路由 {len(posts)} 条（空体），5xx {len(bad_posts)} 条", flush=True)
        for m, p, why in bad_params:
            print("✗ PARAM", m, p, "—", why, flush=True)
        print(f"带参路由 {len(param_routes)} 条（占位值），5xx {len(bad_params)} 条", flush=True)
        for p, why in bad:
            print("✗", p, "—", why, flush=True)
        out = ROOT / ".tmp" / "routes_sweep.json"
        out.write_text(
            json.dumps({"get_total": len(targets), "get_bad": bad, "post_total": len(posts), "post_bad": bad_posts,
                        "param_total": len(param_routes), "param_bad": bad_params},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("写入", out)
        return 1 if (bad or bad_posts or bad_params) else 0
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
