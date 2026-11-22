"""自托管中继服务端。

部署在一台有公网入口的机器上：

    python -m app.relay.server --control-port 8789 --port-start 9100 --port-end 9199 \
        --public-host relay.example.com --token <长随机串>

桌面端用同一条 token 出站连接控制端口；中继为每个桌面会话开一个公网 TCP 端口，
手机访问 http://relay.example.com:<port>/ 即可。端口范围需要在防火墙/安全组放行。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import secrets
import ssl
import uuid
from typing import Any

from websockets.asyncio.server import serve

CHUNK = 64 * 1024


class RelaySession:
    def __init__(self, server: RelayServer, websocket: Any, port: int, public_url: str) -> None:
        self.server = server
        self.websocket = websocket
        self.port = port
        self.public_url = public_url
        self.channels: dict[str, tuple[asyncio.StreamReader, asyncio.StreamWriter]] = {}
        self.tasks: set[asyncio.Task[Any]] = set()
        self._send_lock = asyncio.Lock()
        self._closed = False
        self.listener: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self.listener = await asyncio.start_server(
            self._handle_phone,
            host="0.0.0.0",
            port=self.port,
            ssl=self.server.server_ssl,
        )

    async def send(self, payload: str) -> None:
        if self._closed:
            return
        async with self._send_lock:
            with contextlib.suppress(Exception):
                await self.websocket.send(payload)

    def spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _handle_phone(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        if self._closed:
            writer.close()
            return
        cid = uuid.uuid4().hex
        self.channels[cid] = (reader, writer)
        await self.send(self.server.pack("open", channel=cid))
        try:
            while not self._closed:
                data = await reader.read(CHUNK)
                if not data:
                    break
                await self.send(self.server.pack("data", channel=cid, data=base64.b64encode(data).decode("ascii")))
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self.channels.pop(cid, None)
            await self.send(self.server.pack("close", channel=cid))
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    async def on_message(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        cid = str(msg.get("channel") or "")
        if kind == "data" and cid in self.channels:
            try:
                data = base64.b64decode(str(msg.get("data") or ""))
            except Exception:
                return
            _, writer = self.channels[cid]
            if data:
                writer.write(data)
                with contextlib.suppress(Exception):
                    await writer.drain()
        elif kind == "close" and cid in self.channels:
            _, writer = self.channels.pop(cid)
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.listener is not None:
            self.listener.close()
            with contextlib.suppress(Exception):
                await self.listener.wait_closed()
        for _, writer in list(self.channels.values()):
            with contextlib.suppress(Exception):
                writer.close()
        self.channels.clear()
        for task in list(self.tasks):
            task.cancel()
        await self.server.release_port(self.port)


class RelayServer:
    def __init__(
        self,
        *,
        control_host: str,
        control_port: int,
        port_start: int,
        port_end: int,
        public_host: str,
        token: str = "",
        certfile: str = "",
        keyfile: str = "",
    ) -> None:
        self.control_host = control_host
        self.control_port = control_port
        self.port_start = port_start
        self.port_end = port_end
        self.public_host = public_host
        self.token = token.strip()
        self._ports: set[int] = set()
        self._free = list(range(port_start, port_end + 1))
        self._lock = asyncio.Lock()
        self._server: Any = None
        self.server_ssl: ssl.SSLContext | None = None
        self.control_ssl: ssl.SSLContext | None = None
        if certfile and keyfile:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(certfile, keyfile)
            self.server_ssl = ctx
            self.control_ssl = ctx

    def pack(self, kind: str, **fields: Any) -> str:
        import json

        return json.dumps({"type": kind, **fields}, separators=(",", ":"))

    @property
    def scheme(self) -> str:
        return "https" if self.server_ssl else "http"

    async def acquire_port(self) -> int | None:
        async with self._lock:
            return self._free.pop(0) if self._free else None

    async def release_port(self, port: int) -> None:
        async with self._lock:
            if port not in self._free:
                self._free.append(port)
                self._free.sort()

    async def start(self) -> None:
        self._server = await serve(
            self._handle_control,
            self.control_host,
            self.control_port,
            ssl=self.control_ssl,
            max_size=2 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=60,
        )

    async def _handle_control(self, websocket: Any, *_: Any) -> None:
        session: RelaySession | None = None
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            import json

            msg = json.loads(raw) if isinstance(raw, str) else {}
            if msg.get("type") != "register":
                await websocket.close(code=1008, reason="register required")
                return
            if self.token and not secrets.compare_digest(str(msg.get("token") or ""), self.token):
                await websocket.close(code=1008, reason="invalid relay token")
                return
            port = await self.acquire_port()
            if port is None:
                await websocket.send(self.pack("error", message="relay ports exhausted"))
                await websocket.close(code=1011, reason="ports exhausted")
                return
            public_url = f"{self.scheme}://{self.public_host}:{port}"
            session = RelaySession(self, websocket, port, public_url)
            await session.start()
            await websocket.send(
                self.pack("registered", port=port, public_url=public_url, session=uuid.uuid4().hex[:12])
            )
            async for raw in websocket:
                if isinstance(raw, str):
                    await session.on_message(json.loads(raw))
        except Exception:
            pass
        finally:
            if session is not None:
                await session.close()

    async def run_forever(self) -> None:
        await self.start()
        assert self._server is not None
        await self._server.wait_closed()

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None


def main() -> None:
    parser = argparse.ArgumentParser(description="Moneyhelper 自托管远程中继")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--control-port", type=int, default=8789)
    parser.add_argument("--port-start", type=int, default=9100)
    parser.add_argument("--port-end", type=int, default=9199)
    parser.add_argument("--public-host", required=True, help="手机访问到的主机名/IP，如 relay.example.com")
    parser.add_argument("--token", default="", help="桌面端注册口令；公网部署必须设置")
    parser.add_argument("--certfile", default="", help="TLS 证书（可选；启用后公网端口走 https）")
    parser.add_argument("--keyfile", default="", help="TLS 私钥")
    args = parser.parse_args()

    server = RelayServer(
        control_host=args.host,
        control_port=args.control_port,
        port_start=args.port_start,
        port_end=args.port_end,
        public_host=args.public_host,
        token=args.token,
        certfile=args.certfile,
        keyfile=args.keyfile,
    )
    print(f"relay control on {args.host}:{args.control_port}; public ports {args.port_start}-{args.port_end}")
    asyncio.run(server.run_forever())


if __name__ == "__main__":
    main()
