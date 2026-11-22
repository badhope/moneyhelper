"""自托管中继：桌面出站连接后，公网端口能完整转发字节流。"""

from __future__ import annotations

import asyncio
import socket

import pytest
from app.relay.client import RelayTunnel
from app.relay.server import RelayServer


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


async def test_relay_forwards_tcp_bytes() -> None:
    local_port = _free_port()
    echo = await asyncio.start_server(_echo, "127.0.0.1", local_port)
    control_port = _free_port()
    public_port = _free_port()
    relay = RelayServer(
        control_host="127.0.0.1",
        control_port=control_port,
        port_start=public_port,
        port_end=public_port,
        public_host="127.0.0.1",
        token="t",
    )
    await relay.start()
    tunnel = RelayTunnel(f"ws://127.0.0.1:{control_port}", "t", "127.0.0.1", local_port)
    try:
        info = await tunnel.start()
        assert info["public_url"] == f"http://127.0.0.1:{public_port}"
        reader, writer = await asyncio.open_connection("127.0.0.1", public_port)
        writer.write(b"ping")
        await writer.drain()
        assert await asyncio.wait_for(reader.read(4), timeout=5) == b"ping"
        writer.close()
    finally:
        await tunnel.stop()
        await relay.close()
        echo.close()
        await echo.wait_closed()


async def test_relay_rejects_wrong_token() -> None:
    control_port = _free_port()
    public_port = _free_port()
    relay = RelayServer(
        control_host="127.0.0.1",
        control_port=control_port,
        port_start=public_port,
        port_end=public_port,
        public_host="127.0.0.1",
        token="right",
    )
    await relay.start()
    tunnel = RelayTunnel(f"ws://127.0.0.1:{control_port}", "wrong", "127.0.0.1", 1)
    try:
        with pytest.raises(RuntimeError):
            await tunnel.start(timeout=5)
    finally:
        await tunnel.stop()
        await relay.close()
