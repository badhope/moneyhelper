"""模型不可用时的降级验收：端点连不上，应用不能挂、不能空白。

用户最常见的故障不是"模型答错"，而是"模型没配好/断网"——这时要么走确定性
模板，要么明确告知，绝不能转圈到超时再给一片空白。

用法：
    PYTHONPATH=backend python3 scripts/probe_llm_down.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


async def _noop(_ev) -> None:  # noqa: ANN001 — 与 agent.run_agent 的 emit 约定一致
    return None


async def main() -> int:
    from app import db, service

    await db.init_db()
    await db.add_position({"symbol": "600519", "name": "贵州茅台", "shares": 100, "cost": 1500, "last": 1485, "kind": "股票"})
    rows: list[dict] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        rows.append({"case": name, "ok": ok, "detail": detail})

    t = time.time()
    try:
        out = await service.run_question("我的持仓现在值多少钱？", _noop)
        elapsed = round(time.time() - t, 1)
        answer = (out or {}).get("answer") or ""
        case("断网仍有回答", bool(answer.strip()), f"{len(answer)} 字 / {elapsed}s")
        case("不把异常抛给用户", True, answer[:60].replace("\n", " "))
        case("耗时可控", elapsed < 60, f"{elapsed}s")
    except Exception as exc:  # noqa: BLE001 — 这里恰恰要抓"抛异常"
        case("断网仍有回答", False, f"{type(exc).__name__}: {exc}"[:80])

    # 原始 run_agent 抛 AgentUnavailable 是设计：降级在 agent_graph 里做，
    # 产品入口（service.run_question）不应把异常抛给用户。
    from app import agent

    try:
        await agent.run_agent("我的持仓现在值多少钱？", _noop)
        case("底层抛异常符合约定", False, "run_agent 竟然没抛")
    except agent.AgentUnavailable:
        case("底层抛异常符合约定", True, "AgentUnavailable（由图内降级接住）")

    # 设置页里把 ai_base_url 改到内网地址：工具层必须拒绝（防数据外带）
    from app.tool_registry import TOOL_IMPL

    denied = await TOOL_IMPL["set_setting"]({"key": "ai_base_url", "value": "http://10.0.0.1:8000/v1"})
    case("工具层拒绝改模型端点", "设置" in str(denied) or "Settings" in str(denied), str(denied)[:60])

    for r in rows:
        print(("✓" if r["ok"] else "✗"), r["case"], "—", r["detail"], flush=True)
    bad = [r for r in rows if not r["ok"]]
    print(f"\n通过 {len(rows) - len(bad)}/{len(rows)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
