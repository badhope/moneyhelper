"""4.23.0 电商经营测算：公式、阈值告警与场景保存。"""

from __future__ import annotations

import pytest
from app.calculations.ecommerce import calculate


def _base(**overrides) -> dict:
    data = {
        "gmv": 100000.0,
        "refunds": 5000.0,
        "orders": 1000,
        "commission_pct": 5.0,
        "payment_pct": 0.6,
        "ad_spend": 8000.0,
        "cogs": 45000.0,
        "fulfillment": 6000.0,
        "other_cost": 2000.0,
        "input_vat": 3000.0,
        "vat_rate_pct": 13.0,
        "surtax_pct": 12.0,
        "income_tax_pct": 25.0,
    }
    data.update(overrides)
    return data


def test_profitable_shop_numbers() -> None:
    out = calculate(_base())
    assert out["net_sales"] == 95000.0
    assert out["refund_rate"] == pytest.approx(0.05)
    assert out["platform_fee"] == 4750.0
    assert out["payment_fee"] == 570.0
    assert out["net_profit"] > 0
    assert out["breakeven_roas"] > 0
    assert out["per_order_profit"] > 0
    assert out["verdict"] in ("healthy", "thin")


def test_loss_and_warnings() -> None:
    out = calculate(_base(ad_spend=40000.0, cogs=60000.0))
    assert out["net_profit"] < 0
    assert out["verdict"] == "loss"
    assert any("亏损" in w["text"] for w in out["warnings"])


def test_rejects_refund_above_gmv() -> None:
    with pytest.raises(ValueError):
        calculate(_base(refunds=120000.0))


def test_rejects_negative_cost() -> None:
    with pytest.raises(ValueError):
        calculate(_base(cogs=-1.0))


def test_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError):
        calculate(_base(gmv=float("nan")))
    with pytest.raises(ValueError):
        calculate(_base(ad_spend=float("inf")))


@pytest.mark.asyncio
async def test_ecommerce_calculate_and_scenario_save(client) -> None:
    resp = await client.post("/api/ecommerce/calculate", json=_base())
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["net_sales"] == 95000.0

    saved = await client.post(
        "/api/ecommerce/scenarios",
        json={"name": "双十一方案", "input": _base(ad_spend=12000.0)},
    )
    assert saved.status_code == 200, saved.text
    item = saved.json()["item"]
    assert item["name"] == "双十一方案"
    assert item["result"]["net_profit"] > 0

    listed = await client.get("/api/ecommerce/scenarios")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == item["id"]

    deleted = await client.delete(f"/api/ecommerce/scenarios/{item['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


@pytest.mark.asyncio
async def test_ecommerce_invalid_input_returns_400(client) -> None:
    resp = await client.post("/api/ecommerce/calculate", json=_base(cogs=-1.0))
    assert resp.status_code == 400, resp.text
    assert "不能为负" in resp.json()["detail"]
