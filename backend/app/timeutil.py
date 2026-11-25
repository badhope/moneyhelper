"""时间戳的单一实现：全后端只允许从这里取「当前时间」字符串。

## 为什么有这个文件

M1 拆分 db 层时，`_now()` / `_now_iso()` 被逐个复制进各模块，实测残留
**16 处同构定义**（12 处 `_now` + 4 处 `_now_iso`）。两份实现还漂移成了
两种格式：

    now_str()  →  "2026-11-19T16:10:00"        （naive，本地时间，无偏移）
    now_iso()  →  "2026-11-19T16:10:00+08:00"  （本地时间 + 时区偏移）

两者语义都是「本地当前时刻」，但字符串不同长。混写进同一列会让
`ORDER BY created_at` 的字符串排序错位（同秒内带 `+08:00` 的串更大），
也会让前端 `new Date()` 在不同接口拿到不同精度。

## 为什么不直接统一成一种

历史库里已经有两种格式并存，改格式必须配数据迁移（把旧值补成带偏移或
截掉偏移），否则排序与比较会出现新的错位。迁移单独排期；在那之前：

1. 实现只留一份（本文件），禁止再复制；
2. 新增代码一律用 `now_iso()`（带偏移，语义完整）；
3. 既有调用点保持原格式不变，避免「顺手改格式」引发的隐性回归。
"""

from __future__ import annotations

from datetime import datetime


def now_str() -> str:
    """本地时间，无时区偏移。格式：`2026-11-19T16:10:00`。

    仅用于既有调用点保持历史格式；新代码请用 `now_iso()`。
    """
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def now_iso() -> str:
    """本地时间 + 时区偏移。格式：`2026-11-19T16:10:00+08:00`。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def now_local() -> datetime:
    """带本地时区的 datetime；需要做时间比较（而不是存字符串）时用。"""
    return datetime.now().astimezone()


def new_id(prefix: str) -> str:
    """生成带前缀的短随机 ID（连接中心 / 深链模块历史各自复制过一份）。"""
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:12]}"
