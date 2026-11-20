"""晨报触发工具：手动生成今日晨报（空库给可读提示，失败给可读错误）。"""

from __future__ import annotations

from typing import Any

from . import scheduler


async def tool_trigger_morning_report(_args: dict[str, Any], lang: str = "zh") -> str:
    """触发生成今日晨报（组合+账本+目标体检，空库会提示没有数据）。"""
    try:
        result = await scheduler.generate_report()
    except Exception as exc:  # noqa: BLE001 — 手动触发失败要给可读错误
        if lang != "zh":
            return f"Morning report generation failed: {type(exc).__name__}: {exc}"
        return f"晨报生成失败：{type(exc).__name__}: {exc}"
    if result.get("skipped"):
        if lang != "zh":
            return (
                "Not enough data yet for a morning report (need at least one holding or transaction). "
                "Record an entry or add a holding, and I'll run your check-up."
            )
        return "还没有足够的数据生成晨报（需要至少一条持仓或流水）。先记一笔账或添加持仓，我再来帮你体检。"
    if lang != "zh":
        return result.get("answer", "Morning report generated.") + "\n(archived to Ask AI → Morning report history)"
    return result.get("answer", "晨报已生成。") + "\n（已归档到「问AI」→ 晨报历史）"
