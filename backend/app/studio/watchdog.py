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
_current_interval: int = 0
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
    # 扫日志失败不该让"一键自检"整个 500：监控自身的故障必须降级成一条发现项，
    # 而不是变成被监控对象的崩溃（read_log_lines 已自行兜底 OSError，这里是第二道）。
    try:
        lines = read_log_lines(limit)
    except Exception as exc:  # noqa: BLE001 — 见上，监控路径不允许向外抛
        log.warning("studio.watchdog log scan failed: %s", exc)
        return []
    out: list[str] = []
    for line in lines:
        if any(m in line for m in _ERROR_MARKERS):
            out.append(line[:300])
    return out[-20:]


async def run_check(advance_state: bool = True) -> dict[str, Any]:
    """执行一轮检查，返回发现项（空数组 = 健康）。

    advance_state=False 用于设置页「一键自检」：只读扫一遍，不改看门狗的
    checks 计数与 last_check_at（否则点几次自检就把巡检节奏记录搞乱）。
    """
    findings: list[dict[str, str]] = []
    try:
        await db.get_settings()
    except Exception as exc:  # noqa: BLE001 — 数据库异常本身就是最高优先级发现
        findings.append({"level": "error", "code": "db_unavailable", "message": f"设置读取失败：{exc}"})
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
    if advance_state:
        _state["checks"] += 1
        _state["errors_seen"] += len([f for f in findings if f["level"] == "error"])
        _state["last_check_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _state["last_findings"] = findings
    if findings:
        log.info("studio.watchdog findings=%s", len(findings))
    return {"ok": True, "findings": findings, "checked_at": _state["last_check_at"]}


async def _loop(interval_minutes: int) -> None:
    global _current_interval
    _current_interval = interval_minutes
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
    """启动看门狗（幂等；间隔变化时重启）。

    两个真实缺陷的修法：
    1. `_current_interval` 原本只在 `_loop` 协程体里赋值，而 `start()` 里
       已经用它做「间隔是否变化」的判断——协程还没被调度到，读到的永远是
       **上一次**的值。连续两次 start(5) 会被误判成「间隔变了」而重启两次。
       现在在创建 task 之前同步赋值。
    2. `_task` 可能属于已关闭的事件循环（测试每例一个新 loop），
       此时 `_task.done()` 可能是 False 但 await 它会抛 Event loop is closed。
       先探测循环存活，再决定复用还是重建。
    """
    global _task, _stop, _current_interval
    cfg = await store.watchdog_settings()
    if not cfg.get("enabled", True):
        return
    wanted = int(cfg.get("interval_minutes") or 15)

    if _task is not None:
        loop = getattr(_task, "get_loop", lambda: None)()
        if loop is not None and loop.is_closed():
            # 残留任务属于已关闭的循环：丢弃，不能 await 也不能复用
            _task = None
            _stop = None
        elif _task.done():
            _task = None
            _stop = None
        elif wanted == _current_interval:
            return
        else:
            await stop()

    _stop = asyncio.Event()
    _current_interval = wanted          # 同步赋值，供下一次 start() 比较
    _task = asyncio.create_task(_loop(wanted))
    log.info("studio.watchdog started interval=%smin", wanted)


async def stop() -> None:
    """停止看门狗。无论等待是否成功，_task/_stop 都必须清空。"""
    global _task, _stop
    stop_evt, task = _stop, _task
    _task = None
    _stop = None
    if stop_evt is not None:
        try:
            stop_evt.set()
        except RuntimeError:
            # Event 绑定已关闭的循环：set() 会抛，直接放弃（反正要丢弃）
            pass
    if task is not None and not task.done():
        try:
            await asyncio.wait_for(task, timeout=5)
        except Exception:  # noqa: BLE001 — 退出阶段不阻塞，也不掩盖清理
            pass
