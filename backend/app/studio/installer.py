"""Studio 安装器：从内置市场 / 远程 URL 安装资产，以及组装 MCP 配置。"""

from __future__ import annotations

import base64
import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from .. import mcp_client
from ..logging_utils import get_logger
from . import importer, market, store

log = get_logger(__name__)

MAX_REMOTE_BYTES = 1024 * 1024
_GITHUB_BLOB = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/(?:blob|tree)/([^/]+)/(.+)$", re.I
)
_GITHUB_REPO = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/?$", re.I)


def _github_api_url(url: str) -> str | None:
    m = _GITHUB_BLOB.match(url)
    if not m:
        return None
    owner, repo, ref, path = m.groups()
    return f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"


async def fetch_remote_text(url: str) -> tuple[str, str]:
    """抓取远程文件，返回 (filename, text)。GitHub blob 走 contents API（raw 域名常被墙）。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL 必须以 http:// 或 https:// 开头")
    api = _github_api_url(url)
    target = api or url
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "moneyhelper-studio"}
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(target, headers=headers)
        if resp.status_code >= 400:
            raise ValueError(f"下载失败：HTTP {resp.status_code}")
        if len(resp.content) > MAX_REMOTE_BYTES:
            raise ValueError("远程文件超过 1 MB 上限")
        if api:
            data = resp.json()
            if isinstance(data, dict) and data.get("encoding") == "base64":
                raw = base64.b64decode(data.get("content") or "")
                name = str(data.get("name") or "remote.md")
                return name, raw.decode("utf-8", errors="replace")
            raise ValueError("GitHub 返回的不是单个文件（目录请用 zip 或逐个文件 URL）")
        name = parsed.path.rsplit("/", 1)[-1] or "remote.md"
        return name, resp.text


async def install_remote(url: str, default_kind: str | None = None) -> dict[str, Any]:
    name, text = await fetch_remote_text(url)
    entries = importer.parse_file(text.encode("utf-8"), name, default_kind)
    return await _apply_entries(entries, source=url)


async def _apply_entries(entries: list[dict[str, Any]], *, source: str) -> dict[str, Any]:
    saved: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for entry in entries:
        if "__zip_errors__" in entry:
            errors.extend(entry["__zip_errors__"])
            continue
        try:
            asset = await store.upsert_asset(entry["kind"], entry["id"], entry["asset"])
            saved.append({"kind": entry["kind"], "id": entry["id"], "name": asset.get("name", "")})
        except Exception as exc:  # noqa: BLE001 — 单条失败不拖累整包
            errors.append({"file": entry.get("source") or source, "error": str(exc)})
    return {"ok": not errors or bool(saved), "saved": saved, "errors": errors, "source": source}


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
    installed = cfg.setdefault("marketplace", {}).setdefault("installed", {})
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
    await store.save_config(cfg)
    return {
        "ok": not errors,
        "saved": saved,
        "mcp_configured": mcp_configured,
        "errors": errors,
        "note": "MCP 服务器已写入配置但默认关闭，避免离线环境拖慢问答；可在「插件（MCP）」中逐个启用。",
    }


async def _record_install(item_id: str) -> None:
    cfg = await store.get_config()
    installed = cfg.setdefault("marketplace", {}).setdefault("installed", {})
    installed[item_id] = {"installed_at": store.now_iso()}
    await store.save_config(cfg)


async def uninstall_market(item_id: str) -> dict[str, Any]:
    item = market.find(item_id)
    if item is None:
        raise ValueError(f"市场条目不存在：{item_id}")
    cfg = await store.get_config()
    installed = cfg.setdefault("marketplace", {}).setdefault("installed", {})
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
    await store.save_config(cfg)
    return {"ok": True, "uninstalled": item_id}


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
    await store.save_config(cfg)
    log.info("studio.seed_default_bundle assets=%s mcp=%s", saved, len(mcp_names))
    return {"seeded": True, "assets": saved, "mcp_configured": mcp_names}


def template_for(kind: str) -> dict[str, Any]:
    templates: dict[str, dict[str, Any]] = {
        "prompts": {
            "name": "我的提示词",
            "description": "一句话说明用途",
            "category": "custom",
            "priority": 50,
            "enabled": True,
            "content": "在这里写提示词正文。建议：先写目标，再写约束，最后写输出格式。",
        },
        "rules": {
            "name": "我的约束",
            "description": "一句话说明约束目的",
            "severity": "should",
            "scope": "all",
            "enabled": True,
            "content": "约束正文。must 级约束违反时回答不合格；should 级为默认建议。",
        },
        "hooks": {
            "name": "我的 Hook",
            "description": "一句话说明触发场景",
            "event": "pre_tool",
            "action": "warn",
            "match": "tool_name_pattern",
            "payload": "提示文案或注入内容",
            "priority": 50,
            "enabled": True,
        },
        "roles": {
            "name": "我的角色",
            "description": "一句话职责",
            "instructions": "你是……。职责：……。输出：……。边界：……。",
            "tools": "all",
            "temperature": 0.2,
            "enabled": True,
        },
        "skills": {
            "name": "我的技能",
            "description": "一句话描述技能",
            "content": "技能指令正文：何时使用、步骤、验收标准。",
            "enabled": True,
        },
    }
    if kind not in templates:
        raise ValueError(f"未知资产类型：{kind}")
    return json.loads(json.dumps(templates[kind], ensure_ascii=False))
