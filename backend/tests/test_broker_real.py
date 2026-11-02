"""v4.7 真券商通道测试：凭据 vault 加密、打码、适配器 probe 与路由配置。

测试使用 conftest 的 VAULT_PASSPHRASE；不写任何真实 API Key。
"""

from __future__ import annotations

import httpx
import pytest
from app import broker_adapter as ba
from app import db, main, vault


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    yield


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


async def test_broker_credentials_saved_encrypted_and_masked(temp_db) -> None:
    saved = await db.broker_save_credentials(
        "futu",
        {"app_key": "demo-key", "app_secret": "demo-secret", "access_token": "demo-token"},
        label="富途测试",
        meta={"market": "HK"},
        enabled=False,
    )
    assert saved["broker_id"] == "futu"
    assert saved["configured"] is True
    assert saved["meta"]["market"] == "HK"
    masked = await db.broker_list_credentials()
    assert len(masked) == 1
    assert "secret" not in str(masked[0]).lower()
    assert "demo-key" not in str(masked)
    secret = await db.broker_get_secret("futu")
    assert secret == {"app_key": "demo-key", "app_secret": "demo-secret", "access_token": "demo-token"}


async def test_broker_credential_delete(temp_db) -> None:
    await db.broker_save_credentials("longport", {"app_key": "key"})
    assert await db.broker_delete_credentials("longport") is True
    assert await db.broker_get_secret("longport") is None
    assert await db.broker_delete_credentials("longport") is False


async def test_broker_credential_rejects_unknown_and_empty(temp_db) -> None:
    with pytest.raises(ValueError):
        await db.broker_save_credentials("fake", {"x": "y"})
    with pytest.raises(ValueError):
        await db.broker_save_credentials("futu", {})


async def test_broker_credential_fail_closed_without_vault(temp_db, monkeypatch) -> None:
    monkeypatch.setattr(vault, "is_active", lambda: False)
    with pytest.raises(RuntimeError, match="拒绝保存"):
        await db.broker_save_credentials("ibkr", {"host": "127.0.0.1"})


async def test_adapter_registry_contains_real_channels() -> None:
    ids = {x["id"] for x in ba.list_adapters()}
    assert {"null", "paper", "xtquant", "easytrader", "futu", "longport", "tiger", "ibkr"}.issubset(ids)
    for cls in (ba.FutuBroker, ba.LongPortBroker, ba.TigerBroker, ba.IBKRBroker):
        assert cls is not None
        info = cls().probe()
        assert "available" in info and "supports_trading" in info and "problems" in info


async def test_configure_broker_route_masks_secret(client) -> None:
    response = await client.put(
        "/api/execute/brokers/futu/credentials",
        json={
            "label": "demo",
            "enabled": False,
            "secret": {"app_key": "demo-route-key", "app_secret": "demo-route-secret"},
            "meta": {"market": "HK"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "demo-route-secret" not in str(body)
    status = await client.get("/api/execute/status")
    futu = next(a for a in status.json()["adapters"] if a["id"] == "futu")
    assert futu["configured"] is True
    assert futu["meta"]["market"] == "HK"


async def test_configure_unknown_broker_route(client) -> None:
    response = await client.put(
        "/api/execute/brokers/not-real/credentials",
        json={"secret": {"key": "x"}},
    )
    assert response.status_code == 400


async def test_configured_broker_route_only_returns_masked(client) -> None:
    await client.put(
        "/api/execute/brokers/longport/credentials",
        json={"secret": {"app_key": "long-key", "access_token": "long-token"}},
    )
    response = await client.get("/api/execute/brokers/configured")
    assert response.status_code == 200
    text = response.text
    assert "long-key" not in text and "long-token" not in text
    assert response.json()["items"][0]["configured"] is True


async def test_adapter_connect_without_credentials_reports_actionable_error(client) -> None:
    response = await client.post("/api/execute/adapters/longport/connect")
    assert response.status_code in (400, 502)
    assert "配置" in response.json()["error"] or "连接" in response.json()["error"]
