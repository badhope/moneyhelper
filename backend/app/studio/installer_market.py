"""市场资产的安装/推荐安装/卸载：改 config 里的 marketplace 与资产表。

从 installer.py 拆出；远程抓取仍在门面（测试会替换 `installer.httpx`）。
"""

from __future__ import annotations

from typing import Any

from .. import mcp_client
from ..logging_utils import get_logger
from . import market, store

log = get_logger(__name__)


async def install_market(item_id: str) -> dict[str, Any]:
    item = market.find(item_id)
    if item is None:
        raise ValueError(f"市场条目不存在：{item_id}")
    if item["kind"] == "mcp":
        server = dict(item.get("server") or {})
        if not server.get("url") and not server.get("command"):
            raise ValueError("该 MCP 条目缺少 server 配置")
        raw = mcp_client.raw_servers()
        default_on = bool(server.get("url"))
        for entry in raw:
            if entry.get("name") == server.get("name"):
                entry.update({**server, "enabled": default_on})
                break
        else:
            raw.append({**server, "enabled": default_on})
        mcp_client.save_servers(raw)
        await _record_install(item_id)
        return {
            "ok": True,
            "kind": "mcp",
            "installed": server.get("name"),
            "market_id": item_id,
            "note": (
                "MCP 已写入配置并启用（远程 HTTP）。"
                if default_on
                else "MCP 已写入配置但默认停用（stdio 依赖 npx/uvx）；请在「插件（MCP）」中启用。"
            ),
        }
    asset = dict(item.get("asset") or {})
    if not asset:
        raise ValueError("该市场条目缺少资产内容")
    asset.setdefault("enabled", True)
    saved = await store.upsert_asset(item["kind"], item["id"], asset)
    await _record_install(item_id)
    return {"ok": True, "kind": item["kind"], "id": item["id"], "name": saved.get("name", ""), "market_id": item_id}


async def install_recommended() -> dict[str, Any]:
    """安装推荐组合：全部非 MCP 资产 + 配置推荐 MCP（离线安全，MCP 需手动启用）。"""
    cfg = await store.get_config()
    installed = (cfg.setdefault("marketplace", {}).setdefault("installed", {}))
    saved: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    mcp_configured: list[str] = []
    for item in market.catalog():
        if item["kind"] == "mcp":
            if item["id"] in installed:
                continue
            try:
                server = dict(item.get("server") or {})
                raw = mcp_client.raw_servers()
                if not any(e.get("name") == server.get("name") for e in raw):
                    raw.append({**server, "enabled": False})
                    mcp_client.save_servers(raw)
                    mcp_configured.append(server.get("name", ""))
                installed[item["id"]] = {"kind": "mcp", "installed_at": store.now_iso(), "enabled": False}
            except Exception as exc:  # noqa: BLE001
                errors.append({"file": item["id"], "error": str(exc)})
            continue
        if item["id"] in installed:
            continue
        try:
            asset = dict(item.get("asset") or {})
            asset.setdefault("enabled", True)
            await store.upsert_asset(item["kind"], item["id"], asset)
            installed[item["id"]] = {"kind": item["kind"], "installed_at": store.now_iso(), "enabled": True}
            saved.append({"kind": item["kind"], "id": item["id"], "name": asset.get("name", "")})
        except Exception as exc:  # noqa: BLE001
            errors.append({"file": item["id"], "error": str(exc)})
    await store.mutate_config(lambda c: c.update({"marketplace": cfg["marketplace"]}))
    return {
        "ok": not errors,
        "saved": saved,
        "mcp_configured": mcp_configured,
        "errors": errors,
        "note": "MCP 服务器已写入配置但默认关闭，避免离线环境拖慢问答；可在「插件（MCP）」中逐个启用。",
    }


async def _record_install(item_id: str) -> None:
    def _apply(cfg):
        installed = cfg.setdefault("marketplace", {}).setdefault("installed", {})
        installed[item_id] = {"installed_at": store.now_iso()}

    await store.mutate_config(_apply)


async def uninstall_market(item_id: str) -> dict[str, Any]:
    item = market.find(item_id)
    if item is None:
        raise ValueError(f"市场条目不存在：{item_id}")
    cfg = await store.get_config()
    installed = (cfg.setdefault("marketplace", {}).setdefault("installed", {}))
    if item["kind"] == "mcp":
        server = item.get("server") or {}
        raw = [e for e in mcp_client.raw_servers() if e.get("name") != server.get("name")]
        mcp_client.save_servers(raw)
    else:
        try:
            await store.delete_asset(item["kind"], item["id"], force=True)
        except Exception as exc:  # noqa: BLE001 — 删除失败如实回报
            raise ValueError(str(exc)) from exc
    installed.pop(item_id, None)
    await store.mutate_config(lambda c: c.update({"marketplace": cfg["marketplace"]}))
    return {"ok": True, "uninstalled": item_id}
