"""备份恢复原语：把备份列表统一注入当前租户写回指定表，坏行汇总抛错。"""

from __future__ import annotations

from typing import Any

import aiosqlite

from .tenant import current_user_id


async def _restore_table(
    conn: aiosqlite.Connection,
    name: str,
    rows: Any,
    sql: str,
) -> int:
    """把备份列表写回指定表。

    统一注入当前租户：备份包本身不带 user_id（也不该带），恢复时一律落到
    当前登录用户名下。

    错误策略（专家评审 P0-7）：**不再静默跳过坏行**。旧实现 `except: continue`
    会让外键失败/字段不匹配的行悄悄消失，接口却返回 ok，用户以为恢复成功。
    现在收集失败行并在最后抛错，由调用方整体回滚。
    """
    if not isinstance(rows, list):
        return 0
    uid = current_user_id()
    n = 0
    failed: list[str] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            failed.append(f"#{idx}: 非对象")
            continue
        try:
            await conn.execute(sql, {**row, "user_id": uid})
            n += 1
        except Exception as exc:  # noqa: BLE001
            failed.append(f"#{idx}: {type(exc).__name__}: {exc}")
    if failed:
        raise ValueError(
            f"恢复 {name} 时有 {len(failed)} 行失败（已回滚）：" + "; ".join(failed[:3])
        )
    return n
