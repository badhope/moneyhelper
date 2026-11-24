"""定时任务（APScheduler）：每日晨报 + 订阅到期巡检。

- 报告时间存 settings.report_time（HH:MM），保存设置后立即重排。
- 报告走同一条问答服务（确定性模板或模型），归档 thread_id='cron'。
- 订阅到期巡检：每天检查 subscriptions，7 天内到期的写入一条 user_memory
  （kind=subscription_due），前端在总览/设置记忆页用到；本月已提醒过的不再重复写。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import db
from .automation_runner import run_scheduled_month_end
from .logging_utils import get_logger
from .scheduler_background import (  # noqa: F401,E402 — 对外同名导出（含测试直调）
    _month_end_close,
    _scan_connect_inbox,
    _sync_connect_sources,
)
from .scheduler_skills import run_skill_action  # noqa: F401,E402
from .scheduler_subs import _check_subscriptions_due  # noqa: F401,E402

log = get_logger(__name__)

_sched: AsyncIOScheduler | None = None
_state: dict[str, Any] = {
    "enabled": False,
    "report_time": "08:00",
    "last_run_at": None,
    "next_run_at": None,
    "last_error": None,
    "generated": 0,
}


from .scheduler_report import (  # noqa: F401,E402 — 对外同名导出
    REPORT_QUESTION,
    _parse_time,
    generate_report,
    has_data,
)


def _reschedule() -> None:
    global _sched
    if _sched is None:
        return
    _sched.remove_all_jobs()
    hm = _parse_time(_state.get("report_time"))
    h, m = hm if hm is not None else (8, 0)
    # skill 开关（设置→Agent）真正生效：morning_report 关闭时不再注册定时晨报
    # （手动「生成今日晨报」走 action 路径，不受影响）。
    # 注意：订阅到期巡检与晨报是两件独立的事（前者是提醒，后者是报告），
    # 关晨报不得连带关掉提醒——历史上这里提前 return 把它们绑死了。
    if not _state.get("report_enabled", True):
        _state["next_run_at"] = "（晨报已在设置中关闭）"
    elif hm is None:
        _sched.add_job(_cron_job, trigger="interval", minutes=1440, id="morning_report")
        _state["next_run_at"] = "（周期 24h 兜底）"
    else:
        _sched.add_job(
            _cron_job,
            CronTrigger(hour=h, minute=m, timezone="Asia/Shanghai"),
            id="morning_report",
        )
        _state["next_run_at"] = f"每天 {h:02d}:{m:02d}"
    # 订阅巡检始终按晨报时间点跑（未配置时间时用 08:00），与晨报开关无关
    _sched.add_job(
        _check_subscriptions_due,
        CronTrigger(hour=h, minute=m, timezone="Asia/Shanghai"),
        id="subs_due_check",
    )
    # 连接中心自动同步：公开数据源每小时刷新；账单收件箱每 10 分钟扫一次
    _sched.add_job(_sync_connect_sources, trigger="interval", minutes=60, id="connect_auto_sync")
    _sched.add_job(_scan_connect_inbox, trigger="interval", minutes=10, id="connect_inbox_scan")
    # 月末结账：每月 1 日 02:00 把上月草稿过账后关账（用户不需要点任何按钮）
    _sched.add_job(
        run_scheduled_month_end,
        CronTrigger(day=1, hour=2, minute=0, timezone="Asia/Shanghai"),
        id="month_end_close",
    )


async def _cron_job() -> None:
    try:
        await generate_report()
    except Exception as exc:  # noqa: BLE001
        # 不能让静默吞异常导致晨报连续失败 N 天无感知
        log.exception("cron job failed: %s", exc)
        _state["last_error"] = f"晨报生成失败: {exc}"
        _state["last_run_at"] = datetime.now().isoformat()


# ---------------------------------------------------------------------------
# 技能定时动作（设置 → Agent → 技能 action）：到点跑一遍问答管线并归档
# ---------------------------------------------------------------------------

_SKILL_JOB_PREFIX = "skill_action:"


async def _skill_action_job(skill_id: str) -> None:
    """调度到点：执行技能动作（走与手动触发同一条实现）。"""
    try:
        await run_skill_action(skill_id)
    except Exception as exc:  # noqa: BLE001 — 定时任务异常不炸调度器
        log.exception("skill action failed: %s", exc)
        _state["last_error"] = f"技能「{skill_id}」触发失败: {exc}"


async def sync_skill_jobs() -> None:
    """把启用中、带合法定时动作的技能同步进调度器（幂等：先清后建）。

    非法动作 / 服务停用 / 调度器未启动：静默跳过（保存侧已有 warning，dispatch 侧按策略跳过）。
    """
    global _sched
    if _sched is None:
        return
    # 先清掉全部技能任务（含已被删/停用/改配置的）
    for job in list(_sched.get_jobs()):
        if job.id.startswith(_SKILL_JOB_PREFIX):
            _sched.remove_job(job.id)
    try:
        from . import agent_config

        cfg = await agent_config.get_config()
    except Exception:  # noqa: BLE001 — 读配置失败不打断主流程
        return
    for sid, s in (cfg.get("skills") or {}).items():
        if not isinstance(s, dict) or not s.get("enabled", True):
            continue
        action = agent_config.normalize_skill_action(s.get("action"))
        if not action:
            continue
        h, m = (int(x) for x in action["time"].split(":"))
        days = action["weekdays"]
        try:
            if days:
                # APScheduler day_of_week 使用 mon-sun 名称；0=周一…6=周日 与 date.weekday() 一致
                names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
                dow = ",".join(names[d] for d in days)
                trigger = CronTrigger(day_of_week=dow, hour=h, minute=m, timezone="Asia/Shanghai")
            else:
                trigger = CronTrigger(hour=h, minute=m, timezone="Asia/Shanghai")
            _sched.add_job(_skill_action_job, trigger, id=f"{_SKILL_JOB_PREFIX}{sid}", args=[sid])
        except Exception as exc:  # noqa: BLE001 — 单个技能排程失败不影响其他
            log.warning("skill job add failed (%s): %s", sid, exc)


async def notify_settings_changed() -> None:
    """设置保存后调用：读最新报告时间与晨报开关，并重排（含技能任务）。"""
    st = await db.get_settings()
    _state["report_time"] = st.get("report_time", "08:00")
    try:
        from . import agent_config

        _state["report_enabled"] = await agent_config.is_skill_enabled("morning_report")
    except Exception:  # noqa: BLE001 — 配置读取失败按开启处理（宁多报不漏报）
        _state["report_enabled"] = True
    _reschedule()
    # _reschedule 会清空全部 job，因此技能任务需要在重排后重新同步（幂等）
    await sync_skill_jobs()


async def start() -> None:
    """启动调度器（幂等）。

    注意：_sched 是进程级全局，绑定到**启动它的那个事件循环**。
    若上一个循环已关闭而 _sched 没被清空，这里会误判"已在运行"直接 return，
    导致调度器实际是死的但 status 说 enabled —— 表现为测试里 start 后
    status 仍为 False，且日志里出现 "Event loop is closed"。
    因此先做一次存活检查：循环已关闭则丢弃残留实例重新创建。
    """
    global _sched
    if _sched is not None:
        loop = getattr(_sched, "_eventloop", None)
        if loop is None or not loop.is_closed():
            return
        # 残留实例属于已关闭的循环：它既不会触发任务，也无法安全 shutdown
        _sched = None
        _state["enabled"] = False
    st = await db.get_settings()
    _state["report_time"] = st.get("report_time", "08:00")
    try:
        from . import agent_config

        _state["report_enabled"] = await agent_config.is_skill_enabled("morning_report")
    except Exception:  # noqa: BLE001
        _state["report_enabled"] = True
    _sched = AsyncIOScheduler(timezone="Asia/Shanghai")
    _reschedule()
    await sync_skill_jobs()
    _sched.start()
    _state["enabled"] = True


async def stop() -> None:
    """停止调度器。必须保证 _sched 一定被清空。

    原实现把 shutdown() 放在赋值之前且没有 try/finally：当调度器所属的
    事件循环已关闭（测试里每个用例一个新 loop），shutdown 抛
    RuntimeError: Event loop is closed，`_sched = None` 永远执行不到，
    残留对象让下一个用例的 start() 直接 return —— 后续所有调度测试连锁失败。
    清理失败不能影响"已停止"这个事实，所以放 finally。
    """
    global _sched
    sched, _sched = _sched, None
    _state["enabled"] = False
    if sched is not None:
        try:
            sched.shutdown(wait=False)
        except Exception as e:  # noqa: BLE001 — 循环已关闭时无法优雅关停
            log.debug("scheduler.shutdown skipped: %s", e)


def status() -> dict[str, Any]:
    skill_jobs: list[str] = []
    if _sched is not None:
        try:
            skill_jobs = [
                job.id[len(_SKILL_JOB_PREFIX):]
                for job in _sched.get_jobs()
                if job.id.startswith(_SKILL_JOB_PREFIX)
            ]
        except Exception:  # noqa: BLE001 — 状态查询失败不影响主流程
            pass
    return {
        "enabled": _state["enabled"],
        "report_time": _state.get("report_time", "08:00"),
        "last_run_at": _state["last_run_at"],
        "next_run_at": _state["next_run_at"],
        "last_error": _state["last_error"],
        "generated": _state["generated"],
        "skill_jobs": skill_jobs,
    }
