"""订阅到期巡检：7 天内扣款的订阅写入一条 user_memory，每月去重。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from . import db

SUBS_REMIND_WITHIN_DAYS = 7


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
