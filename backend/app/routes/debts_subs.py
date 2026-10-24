"""负债与订阅路由：CRUD 操作（db 层 undo 快照由调用方经由 undo endpoint 触发）。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import analysis, db
from ..provenance import record_provenance

router = APIRouter()


# ---------------------------------------------------------------------------
# 负债
# ---------------------------------------------------------------------------


@router.post("/api/debts")
async def create_debt(payload: dict) -> dict:
    name = str((payload or {}).get("name", "")).strip()
    try:
        out = await db.add_debt(payload or {})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    await record_provenance(
        action="create_debt",
        entity_type="debt",
        entity_id=name,
        before=None,
        after=payload or {},
        source="api",
    )
    analysis.invalidate_dashboard_cache()
    return out


@router.delete("/api/debts/{name}")
async def remove_debt(name: str) -> dict:
    before_row = await db.fetch_one("SELECT * FROM debts WHERE name = ?", (name,))
    before = dict(before_row) if before_row else None
    result = await db.delete_debt(name)
    await record_provenance(
        action="delete_debt",
        entity_type="debt",
        entity_id=name,
        before=before,
        after=None,
        source="api",
    )
    analysis.invalidate_dashboard_cache()
    return result


# ---------------------------------------------------------------------------
# 订阅
# ---------------------------------------------------------------------------


@router.post("/api/subscriptions")
async def create_subscription(payload: dict) -> dict:
    name = str((payload or {}).get("name", "")).strip()
    try:
        out = await db.add_subscription(payload or {})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    await record_provenance(
        action="create_subscription",
        entity_type="subscription",
        entity_id=name,
        before=None,
        after=payload or {},
        source="api",
    )
    analysis.invalidate_dashboard_cache()
    return out


@router.delete("/api/subscriptions/{name}")
async def remove_subscription(name: str) -> dict:
    before_row = await db.fetch_one("SELECT * FROM subscriptions WHERE name = ?", (name,))
    before = dict(before_row) if before_row else None
    result = await db.delete_subscription(name)
    await record_provenance(
        action="delete_subscription",
        entity_type="subscription",
        entity_id=name,
        before=before,
        after=None,
        source="api",
    )
    analysis.invalidate_dashboard_cache()
    return result
