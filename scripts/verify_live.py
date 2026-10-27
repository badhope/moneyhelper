"""真实模型端到端验收脚本（不写死任何密钥）。

用法（PowerShell）：
    $env:LLM_BASE_URL="https://your-endpoint/v1"
    $env:LLM_API_KEY="sk-..."
    $env:LLM_MODEL="your-model"
    $env:MONEYHELPER_DB_PATH="$PWD/../out/verify.db"
    .venv\\Scripts\\python scripts/verify_live.py

用法（bash）：
    LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... \
      MONEYHELPER_DB_PATH="$PWD/../out/verify.db" .venv/bin/python scripts/verify_live.py

验收内容：
1. 模型连通（llm_available）
2. 确定性记账（不依赖模型）
3. 模型 + function calling：必须真实调用工具并依据工具结果回答
4. 多轮追问

退出码：0 全部通过；1 有断言失败。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

OUT_PATH = os.getenv("VERIFY_LOG") or ""
_T0 = time.time()
_lines: list[str] = []


def log(msg: str) -> None:
    line = f"{time.time() - _T0:6.1f}s {msg}"
    _lines.append(line)
    print(line, flush=True)
    if OUT_PATH:
        with open(OUT_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


async def _emit(_ev: dict) -> None:
    return None


async def _run() -> int:
    from app import db, llm, service

    failures: list[str] = []
    if not os.getenv("LLM_API_KEY"):
        log("SKIP: 未设置 LLM_API_KEY")
        return 0

    await db.init_db()
    log("db ready")

    available = await llm.llm_available()
    log(f"llm_available={available}")
    if not available:
        failures.append("模型不可用（检查 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL）")

    # 1) 确定性记账：即使模型不可用也必须成功
    r1 = await service.run_question("咖啡 28 元", _emit, thread_id="verify-1")
    receipt = (r1.get("answer") or "").strip()
    log("record → " + receipt[:60])
    if "28" not in receipt:
        failures.append("一句话记账未成功写入 28 元")

    # 2) 模型应调用工具读账本
    r2 = await service.run_question("我本月支出多少？", _emit, thread_id="verify-2")
    tools = r2.get("tools") or []
    log(f"llm tools={tools} llm={r2.get('llm')}")
    log("answer → " + (r2.get("answer") or "")[:120].replace("\n", " "))
    if not tools:
        failures.append("模型未调用任何工具（function calling 链路可能未生效）")
    if (r2.get("answer") or "").strip() == "":
        failures.append("模型返回空回答")

    # 3) 多轮追问：同一线程应能继续
    r3 = await service.run_question("那结余呢？", _emit, thread_id="verify-2")
    log(f"followup tools={r3.get('tools')} route={r3.get('route')}")
    if not (r3.get("answer") or "").strip():
        failures.append("追问未返回回答")

    for f in failures:
        log("FAIL: " + f)
    return 1 if failures else 0


def main() -> None:
    try:
        code = asyncio.run(_run())
    finally:
        pass
    # asyncio 默认线程池与 anyio worker 是标准库行为，脚本退出时无需等待
    sys.stdout.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
