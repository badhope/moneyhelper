"""Studio 资产安装门面：远程抓取、按条目落库，以及市场/预装/模板的 re-export。

按域拆到 installer_remote（抓取与 SSRF 校验在门面）、installer_market（安装/卸载）、
installer_seed（出厂预装与 MCP 漂移修复）、installer_templates（空白模板）。
"""

from __future__ import annotations

import base64
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from ..logging_utils import get_logger
from . import importer
from .installer_apply import _apply_entries

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
    """抓取远程文件，返回 (filename, text)。GitHub blob 走 contents API（raw 域名常被墙）。

    重定向安全：不自动跟随。SSRF 校验发生在调用方（只查首跳 URL），
    若这里 follow_redirects=True，攻击者控制的公网地址可以 302 到
    169.254.169.254 / 10.x 绕过校验。改为手动跟随，每一跳都重新校验，
    上限 3 跳。
    """
    from ..netguard import assert_public_http_url

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL 必须以 http:// 或 https:// 开头")
    api = _github_api_url(url)
    target = api or url
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "moneyhelper-studio"}
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        current = target
        for _hop in range(4):
            # 每一跳都做完整校验（含 DNS 解析）。GitHub API 本身是公网域名，
            # 不需要为它开后门；跳过解析反而给了「解析到内网」的绕过口子。
            assert_public_http_url(current)
            resp = await client.get(current, headers=headers)
            if resp.is_redirect:
                location = resp.headers.get("location") or ""
                if not location:
                    raise ValueError("下载失败：重定向缺少 Location")
                current = str(httpx.URL(current).join(location))
                continue
            break
        else:
            raise ValueError("下载失败：重定向次数过多")
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


from .installer_market import (  # noqa: F401,E402 — 对外同名导出
    _record_install,
    install_market,
    install_recommended,
    uninstall_market,
)
from .installer_seed import (  # noqa: F401,E402
    repair_mcp_config,
    seed_default_bundle,
    seed_domain_pack,
)
from .installer_templates import template_for  # noqa: F401,E402
