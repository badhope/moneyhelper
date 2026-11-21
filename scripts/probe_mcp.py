"""MCP 协议面验收：真客户端握手、列工具、调用、读写与大额 fail-closed。

前面 40 个只读工具是用 agent 的 OpenAI 端点验的；这一层验的是另一条对外接口：
MCP（Claude Code / Cursor / Cline 接进来的那条）。两者共用实现，但协议栈、
鉴权、确认策略完全不同，必须单独过一遍。

用法（脚本会自己拉起 uvicorn，跑完杀掉）：
    PYTHONPATH=backend python3 scripts/probe_mcp.py
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8099
URL = f"http://127.0.0.1:{PORT}/mcp"


async def main() -> int:
    db_path = ROOT / ".tmp" / "mcp_probe.db"
    data_dir = ROOT / ".tmp" / "mcp_data"
    db_path.unlink(missing_ok=True)
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "MONEYHELPER_DB_PATH": str(db_path),
        "MONEYHELPER_DATA_DIR": str(data_dir),
        "MONEYHELPER_TRADING_ENABLED": "0",
        "LLM_ENABLED": "0",
    }
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
        for _ in range(60):
            if await _healthy():
                break
            await asyncio.sleep(0.5)
        else:
            print("服务没起来", file=sys.stderr)
            return 2

        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(URL) as (read, write, _):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                rows.append({"case": "initialize", "ok": True, "detail": init.serverInfo.name})

                tools = (await session.list_tools()).tools
                rows.append({"case": "tools/list", "ok": len(tools) >= 60, "detail": f"{len(tools)} 个"})

                # 只读调用：真实取价
                res = await _call(session, "get_quote", {"symbol": "600519"})
                rows.append({"case": "call get_quote", "ok": "600519" in res and any(c.isdigit() for c in res), "detail": res[:80]})

                # 写调用：小额的加自选，应当直接落库
                await _call(session, "add_to_watchlist", {"symbol": "600519", "name": "贵州茅台", "kind": "股票"})
                wl = await _call(session, "get_watchlist", {})
                rows.append({"case": "write add_to_watchlist", "ok": "600519" in wl, "detail": wl[:80]})

                # 大额写：客户端不支持 elicitation 时必须 fail-closed，且不能落库
                big = await _call(session, "record_transaction", {"text": "买电脑花了 20000 元"})
                after = await _call(session, "get_ledger_view", {})
                ok = ("确认" in big or "拒绝" in big or "approval" in big.lower()) and "20000" not in after
                rows.append({"case": "big write fail-closed", "ok": ok, "detail": big[:100]})

                # 无必填参数的工具有多少就能空跑多少：空库下不许报 isError/空白
                zero = [t for t in tools if not (t.inputSchema or {}).get("required")]
                failed = []
                for t in zero:
                    try:
                        rr = await session.call_tool(t.name, {})
                        txt = "\n".join(getattr(c, "text", "") for c in rr.content).strip()
                        if rr.isError or not txt:
                            failed.append(f"{t.name}:{'isError' if rr.isError else '空'}:{txt[:50]}")
                    except Exception as exc:  # noqa: BLE001
                        failed.append(f"{t.name}:{type(exc).__name__}")
                rows.append({"case": "无参工具空库全跑", "ok": not failed,
                             "detail": f"{len(zero)} 个，失败 {failed[:4]}"})

                prompts = (await session.list_prompts()).prompts
                rows.append({"case": "prompts/list", "ok": len(prompts) >= 3, "detail": f"{len(prompts)} 个"})
                got = await session.get_prompt(prompts[0].name, {})
                rows.append({"case": "prompts/get", "ok": bool(got.messages), "detail": prompts[0].name})

                resources = (await session.list_resources()).resources
                rows.append({"case": "resources/list", "ok": len(resources) >= 3, "detail": f"{len(resources)} 个"})
                if resources:
                    rr = await session.read_resource(resources[0].uri)
                    rows.append({"case": "resources/read", "ok": bool(rr.contents), "detail": str(resources[0].uri)})

        # 第二条传输：HTTP+SSE（旧客户端接的 /mcp-sse，保留一个版本期）
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        async with sse_client(f"http://127.0.0.1:{PORT}/mcp-sse/sse") as (sr, sw):
            async with ClientSession(sr, sw) as sse_session:
                await sse_session.initialize()
                sse_tools = (await sse_session.list_tools()).tools
                got = await sse_session.call_tool("get_watchlist", {})
                text = "\n".join(getattr(c, "text", "") for c in got.content)
                rows.append({"case": "SSE 传输 handshake+调用",
                             "ok": len(sse_tools) == len(tools) and ("600519" in text or "自选" in text),
                             "detail": f"{len(sse_tools)} 个工具"})
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    for r in rows:
        print(("✓" if r["ok"] else "✗"), r["case"], "—", r["detail"], flush=True)
    bad = [r for r in rows if not r["ok"]]
    print(f"\n通过 {len(rows) - len(bad)}/{len(rows)}", flush=True)
    return 1 if bad or len(rows) < 8 else 0


async def _call(session, name: str, args: dict) -> str:
    out = await session.call_tool(name, args)
    parts = []
    for c in out.content:
        parts.append(getattr(c, "text", "") or "")
    return "\n".join(p for p in parts if p)


async def _healthy() -> bool:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get(f"http://127.0.0.1:{PORT}/api/health")
            return r.status_code < 500
    except Exception:  # noqa: BLE001 — 端口没起来就继续等
        return False


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
