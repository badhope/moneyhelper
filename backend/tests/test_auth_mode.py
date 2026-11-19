"""健康检查的 auth_mode：让前端能明确告诉用户"这个实例要不要口令"。

背景：设置页的「访问口令」只能写"后端同时设置 API_TOKEN 才生效"，
用户填完根本不知道是否生效。health 现在返回 token / accounts / local 三态。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
async def _auto_temp_db(temp_db):
    """保持原文件的 autouse 语义：本文件每个用例都跑在临时库上。

    `_temp_db` 转发版已收敛到 conftest；此处只保留「自动生效」这一行为差异。
    """
    yield


async def test_auth_mode_local_when_no_users(client, monkeypatch) -> None:
    monkeypatch.delenv("API_TOKEN", raising=False)
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["auth_mode"] == "local"


async def test_auth_mode_token_when_env_set(client, monkeypatch) -> None:
    monkeypatch.setenv("API_TOKEN", "secret-token-123")
    r = await client.get("/api/health")
    # /api/health 在免鉴权白名单里，因此即使设了口令也应能读到状态
    assert r.status_code == 200
    assert r.json()["auth_mode"] == "token"


async def test_auth_mode_accounts_after_register(client, monkeypatch) -> None:
    monkeypatch.delenv("API_TOKEN", raising=False)
    from app import auth

    auth._ensure_secret()
    await auth.register(auth.RegisterReq(username="healthprobe", password="probe-pass-123"))
    r = await client.get("/api/health")
    assert r.json()["auth_mode"] == "accounts"
