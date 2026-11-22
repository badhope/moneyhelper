"""远程控制：一次性配对、设备 cookie、撤销、刷新失效。"""

from __future__ import annotations

import urllib.parse

import httpx
import pytest
from app import main


@pytest.fixture
async def owner(_temp_db, monkeypatch):
    async def _snap(positions):
        return {p["symbol"]: float(p["last"]) for p in positions}

    from app import quotes as quotes_mod

    monkeypatch.setattr(quotes_mod, "live_quotes", _snap)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


@pytest.fixture
async def phone(_temp_db, monkeypatch):
    async def _snap(positions):
        return {p["symbol"]: float(p["last"]) for p in positions}

    from app import quotes as quotes_mod

    monkeypatch.setattr(quotes_mod, "live_quotes", _snap)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


async def test_remote_pair_then_control_and_stop(owner, phone) -> None:
    create = await owner.post("/api/remote/sessions", json={"label": "我的手机"})
    assert create.status_code == 200, create.text
    data = create.json()
    assert data["qr_svg"].startswith("data:image/svg+xml;base64,")
    assert "#s=" in data["pair_url"] and "&t=" in data["pair_url"]
    assert data["warning"]  # 回环地址必须给出不能扫码的警告

    frag = urllib.parse.urlsplit(data["pair_url"]).fragment
    params = urllib.parse.parse_qs(frag)
    sid = params["s"][0]
    token = params["t"][0]

    paired = await phone.post("/api/remote/pair", json={"sid": sid, "token": token})
    assert paired.status_code == 200, paired.text
    assert paired.json()["redirect"] == "/?remote=1"
    assert phone.cookies.get("mh_remote")

    me = await phone.get("/api/remote/me")
    assert me.status_code == 200
    assert me.json()["remote"] is True
    assert me.json()["sid"] == sid

    # 同一个 cookie 能读真实账本，说明不是只换了个空壳页面
    dash = await phone.get("/api/dashboard")
    assert dash.status_code == 200
    assert "totals" in dash.json()

    stopped = await owner.post(f"/api/remote/sessions/{sid}/stop")
    assert stopped.status_code == 200 and stopped.json()["ok"] is True

    after = await phone.get("/api/dashboard")
    assert after.status_code == 401


async def test_pair_token_is_single_use(owner, phone) -> None:
    data = (await owner.post("/api/remote/sessions", json={})).json()
    frag = urllib.parse.parse_qs(urllib.parse.urlsplit(data["pair_url"]).fragment)
    sid, token = frag["s"][0], frag["t"][0]

    first = await phone.post("/api/remote/pair", json={"sid": sid, "token": token})
    assert first.status_code == 200
    second = await phone.post("/api/remote/pair", json={"sid": sid, "token": token})
    assert second.status_code == 410


async def test_refresh_rotates_and_kicks_device(owner, phone) -> None:
    data = (await owner.post("/api/remote/sessions", json={})).json()
    frag = urllib.parse.parse_qs(urllib.parse.urlsplit(data["pair_url"]).fragment)
    sid, token = frag["s"][0], frag["t"][0]
    assert (await phone.post("/api/remote/pair", json={"sid": sid, "token": token})).status_code == 200

    rotated = await owner.post(f"/api/remote/sessions/{sid}/refresh")
    assert rotated.status_code == 200
    new = rotated.json()
    assert new["pair_url"] != data["pair_url"]
    assert "&t=" in new["pair_url"]

    # 旧设备立刻掉线，旧链接也不能再换设备
    assert (await phone.get("/api/dashboard")).status_code == 401
    old = await phone.post("/api/remote/pair", json={"sid": sid, "token": token})
    assert old.status_code == 410


async def test_public_url_is_used_in_link(owner) -> None:
    saved = await owner.put(
        "/api/remote/config",
        json={"public_url": "https://money.example.com", "session_hours": 24},
    )
    assert saved.status_code == 200, saved.text
    data = (await owner.post("/api/remote/sessions", json={})).json()
    assert data["pair_url"].startswith("https://money.example.com/remote#")
    assert data["warning"] == ""
