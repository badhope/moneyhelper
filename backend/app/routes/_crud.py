"""实体增删改的统一外壳 —— 「写库 → 记凭证 → 清缓存 → 返回」只写一遍。

## 为什么抽出来

`debts_subs.py` 的负债/订阅与 `goals.py` 的目标，六个端点是同一个模板抄出来的：
创建/更新/删除各自 20 行，差异只有 db 函数名、表名和 `action`/`entity_type` 字符串。
复制带来的真实问题不是行数，而是**忘记清缓存**：只要有一个端点漏掉
`invalidate_dashboard_cache()`，首页数字就会停在旧值，而接口返回成功 ——
用户看到的是"改完刷新没变化"，最难排查的一类 bug。

## 约定

- `before` / `after` 直接取整行快照（`SELECT * ... WHERE name = ?`），
  撤销功能靠它做 `INSERT OR REPLACE` 回滚，所以不能只记变更字段。
- 表名只来自调用方模块内的常量，不来自请求参数。
- 校验类异常统一映射 400；其余异常照常抛出，交给全局异常处理（500）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.responses import JSONResponse

from .. import analysis, db
from ..provenance import record_provenance


async def _snapshot(table: str, name: str) -> dict[str, Any] | None:
    row = await db.fetch_one(f"SELECT * FROM {table} WHERE name = ?", (name,))
    return dict(row) if row else None


async def create_entity(
    payload: dict,
    *,
    add: Callable[[dict], Any],
    action: str,
    entity_type: str,
) -> Any:
    name = str((payload or {}).get("name", "")).strip()
    try:
        out = await add(payload or {})
    except Exception as exc:  # noqa: BLE001 — 坏输入回 400，不落到 500
        return JSONResponse({"error": str(exc)}, status_code=400)
    await record_provenance(
        action=action,
        entity_type=entity_type,
        entity_id=name,
        before=None,
        after=payload or {},
        source="api",
    )
    analysis.invalidate_dashboard_cache()
    return out


async def update_entity(
    name: str,
    payload: dict,
    *,
    table: str,
    update: Callable[[str, dict], Any],
    action: str,
    entity_type: str,
) -> Any:
    before = await _snapshot(table, name)
    try:
        out = await update(name, payload or {})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    after = await _snapshot(table, name)
    await record_provenance(
        action=action,
        entity_type=entity_type,
        entity_id=name,
        before=before,
        after=after,
        source="api",
    )
    analysis.invalidate_dashboard_cache()
    return out


async def delete_entity(
    name: str,
    *,
    table: str,
    delete: Callable[[str], Any],
    action: str,
    entity_type: str,
) -> Any:
    before = await _snapshot(table, name)
    result = await delete(name)
    await record_provenance(
        action=action,
        entity_type=entity_type,
        entity_id=name,
        before=before,
        after=None,
        source="api",
    )
    analysis.invalidate_dashboard_cache()
    return result
