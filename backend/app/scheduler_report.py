"""晨报生成：问答复用同一条管线（确定性模板或模型），归档 thread_id='cron'。

从 scheduler.py 拆出；运行态计数仍写在门面的 `_state`（测试与 /api/scheduler 读同一份）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import db, service
from . import scheduler as _facade
from .logging_utils import get_logger
from .provenance import record_provenance

log = get_logger(__name__)


REPORT_QUESTION = "帮我做一次全面体检：汇总我的组合、账本与财务目标的现状，只描述事实与风险提示，不给操作建议。"


def _parse_time(value: str | None) -> tuple[int, int] | None:
    if not value or ":" not in value:
        return None
    try:
        h, m = value.strip().split(":")
        hh, mm = int(h), int(m)
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        return hh, mm
    except (ValueError, TypeError):
        return None


async def has_data() -> bool:
    """库中是否已有持仓或流水（空库不生成无意义的晨报）。"""
    if await db.list_positions():
        return True
    return bool(await db.fetch_all("SELECT 1 FROM transactions LIMIT 1"))


async def generate_report() -> dict[str, Any]:
    """生成一次晨报并归档。手动触发（POST /api/reports/generate）与定时共用。

    空库时返回 skipped=True 并跳过归档：无内容的定时产出只是噪音。
    """
    async def emit(e: dict[str, Any]) -> None:
        pass

    if not await _facade.has_data():
        return {
            "skipped": True,
            "reason": "no_data",
            "answer": "",
            "level": "",
            "flags": [],
        }

    try:
        # 关注的要点（设置 → 晨报，可 AI 生成）：拼进报告问题，让成文聚焦用户关心的点
        st = await db.get_settings()
        focus = (st.get("report_focus") or "").strip()
        question = (
            f"{REPORT_QUESTION}\n\n本次请重点结合这一点来写：{focus[:200]}" if focus else REPORT_QUESTION
        )
        result = await service.run_question(question, emit)
        await db.save_run(
            thread_id="cron",
            question=question,
            answer=result["answer"],
            level=result["level"],
            flags=result["flags"],
            route=result.get("route", ""),
            llm=result.get("llm", ""),
            route_reason=result.get("route_reason", ""),
            # 系统归档不进会话列表：晨报历史按 thread_id='cron' 从 runs 读取
            skip_session=True,
        )
        _facade._state["generated"] += 1
        _facade._state["last_run_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _facade._state["last_error"] = None
        # 记录晨报生成审计：审计失败不应把已生成的晨报标成失败
        try:
            await record_provenance(
                action="generate_morning_report",
                entity_type="report",
                entity_id="morning_report",
                before=None,
                after={"generated": _facade._state["generated"], "thread_id": "cron"},
                source="scheduler",
                username="system",
            )
        except Exception as audit_exc:  # noqa: BLE001
            log.warning("morning report audit failed: %s", audit_exc)
        return result
    except Exception as exc:  # noqa: BLE001 — 晨报失败只记录，不炸服务
        _facade._state["last_error"] = f"{type(exc).__name__}: {exc}"
        raise
