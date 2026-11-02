"""定时任务（APScheduler）：每日晨报 + 订阅到期巡检。

- 报告时间存 settings.report_time（HH:MM），保存设置后立即重排。
- 报告走同一条问答服务（确定性模板或模型），归档 thread_id='cron'。
- 订阅到期巡检：每天检查 subscriptions，7 天内到期的写入一条 user_memory
  （kind=subscription_due），前端在总览/设置记忆页用到；本月已提醒过的不再重复写。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import db, service
from .logging_utils import get_logger
from .provenance import record_provenance

log = get_logger(__name__)

REPORT_QUESTION = "帮我做一次全面体检：汇总我的组合、账本与财务目标的现状，只描述事实与风险提示，不给操作建议。"
# 订阅到期提前提醒天数；due_day 在 [today, today+SUBS_REMIND_WITHIN_DAYS] 区间内即生成提醒
SUBS_REMIND_WITHIN_DAYS = 7

_sched: AsyncIOScheduler | None = None
_state: dict[str, Any] = {
    "enabled": False,
    "report_time": "08:00",
    "last_run_at": None,
    "next_run_at": None,
    "last_error": None,
    "generated": 0,
}


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

    if not await has_data():
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
        _state["generated"] += 1
        _state["last_run_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _state["last_error"] = None
        # 记录晨报生成审计：审计失败不应把已生成的晨报标成失败
        try:
            await record_provenance(
                action="generate_morning_report",
                entity_type="report",
                entity_id="morning_report",
                before=None,
                after={"generated": _state["generated"], "thread_id": "cron"},
                source="scheduler",
                username="system",
            )
        except Exception as audit_exc:  # noqa: BLE001
            log.warning("morning report audit failed: %s", audit_exc)
        return result
    except Exception as exc:  # noqa: BLE001 — 晨报失败只记录，不炸服务
        _state["last_error"] = f"{type(exc).__name__}: {exc}"
        raise


async def _check_subscriptions_due() -> None:
    """检查 subscriptions.due_day：7 天内到期的写入 user_memory（kind=subscription_due）。
    每个自然月只写一条提醒（due_day 列表拼接），避免每日重复刷屏。"""
    subs = await db.list_subscriptions()
    if not subs:
        return
    today = datetime.now().astimezone().date()
    soon: list[dict[str, Any]] = []
    for s in subs:
        dd = (s.get("due_day") or "").strip()
        if not dd.isdigit():
            continue
        due_day = int(dd)
        if due_day < 1 or due_day > 31:
            continue
        # 本月 upcoming due date：取 [today, today+WINDOW] 区间内第一个合法的 due_day
        due_date = _upcoming_due_date(today, due_day)
        if due_date is None:
            continue
        days_until = (due_date - today).days
        if 0 <= days_until <= SUBS_REMIND_WITHIN_DAYS:
            soon.append(
                {
                    "name": s["name"],
                    "monthly": float(s.get("monthly") or 0),
                    "note": s.get("note", ""),
                    "due_day": due_day,
                    "due_date": due_date.isoformat(),
                    "days_until": days_until,
                }
            )
    if not soon:
        return
    soon.sort(key=lambda x: x["days_until"])
    month_key = today.strftime("%Y-%m")
    marker = f"subscription_due:{month_key}"
    # 本月首次写：先清旧月的同 marker，再写入（保证内容随 today 刷新但只保留一条）
    await db.delete_memory_by_kind(marker)
    total = 0.0
    bullets: list[str] = []
    for s_n in soon:
        when = "今天" if s_n["days_until"] == 0 else f"{s_n['days_until']} 天后"
        bullet = f"- **{s_n['name']}**：{s_n['monthly']:.2f} 元 / 月，{s_n['due_day']} 号扣款（{due_date_cn(s_n['due_date'])}，{when}）"
        if s_n["note"]:
            bullet += f" · {s_n['note']}"
        bullets.append(bullet)
        total += s_n["monthly"]
    content = "\n".join(
        [
            f"## 本月待缴订阅（{month_key}）",
            f"> 内部标记：{marker}",
            "",
            *bullets,
            "",
            f"**小计**：{len(soon)} 笔待缴，月度合计 {total:.2f} 元 / 月",
        ]
    )
    await db.add_memory(content, kind=marker)


def _upcoming_due_date(today, due_day: int) -> Any:
    """返回 upcomingdue date（本月或下月），限定在 today+WINDOW 内；None 表示不在窗口。"""
    candidate_this_month = _safe_date(today.year, today.month, due_day)
    window_end = today + timedelta(days=SUBS_REMIND_WITHIN_DAYS)
    if candidate_this_month is not None and today <= candidate_this_month <= window_end:
        return candidate_this_month
    # 下月候选
    y, m = today.year, today.month
    m2 = m + 1
    y2 = y
    if m2 > 12:
        m2 = 1
        y2 = y + 1
    candidate_next = _safe_date(y2, m2, due_day)
    if candidate_next is not None and today <= candidate_next <= window_end:
        return candidate_next
    return None


def _safe_date(year: int, month: int, day: int):
    from datetime import date as _date
    try:
        return _date(year, month, day)
    except ValueError:
        return None


def due_date_cn(iso: str) -> str:
    try:
        from datetime import date as _date
        d = _date.fromisoformat(iso)
        return f"{d.month} 月 {d.day} 日"
    except Exception:
        return iso


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


async def _sync_connect_sources() -> None:
    """后台自动同步「全自动」类连接（公开行情 / 基金净值）。

    只碰 automation=auto 且未停用的连接：登录类连接需要用户在场，
    绝不在后台凭空消耗配对码。单条失败只记日志，不影响其他连接。
    """
    try:
        from . import connect

        for conn in await connect.list_connections():
            if conn["status"] == "disabled":
                continue
            connector = connect.get_connector(conn["connector_id"]) or {}
            if connector.get("automation") != "auto":
                continue
            try:
                await connect.sync_connection(conn["id"])
            except Exception as exc:  # noqa: BLE001 — 单条同步失败不阻断调度
                log.warning("connect.auto_sync_failed id=%s err=%s", conn["id"], exc)
    except Exception as exc:  # noqa: BLE001 — 调度任务失败不能炸服务
        log.warning("connect.auto_sync crashed: %s", exc)


async def _scan_connect_inbox() -> None:
    """后台自动扫描账单收件箱：用户只需把官方导出的 CSV 放进去。"""
    try:
        from . import connect

        out = await connect.scan_import_inbox()
        if out.get("imported"):
            log.info("connect.inbox_auto_imported n=%s", out["imported"])
    except Exception as exc:  # noqa: BLE001
        log.warning("connect.inbox_scan crashed: %s", exc)


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


async def run_skill_action(skill_id: str) -> dict[str, Any]:
    """执行一次技能动作：走标准问答管线 → 归档到 thread=skill:<id>（不进会话列表）。

    供「立即触发」端点与定时任务共用；失败抛 ValueError（调用方转 400 / 记 last_error）。
    """
    from . import agent_config
    from . import service as service_mod

    cfg = await agent_config.get_config()
    skill = (cfg.get("skills") or {}).get(skill_id)
    if not isinstance(skill, dict):
        raise ValueError("技能不存在")
    if not skill.get("enabled", True):
        raise ValueError("技能已停用")
    action = agent_config.normalize_skill_action(skill.get("action"))
    if not action:
        raise ValueError("该技能没有可执行的定时动作")

    prompt = action["prompt"]
    thread_id = f"skill:{skill_id}"

    async def emit(_ev: dict[str, Any]) -> None:
        pass

    result = await service_mod.run_question(prompt, emit, thread_id=thread_id)
    await db.save_run(
        thread_id=thread_id,
        question=prompt,
        answer=result["answer"],
        level=result["level"],
        flags=result["flags"],
        route=result.get("route", ""),
        llm=result.get("llm", ""),
        route_reason=result.get("route_reason", ""),
        # 系统归档不进会话列表（与晨报一致）；历史按 thread_id 读
        skip_session=True,
    )
    # 审计链：技能触发属于"自动产生的金额相关产出"，可溯源
    try:
        await record_provenance(
            action="skill_action_fired",
            entity_type="skill",
            entity_id=skill_id,
            before=None,
            after={"thread_id": thread_id, "time": action["time"]},
            source="scheduler",
            username="system",
        )
    except Exception as exc:  # noqa: BLE001 — 审计失败不影响触发结果
        log.warning("skill action audit failed: %s", exc)
    return {
        "ok": True,
        "skill_id": skill_id,
        "thread_id": thread_id,
        "answer": result["answer"],
        "level": result["level"],
    }


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
    global _sched
    if _sched is not None:
        return
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
    global _sched
    if _sched is not None:
        _sched.shutdown(wait=False)
    _sched = None
    _state["enabled"] = False


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
