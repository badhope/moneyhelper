"""电商经营测算 API（4.23.0）。

计算是纯函数，保存场景只存输入与结果，不把测算当真实账务。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..auth import get_current_user
from ..calculations.ecommerce import calculate
from .gl import gl_read_scope, gl_write_scope

router = APIRouter(dependencies=[Depends(get_current_user)])


class EcommerceIn(BaseModel):
    gmv: float = 0.0
    refunds: float = 0.0
    orders: int = 0
    commission_pct: float = 5.0
    payment_pct: float = 0.6
    ad_spend: float = 0.0
    cogs: float = 0.0
    fulfillment: float = 0.0
    other_cost: float = 0.0
    input_vat: float = 0.0
    vat_rate_pct: float = 13.0
    surtax_pct: float = 12.0
    income_tax_pct: float = 25.0


class ScenarioIn(BaseModel):
    name: str = ""
    input: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/ecommerce/calculate")
async def ecommerce_calculate(body: EcommerceIn, _: int = Depends(gl_read_scope)):
    try:
        result = calculate(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"input": body.model_dump(), "result": result}


@router.get("/api/ecommerce/scenarios")
async def ecommerce_scenarios(limit: int = 30, _: int = Depends(gl_read_scope)):
    return {"items": await db.ecommerce_list_scenarios(limit)}


@router.post("/api/ecommerce/scenarios")
async def ecommerce_save_scenario(body: ScenarioIn, _: int = Depends(gl_write_scope)):
    try:
        result = calculate(body.input)
        item = await db.ecommerce_save_scenario(body.name, body.input, result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.delete("/api/ecommerce/scenarios/{scenario_id}")
async def ecommerce_delete_scenario(
    scenario_id: int, _: int = Depends(gl_write_scope)
):
    deleted = await db.ecommerce_delete_scenario(scenario_id)
    return {"deleted": deleted}
