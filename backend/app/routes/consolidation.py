"""多主体管理合并 API（4.18.0）。

路由只做参数清洗与响应组装；集团所有权、主体成员资格、借贷平衡由
`db/consolidation.py` 校验。所有接口都是显式人工动作，合并报表只读。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import db
from ..auth import get_current_user
from ..db.tenant import current_user_id
from ..provenance import record_provenance
from ._responses import bad as _bad

router = APIRouter(dependencies=[Depends(get_current_user)])


def _uid() -> int:
    return int(current_user_id())


@router.get("/api/consolidation/groups")
async def consolidation_groups() -> Any:
    groups = await db.consolidation_list_groups(_uid())
    return {
        "groups": groups,
        "count": len(groups),
        "boundary": "集团仅创建者可见可管；合并范围不跨用户授权边界。",
    }


@router.post("/api/consolidation/groups")
async def consolidation_group_create(payload: dict[str, Any]) -> Any:
    body = payload or {}
    try:
        group = await db.consolidation_create_group(_uid(), body.get("name"))
    except ValueError as exc:
        return _bad(str(exc))
    await record_provenance(
        "consolidation_group_create", "tenant_group", str(group["id"]),
        after={"name": group["name"]}, source="api",
    )
    return {"ok": True, "group": group}


@router.get("/api/consolidation/groups/{group_id}")
async def consolidation_group_detail(group_id: str) -> Any:
    try:
        data = await db.consolidation_group_detail(_uid(), group_id)
    except ValueError as exc:
        return _bad(str(exc), 404)
    data["candidates"] = await db.consolidation_entity_tenants(_uid(), group_id)
    return data


@router.delete("/api/consolidation/groups/{group_id}")
async def consolidation_group_delete(group_id: str) -> Any:
    try:
        out = await db.consolidation_delete_group(group_id, _uid())
    except ValueError as exc:
        return _bad(str(exc), 404)
    await record_provenance(
        "consolidation_group_delete", "tenant_group", str(group_id),
        after={"status": "deleted"}, source="api",
    )
    return out


@router.get("/api/consolidation/groups/{group_id}/candidates")
async def consolidation_candidates(group_id: str) -> Any:
    try:
        rows = await db.consolidation_entity_tenants(_uid(), group_id)
    except ValueError as exc:
        return _bad(str(exc), 404)
    return {"entities": rows, "count": len(rows)}


@router.post("/api/consolidation/groups/{group_id}/entities")
async def consolidation_entity_add(group_id: str, payload: dict[str, Any]) -> Any:
    body = payload or {}
    try:
        entity = await db.consolidation_add_entity(
            _uid(), group_id,
            tenant_id=body.get("tenant_id"),
            ownership_pct=body.get("ownership_pct", 100),
            method=body.get("method", "full"),
        )
    except ValueError as exc:
        return _bad(str(exc))
    await record_provenance(
        "consolidation_entity_add", "tenant_group_entity",
        f"{group_id}:{entity['tenant_id']}",
        after={
            "tenant_id": entity["tenant_id"],
            "ownership_pct": entity["ownership_pct"],
            "method": entity["method"],
        },
        source="api",
    )
    return {"ok": True, "entity": entity}


@router.post("/api/consolidation/groups/{group_id}/entities/new")
async def consolidation_entity_create(group_id: str, payload: dict[str, Any]) -> Any:
    body = payload or {}
    try:
        entity = await db.consolidation_create_entity(
            _uid(), group_id,
            name=body.get("name"),
            ownership_pct=body.get("ownership_pct", 100),
            method=body.get("method", "full"),
        )
    except ValueError as exc:
        return _bad(str(exc))
    await record_provenance(
        "consolidation_entity_create", "tenant",
        str(entity["tenant_id"]),
        after={
            "name": entity["tenant_name"],
            "group_id": group_id,
            "ownership_pct": entity["ownership_pct"],
            "method": entity["method"],
        },
        source="api",
    )
    return {"ok": True, "entity": entity}


@router.delete("/api/consolidation/groups/{group_id}/entities/{tenant_id}")
async def consolidation_entity_remove(group_id: str, tenant_id: int) -> Any:
    try:
        out = await db.consolidation_remove_entity(_uid(), group_id, tenant_id)
    except ValueError as exc:
        return _bad(str(exc), 404)
    await record_provenance(
        "consolidation_entity_remove", "tenant_group_entity", f"{group_id}:{tenant_id}",
        after={"removed": True}, source="api",
    )
    return out


@router.get("/api/consolidation/groups/{group_id}/report")
async def consolidation_report(group_id: str, period: str) -> Any:
    try:
        return await db.consolidation_report(_uid(), group_id, period)
    except ValueError as exc:
        return _bad(str(exc))


@router.get("/api/consolidation/groups/{group_id}/adjustments")
async def consolidation_adjustments(group_id: str, period: str | None = None) -> Any:
    try:
        rows = await db.consolidation_list_adjustments(_uid(), group_id, period)
    except ValueError as exc:
        return _bad(str(exc))
    return {
        "adjustments": rows,
        "count": len(rows),
        "boundary": "抵销分录按月保存，借贷必须平衡；只影响合并报表，不回写任何主体。",
    }


@router.post("/api/consolidation/groups/{group_id}/adjustments")
async def consolidation_adjustment_create(group_id: str, payload: dict[str, Any]) -> Any:
    body = payload or {}
    try:
        out = await db.consolidation_create_adjustment(
            _uid(), group_id,
            period=body.get("period"),
            description=body.get("description"),
            lines=body.get("lines"),
        )
    except ValueError as exc:
        return _bad(str(exc))
    await record_provenance(
        "consolidation_adjustment_create", "consolidation_adjustment",
        str(out["voucher_id"]),
        after={
            "group_id": group_id,
            "period": out["period"],
            "debit_cents": out["debit_cents"],
            "credit_cents": out["credit_cents"],
            "lines": len(out["lines"]),
        },
        source="api",
    )
    return {"ok": True, "adjustment": out}


@router.delete("/api/consolidation/groups/{group_id}/adjustments/{voucher_id}")
async def consolidation_adjustment_delete(group_id: str, voucher_id: str) -> Any:
    try:
        out = await db.consolidation_delete_adjustment(_uid(), group_id, voucher_id)
    except ValueError as exc:
        return _bad(str(exc), 404)
    await record_provenance(
        "consolidation_adjustment_delete", "consolidation_adjustment", str(voucher_id),
        after={"deleted": True}, source="api",
    )
    return out
