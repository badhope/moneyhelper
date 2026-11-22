"""应用内中继客户端单例：面板一键启停，状态可查询。"""

from __future__ import annotations

import asyncio
from typing import Any

from .client import RelayTunnel

_tunnel: RelayTunnel | None = None
_lock = asyncio.Lock()


def status() -> dict[str, Any]:
    if _tunnel is None:
        return {"active": False, "public_url": "", "relay_url": "", "local": ""}
    return _tunnel.status()


async def start(relay_url: str, token: str, local_port: int) -> dict[str, Any]:
    global _tunnel
    async with _lock:
        if _tunnel is not None and _tunnel.active:
            return _tunnel.status()
        if _tunnel is not None:
            await _tunnel.stop()
        _tunnel = RelayTunnel(relay_url, token, "127.0.0.1", int(local_port))
        return await _tunnel.start()


async def stop() -> None:
    global _tunnel
    async with _lock:
        if _tunnel is not None:
            await _tunnel.stop()
        _tunnel = None
