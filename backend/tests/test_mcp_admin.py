"""MCP 服务器管理：增删、校验、凭据打码、探活。

背景：此前只能手改 backend/data/mcp.json，格式错误一处整份配置静默失效；
且 URL 里的 token 会在设置页明文回显。
"""

from __future__ import annotations

import json

import pytest
from app import mcp_client


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """把配置指向临时文件，避免污染仓库内的 data/mcp.json。"""
    p = tmp_path / "mcp.json"
    monkeypatch.setattr(mcp_client, "MCP_CFG", p)
    monkeypatch.setattr(mcp_client, "_discover_cache", None)
    mcp_client._servers.clear()
    yield p
    mcp_client._servers.clear()


def test_save_and_list_roundtrip(cfg) -> None:
    mcp_client.save_servers([{"name": "a", "url": "https://a.example/mcp"}])
    servers = mcp_client.list_servers()
    assert [s["name"] for s in servers] == ["a"]
    assert json.loads(cfg.read_text(encoding="utf-8"))["servers"][0]["name"] == "a"


def test_duplicate_name_rejected(cfg) -> None:
    with pytest.raises(ValueError, match="重复"):
        mcp_client.save_servers(
            [
                {"name": "dup", "url": "https://a.example/mcp"},
                {"name": "dup", "url": "https://b.example/mcp"},
            ]
        )


def test_non_http_url_rejected(cfg) -> None:
    with pytest.raises(ValueError, match="http"):
        mcp_client.save_servers([{"name": "x", "url": "file:///etc/passwd"}])


def test_incomplete_entries_skipped(cfg) -> None:
    """缺 name 或 url 的草稿被跳过，而不是让整份配置失效。"""
    cleaned = mcp_client.save_servers(
        [
            {"name": "", "url": "https://a.example/mcp"},
            {"name": "b", "url": ""},
            {"name": "c", "url": "https://c.example/mcp"},
        ]
    )
    assert [s["name"] for s in cleaned] == ["c"]


def test_credentials_redacted_in_listing(cfg) -> None:
    mcp_client.save_servers(
        [{"name": "secret", "url": "https://user:tok-123@example.com/mcp"}]
    )
    shown = mcp_client.list_servers()[0]["url"]
    assert "tok-123" not in shown
    assert shown == "https://***@example.com/mcp"


def test_redact_url_without_credentials() -> None:
    assert mcp_client.redact_url("https://example.com/mcp") == "https://example.com/mcp"


def test_save_clears_discover_cache(cfg, monkeypatch) -> None:
    """保存后必须让发现缓存失效，否则新工具要等 30s 才可见。"""
    monkeypatch.setattr(mcp_client, "_discover_cache", (0.0, "stale", []))
    mcp_client.save_servers([{"name": "a", "url": "https://a.example/mcp"}])
    assert mcp_client._discover_cache is None


def test_broken_config_returns_empty(cfg) -> None:
    cfg.write_text("{not json", encoding="utf-8")
    assert mcp_client.list_servers() == []


def test_enabled_flag_roundtrip(cfg) -> None:
    """启停标记要持久化，且停用项不出现在 _load_config（不参与发现）。"""
    mcp_client.save_servers(
        [
            {"name": "on", "url": "https://a.example/mcp", "enabled": True},
            {"name": "off", "url": "https://b.example/mcp", "enabled": False},
        ]
    )
    active = mcp_client._load_config()
    assert [s["name"] for s in active] == ["on"]
    listed = mcp_client.list_servers()
    assert {s["name"]: s["enabled"] for s in listed} == {"on": True, "off": False}


def test_stdio_entry_saved_and_loaded(cfg) -> None:
    mcp_client.save_servers(
        [{"name": "local", "command": "npx", "args": ["-y", "pkg"], "enabled": True}]
    )
    entry = mcp_client._load_config()[0]
    assert entry["command"] == "npx" and entry["args"] == ["-y", "pkg"]


def test_stdio_requires_command(cfg) -> None:
    """既没有 url 也没有 command 的条目被跳过，不会写出坏配置。"""
    cleaned = mcp_client.save_servers([{"name": "broken"}])
    assert cleaned == []


def test_set_server_enabled(cfg) -> None:
    mcp_client.save_servers([{"name": "a", "url": "https://a.example/mcp", "enabled": True}])
    mcp_client.set_server_enabled("a", False)
    assert mcp_client.list_servers()[0]["enabled"] is False
    with pytest.raises(ValueError, match="不存在"):
        mcp_client.set_server_enabled("nope", True)
