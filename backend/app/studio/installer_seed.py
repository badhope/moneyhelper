"""出厂预装与 MCP 配置漂移修复（启动时调用，失败不阻断启动）。"""

from __future__ import annotations

from typing import Any

from .. import mcp_client
from ..logging_utils import get_logger
from . import market, store

log = get_logger(__name__)


async def seed_default_bundle() -> dict[str, Any]:
    """首次启动的「出厂预装」：把市场里全部非 MCP 资产装好并启用。

    只跑一次（marketplace.seeded=true 后不再执行），因此用户之后删掉的条目
    不会被重启重新装回来。MCP 只写配置、保持停用：stdio 服务器依赖 npx/uvx，
    离线或未安装时启用会拖慢每轮问答。
    """
    cfg = await store.get_config()
    marketplace = cfg.setdefault("marketplace", {"installed": {}})
    if marketplace.get("seeded"):
        return {"seeded": False, "reason": "already"}
    installed = marketplace.setdefault("installed", {})
    saved = 0
    mcp_names: list[str] = []
    for item in market.catalog():
        if item["kind"] == "mcp":
            server = dict(item.get("server") or {})
            if not server.get("name"):
                continue
            raw = mcp_client.raw_servers()
            # 远程 HTTP MCP 默认启用（无本地运行时依赖）；stdio 需要 npx/uvx，
            # 缺失时每轮问答都要等一次启动失败，所以默认停用、由用户显式打开。
            default_on = bool(server.get("url"))
            if not any(e.get("name") == server.get("name") for e in raw):
                raw.append({**server, "enabled": default_on})
                try:
                    mcp_client.save_servers(raw)
                    mcp_names.append(str(server["name"]))
                except ValueError as exc:
                    log.warning("studio.seed mcp failed (%s): %s", item["id"], exc)
            installed[item["id"]] = {
                "kind": "mcp",
                "installed_at": store.now_iso(),
                "enabled": default_on,
            }
            continue
        if item["id"] in installed:
            continue
        try:
            asset = dict(item.get("asset") or {})
            asset.setdefault("enabled", True)
            # 市场条目不算「内置资产」：可自由删除（内置只指代码里随包分发的默认项）
            asset.setdefault("builtin", False)
            await store.upsert_asset(item["kind"], item["id"], asset)
            installed[item["id"]] = {
                "kind": item["kind"],
                "installed_at": store.now_iso(),
                "enabled": True,
            }
            saved += 1
        except Exception as exc:  # noqa: BLE001 — 单条失败不阻断出厂预装
            log.warning("studio.seed asset failed (%s): %s", item["id"], exc)
    marketplace["seeded"] = True
    await store.mutate_config(lambda c: c.update({"marketplace": marketplace}))
    log.info("studio.seed_default_bundle assets=%s mcp=%s", saved, len(mcp_names))
    return {"seeded": True, "assets": saved, "mcp_configured": mcp_names}


async def seed_domain_pack() -> dict[str, Any]:
    """补装「财务域内置包」：老库已过首次预装，仍要一次性补齐领域条目。

    只装一次（domain_finance 标记），之后用户删掉/关掉不会被重启复活。
    只处理 category 以「财务」开头的非 MCP 条目，不动科研资产。
    """
    cfg = await store.get_config()
    marketplace = cfg.setdefault("marketplace", {"installed": {}})
    if marketplace.get("domain_finance_seeded"):
        return {"seeded": False, "reason": "already"}
    installed = marketplace.setdefault("installed", {})
    saved = 0
    finance_mcp = {"mcp-aktools", "mcp-china-stock"}
    mcp_added: list[str] = []
    for item in market.catalog():
        if item["kind"] == "mcp":
            if item["id"] not in finance_mcp or item["id"] in installed:
                continue
            server = dict(item.get("server") or {})
            name = str(server.get("name") or "")
            raw = mcp_client.raw_servers()
            if name and not any(e.get("name") == name for e in raw):
                raw.append({**server, "enabled": False})
                try:
                    mcp_client.save_servers(raw)
                    mcp_added.append(name)
                except ValueError as exc:
                    log.warning("studio.seed finance mcp failed (%s): %s", item["id"], exc)
                    continue
            installed[item["id"]] = {
                "kind": "mcp",
                "installed_at": store.now_iso(),
                "enabled": False,
            }
            continue
        if item["id"] in installed:
            continue
        if not str(item.get("category") or "").startswith("财务"):
            continue
        try:
            asset = dict(item.get("asset") or {})
            asset.setdefault("enabled", True)
            asset.setdefault("builtin", False)
            await store.upsert_asset(item["kind"], item["id"], asset)
            installed[item["id"]] = {
                "kind": item["kind"],
                "installed_at": store.now_iso(),
                "enabled": True,
            }
            saved += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("studio.seed finance failed (%s): %s", item["id"], exc)
    marketplace["domain_finance_seeded"] = True
    await store.mutate_config(lambda c: c.update({"marketplace": marketplace}))
    log.info("studio.seed_domain_pack assets=%s mcp=%s", saved, mcp_added)
    return {"seeded": True, "assets": saved, "mcp": mcp_added}


async def repair_mcp_config() -> dict[str, Any]:
    """修复 MCP 配置漂移：已安装过的市场条目若从 mcp.json 里消失，重新补回。

    为什么需要单独一步：`mcp.json` 在 data/ 下、`seeded` 标记在 settings 表里，
    两者生命周期不同——用户删了 mcp.json（换机器/清数据）后 DB 仍认为「已预装」，
    MCP 就永远回不来了。只补 `installed` 里记录过的条目，不会复活用户主动卸载的。
    """
    cfg = await store.get_config()
    installed = (cfg.get("marketplace") or {}).get("installed") or {}
    if not installed:
        return {"repaired": []}
    raw = mcp_client.raw_servers()
    names = {str(e.get("name") or "") for e in raw}
    repaired: list[str] = []
    for item in market.catalog():
        if item["kind"] != "mcp" or item["id"] not in installed:
            continue
        server = dict(item.get("server") or {})
        name = str(server.get("name") or "")
        if not name or name in names:
            continue
        raw.append({**server, "enabled": bool(server.get("url"))})
        names.add(name)
        repaired.append(name)
    if repaired:
        try:
            mcp_client.save_servers(raw)
        except ValueError as exc:
            log.warning("studio.repair_mcp failed: %s", exc)
            return {"repaired": [], "error": str(exc)}
    return {"repaired": repaired}
