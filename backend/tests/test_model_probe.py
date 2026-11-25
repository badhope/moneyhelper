"""模型探测接口：/api/models/probe 的契约与失败降级（不真连外网）。"""

from __future__ import annotations

import pytest
from app.routes import status


class _FakeResp:
    status_code = 200

    def json(self):
        return {
            "data": [
                {"id": "glm-5.3-flash", "owned_by": "智谱"},
                {"id": "deepseek-v4.1-flash", "owned_by": "DeepSeek"},
                {"id": "", "owned_by": "脏数据"},
            ]
        }


class _FakeClient:
    def __init__(self, *a, **k):
        self.url = ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        self.url = url
        return _FakeResp()


@pytest.mark.asyncio
async def test_model_probe_filters_empty_ids(client, monkeypatch) -> None:
    monkeypatch.setattr(status.httpx, "AsyncClient", _FakeClient)
    r = await client.post(
        "/api/models/probe",
        json={"base_url": "https://api.qs.al/v1/", "api_key": "probe-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["count"] == 2  # 空 id 被过滤
    assert [m["id"] for m in body["models"]] == ["glm-5.3-flash", "deepseek-v4.1-flash"]


@pytest.mark.asyncio
async def test_model_probe_rejects_bad_scheme(client) -> None:
    r = await client.post("/api/models/probe", json={"base_url": "api.qs.al/v1"})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "http" in r.json()["error"]
