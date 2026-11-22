"""桌面端中继客户端：出站连接公网中继，把手机流量转到本机服务。

    python -m app.relay.client --relay ws://relay.example.com:8789 --token <token> \
        --local 127.0.0.1:8788

手机访问中继分配的公网端口即可，不需要本机有公网 IP。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import ssl
from typing import Any

import websockets


class RelayTunnel:
    def __init__(
        self,
        relay_url: str,
        token: str,
        local_host: str = "127.0.0.1",
        local_port: int = 8788,
        *,
        insecure: bool = False,
    ) -> None:
        self.relay_url = relay_url.rstrip("/")
        if not self.relay_url.endswith("/control"):
            self.relay_url += "/control"
        self.token = token
        self.local_host = local_host
        self.local_port = local_port
        self.insecure = insecure
        self.public_url = ""
        self.session = ""
        self.error = ""
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[Any] | None = None
        self._ws: Any = None
        self._channels: dict[str, tuple[asyncio.StreamReader, asyncio.StreamWriter]] = {}
        self._pending: dict[str, list[bytes]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._send_lock = asyncio.Lock()

    @property
    def active(self) -> bool:
        return bool(self.public_url) and self._task is not None and not self._task.done()

    async def start(self, timeout: float = 12.0) -> dict[str, Any]:
        if self.active:
            return self.status()
        self._task = asyncio.create_task(self._run())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            await self.stop()
            raise RuntimeError("中继连接超时：检查中继地址、网络与 token") from None
        if self.error:
            await self.stop()
            raise RuntimeError(self.error)
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "public_url": self.public_url,
            "session": self.session,
            "relay_url": self.relay_url,
            "local": f"{self.local_host}:{self.local_port}",
        }

    async def _send(self, payload: str) -> None:
        ws = self._ws
        if ws is None:
            return
        async with self._send_lock:
            with contextlib.suppress(Exception):
                await ws.send(payload)

    def _pack(self, kind: str, **fields: Any) -> str:
        return json.dumps({"type": kind, **fields}, separators=(",", ":"))

    async def _run(self) -> None:
        ssl_ctx = None
        if self.relay_url.startswith("wss://") and self.insecure:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        try:
            async with websockets.connect(
                self.relay_url,
                ssl=ssl_ctx,
                max_size=2 * 1024 * 1024,
                ping_interval=20,
                ping_timeout=60,
            ) as ws:
                self._ws = ws
                await ws.send(self._pack("register", token=self.token))
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                msg = json.loads(raw) if isinstance(raw, str) else {}
                if msg.get("type") == "error":
                    self.error = str(msg.get("message") or "中继拒绝连接")
                    self._ready.set()
                    return
                if msg.get("type") != "registered":
                    self.error = "中继未返回注册结果"
                    self._ready.set()
                    return
                self.public_url = str(msg.get("public_url") or "")
                self.session = str(msg.get("session") or "")
                self._ready.set()
                async for raw in ws:
                    if isinstance(raw, str):
                        await self._on_message(json.loads(raw))
        except Exception as exc:  # noqa: BLE001
            self.error = f"中继连接失败：{exc}"
            self._ready.set()
        finally:
            self._ready.set()
            self._ws = None
            for _, writer in list(self._channels.values()):
                with contextlib.suppress(Exception):
                    writer.close()
            self._channels.clear()

    async def _on_message(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        cid = str(msg.get("channel") or "")
        if kind == "open" and cid and cid not in self._channels:
            task = asyncio.create_task(self._open_channel(cid))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        elif kind == "data":
            try:
                data = base64.b64decode(str(msg.get("data") or ""))
            except Exception:
                return
            if cid not in self._channels:
                # open 与首个请求可能同帧到达：先缓存，本地连接建好再灌进去
                if data and len(self._pending.get(cid, [])) < 8:
                    self._pending.setdefault(cid, []).append(data)
                return
            _, writer = self._channels[cid]
            if data:
                writer.write(data)
                with contextlib.suppress(Exception):
                    await writer.drain()
        elif kind == "close" and cid in self._channels:
            _, writer = self._channels.pop(cid)
            with contextlib.suppress(Exception):
                writer.close()

    async def _open_channel(self, cid: str) -> None:
        try:
            reader, writer = await asyncio.open_connection(self.local_host, self.local_port)
        except Exception:
            await self._send(self._pack("close", channel=cid))
            return
        self._channels[cid] = (reader, writer)
        for buffered in self._pending.pop(cid, []):
            writer.write(buffered)
        with contextlib.suppress(Exception):
            await writer.drain()
        try:
            while True:
                data = await reader.read(64 * 1024)
                if not data:
                    break
                await self._send(
                    self._pack("data", channel=cid, data=base64.b64encode(data).decode("ascii"))
                )
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._channels.pop(cid, None)
            self._pending.pop(cid, None)
            await self._send(self._pack("close", channel=cid))
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._task = None
        self.public_url = ""
        self.session = ""
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        for _, writer in list(self._channels.values()):
            with contextlib.suppress(Exception):
                writer.close()
        self._channels.clear()


def main() -> None:
    parser = argparse.ArgumentParser(description="Moneyhelper 桌面端远程中继")
    parser.add_argument("--relay", required=True, help="中继控制地址，如 ws://relay.example.com:8789")
    parser.add_argument("--token", default="")
    parser.add_argument("--local", default="127.0.0.1:8788")
    parser.add_argument("--insecure", action="store_true", help="跳过 wss 证书校验（仅自签测试）")
    args = parser.parse_args()
    host, _, port = args.local.partition(":")
    tunnel = RelayTunnel(args.relay, args.token, host or "127.0.0.1", int(port or 8788), insecure=args.insecure)

    async def run() -> None:
        info = await tunnel.start()
        print(f"relay connected: {info['public_url']} -> {info['local']}", flush=True)
        await asyncio.Event().wait()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
