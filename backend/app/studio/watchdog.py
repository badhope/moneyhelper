"""运行时看门狗：周期性检查服务健康、日志错误与配置完整性，产出可读告警。

启动时随 lifespan 注册；间隔与开关由 Studio 配置控制（默认 15 分钟）。
检查项刻意保持只读 + 确定性：不调用模型、不发网络请求，避免监控本身成为故障源。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from .. import db, mcp_client
from ..logging_utils import get_logger, read_log_lines
from . import store

log = get_logger(__name__)

_state: dict[str, Any] = {
    "last_check_at": "",
    "last_findings": [],
    "checks": 0,
    "errors_seen": 0,
}
_task: asyncio.Task | None = None
_stop: asyncio.Event | None = None
_ERROR_MARKERS = ("ERROR", "CRITICAL", "Traceback")


def status() -> dict[str, Any]:
    return {
        "running": bool(_task and not _task.done()),
        "last_check_at": _state["last_check_at"],
        "checks": _state["checks"],
        "errors_seen": _state["errors_seen"],
        "findings": list(_state["last_findings"])[-10:],
    }


def _scan_logs(limit: int = 400) -> list[str]:
    lines = read_log_lines(limit)
    out: list[str] = []
    for line in lines:
        if any(m in line for m in _ERROR_MARKERS):
            out.append(line[:300])
    return out[-20:]


async def run_check() -> dict[str, Any]:
    """执行一轮检查，返回发现项（空数组 = 健康）。"""
    findings: list[dict[str, str]] = []
    try:
        settings = await db.get_settings()
    except Exception as exc:  # noqa: BLE001 — 数据库异常本身就是最高优先级发现
        findings.append({"level": "error", "code": "db_unavailable", "message": f"设置读取失败：{exc}"})
        settings = {}
    for key in ("ai_base_url", "ai_model"):
        if settings.get(key) == "":
            pass
    cfg = await store.get_config()
    prompts = cfg.get("prompts") or {}
    if not any(p.get("enabled", True) for p in prompts.values() if isinstance(p, dict)):
        findings.append(
            {
                "level": "warn",
                "code": "no_active_prompt",
                "message": "没有任何启用的提示词，模型将只使用内置基础说明",
            }
        )
    if not any(r.get("enabled", True) for r in (cfg.get("rules") or {}).values() if isinstance(r, dict)):
        findings.append(
            {"level": "warn", "code": "no_active_rule", "message": "没有任何启用的约束，回答质量无护栏"}
        )
    disabled_mcp = [s["name"] for s in mcp_client.list_servers() if not s.get("enabled", True)]
    if disabled_mcp:
        findings.append(
            {
                "level": "info",
                "code": "mcp_disabled",
                "message": f"{len(disabled_mcp)} 个 MCP 服务器处于停用状态：{', '.join(disabled_mcp[:3])}",
            }
        )
    errs = _scan_logs()
    if errs:
        findings.append(
            {
                "level": "warn",
                "code": "log_errors",
                "message": f"日志中有 {len(errs)} 条错误/告警，最近一条：{errs[-1]}",
            }
        )
    _state["checks"] += 1
    _state["errors_seen"] += len([f for f in findings if f["level"] == "error"])
    _state["last_check_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    _state["last_findings"] = findings
    if findings:
        log.info("studio.watchdog findings=%s", len(findings))
    return {"ok": True, "findings": findings, "checked_at": _state["last_check_at"]}


async def _loop(interval_minutes: int) -> None:
    assert _stop is not None
    while not _stop.is_set():
        try:
            await run_check()
        except Exception as exc:  # noqa: BLE001 — 监控自身失败不能让服务崩
            log.warning("studio.watchdog check failed: %s", exc)
        try:
            await asyncio.wait_for(_stop.wait(), timeout=max(60, interval_minutes * 60))
        except asyncio.TimeoutError:
            continue


async def start() -> None:
    global _task, _stop
    cfg = await store.watchdog_settings()
    if not cfg.get("enabled", True):
        return
    if _task and not _task.done():
        return
    _stop = asyncio.Event()
    _task = asyncio.create_task(_loop(int(cfg.get("interval_minutes") or 15)))
    log.info("studio.watchdog started interval=%smin", cfg.get("interval_minutes"))


async def stop() -> None:
    global _task, _stop
    if _stop is not None:
        _stop.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=5)
        except Exception:  # noqa: BLE001 — 退出阶段不阻塞
            pass
    _task = None
    _stop = None
