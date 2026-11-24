"""4.22.0 外部投递：真实 SMTP / HTTP 本地服务端到端，不用 mock 冒充接入。"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import date

import pytest
from aiohttp import web
from app import db

SECRET = "unit-test-signing-secret-1234"


class _SmtpServer:
    def __init__(self) -> None:
        self.messages: list[bytes] = []
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        sockets = self.server.sockets or []
        return int(sockets[0].getsockname()[1])

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writer.write(b"220 localhost test smtp\r\n")
        await writer.drain()
        data_mode = False
        buf: list[bytes] = []
        while True:
            line = await reader.readline()
            if not line:
                break
            if data_mode:
                if line in (b".\r\n", b".\n"):
                    self.messages.append(b"".join(buf))
                    buf.clear()
                    data_mode = False
                    writer.write(b"250 queued\r\n")
                    await writer.drain()
                else:
                    buf.append(line[1:] if line.startswith(b"..") else line)
                continue
            cmd = line.decode("utf-8", "replace").strip()
            upper = cmd.upper()
            if upper.startswith("EHLO") or upper.startswith("HELO"):
                writer.write(b"250-localhost\r\n250 8BITMIME\r\n")
            elif (
                upper.startswith("MAIL FROM")
                or upper.startswith("RCPT TO")
                or upper == "RSET"
            ):
                writer.write(b"250 ok\r\n")
            elif upper == "DATA":
                data_mode = True
                writer.write(b"354 end with .\r\n")
            elif upper == "QUIT":
                writer.write(b"221 bye\r\n")
                await writer.drain()
                break
            else:
                writer.write(b"250 ok\r\n")
            await writer.drain()
        writer.close()
        await writer.wait_closed()


async def _prepare_tax(tenant_id: int = 0) -> str:
    period = date.today().strftime("%Y-%m")
    day = date.today().isoformat()
    await db.gl_bootstrap(tenant_id, ref_date=day)
    accounts = {a["code"]: a for a in await db.gl_list_accounts(tenant_id)}
    entry = await db.gl_create_entry(
        tenant_id,
        day,
        "外部投递测试销售",
        [
            {"account_id": accounts["1001"]["id"], "debit": 900, "credit": 0},
            {"account_id": accounts["6001"]["id"], "debit": 0, "credit": 900},
        ],
    )
    await db.gl_post_entry(tenant_id, entry["id"])
    return period


@pytest.mark.asyncio
async def test_smtp_channel_really_sends_email_and_is_idempotent(
    client, monkeypatch
) -> None:
    monkeypatch.setenv("MH_ALLOW_LOCAL_CHANNELS", "1")
    period = await _prepare_tax()
    smtp = _SmtpServer()
    port = await smtp.start()
    try:
        resp = await client.put(
            "/api/external/channels/smtp",
            json={
                "label": "测试邮箱",
                "enabled": True,
                "config": {
                    "host": "127.0.0.1",
                    "port": port,
                    "security": "none",
                    "username": "",
                    "from_addr": "finance@example.com",
                    "to_addrs": ["accountant@example.com"],
                    "subject_prefix": "[MH]",
                },
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["channel"]["ready"] is True

        test = await client.post("/api/external/channels/smtp/test", json={})
        assert test.status_code == 200, test.text
        assert test.json()["ok"] is True
        assert "已受理" in test.json()["detail"]

        sent = await client.post(
            "/api/external/deliver",
            json={
                "channel_id": "smtp",
                "kind": "tax",
                "period": period,
                "note": "交给代账",
            },
        )
        assert sent.status_code == 200, sent.text
        delivery = sent.json()["delivery"]
        assert delivery["status"] == "accepted"
        assert delivery["receipt"]["transport"] == "smtp"
        assert delivery["receipt"]["attachment_bytes"] > 0
        assert delivery["request_summary"]["attachments"] == 2

        again = await client.post(
            "/api/external/deliver",
            json={
                "channel_id": "smtp",
                "kind": "tax",
                "period": period,
                "note": "交给代账",
            },
        )
        assert again.status_code == 200, again.text
        assert again.json()["duplicate"] is True
        assert len(smtp.messages) == 2  # 测试邮件 + 业务邮件，重复点击不再发第三封

        raw = smtp.messages[-1].decode("utf-8", "replace")
        assert "TAX-" in raw
        assert "accountant@example.com" in raw
        ledger = await client.get("/api/external/handoffs")
        assert ledger.status_code == 200
        assert any(
            row["delivery_status"] == "accepted" for row in ledger.json()["records"]
        )
    finally:
        await smtp.stop()


@pytest.mark.asyncio
async def test_signed_https_gateway_really_posts_packet(client, monkeypatch) -> None:
    monkeypatch.setenv("MH_ALLOW_LOCAL_CHANNELS", "1")
    period = await _prepare_tax()
    seen: list[dict] = []
    auth_ok: list[bool] = []

    async def hook(request: web.Request) -> web.Response:
        body = await request.read()
        ts = request.headers.get("X-MH-Timestamp", "")
        sig = request.headers.get("X-MH-Signature", "")
        expected = (
            "sha256="
            + hmac.new(
                SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256
            ).hexdigest()
        )
        auth_ok.append(sig == expected)
        payload = json.loads(body)
        seen.append(payload)
        return web.json_response({"receipt_id": f"RCPT-{len(seen)}"})

    app = web.Application()
    app.router.add_post("/hook", hook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        resp = await client.put(
            "/api/external/channels/tax_gateway",
            json={
                "label": "测试税局网关",
                "enabled": True,
                "config": {
                    "endpoint": f"http://127.0.0.1:{port}/hook",
                    "provider_name": "测试服务商",
                    "timeout_sec": 10,
                },
                "secret": {"signing_secret": SECRET},
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["channel"]["ready"] is True

        test = await client.post("/api/external/channels/tax_gateway/test", json={})
        assert test.status_code == 200, test.text
        assert test.json()["ok"] is True
        assert seen[-1]["event"] == "probe"

        sent = await client.post(
            "/api/external/deliver",
            json={"channel_id": "tax_gateway", "kind": "tax", "period": period},
        )
        assert sent.status_code == 200, sent.text
        delivery = sent.json()["delivery"]
        assert delivery["status"] == "accepted"
        assert delivery["receipt"]["receipt_id"] == "RCPT-2"
        assert seen[-1]["packet"]["packet_id"].startswith("TAX-")
        assert auth_ok == [True, True]

        deliveries = await client.get("/api/external/deliveries")
        assert deliveries.status_code == 200
        assert deliveries.json()["stats"]["accepted"] == 1
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_channel_fails_closed_without_secret_or_bad_endpoint(client) -> None:
    resp = await client.put(
        "/api/external/channels/bank_gateway",
        json={
            "enabled": True,
            "config": {
                "endpoint": "http://169.254.169.254/latest/meta-data",
                "provider_name": "坏地址",
            },
        },
    )
    assert resp.status_code == 400
    assert "HTTPS" in resp.json()["error"] or "内网" in resp.json()["error"]

    resp = await client.put(
        "/api/external/channels/bank_gateway",
        json={
            "enabled": True,
            "config": {
                "endpoint": "https://bank.example.com/hook",
                "provider_name": "示例银行",
            },
        },
    )
    assert resp.status_code == 400
    assert "签名密钥" in resp.json()["error"]

    resp = await client.post(
        "/api/external/deliver", json={"channel_id": "bank_gateway", "kind": "tax"}
    )
    assert resp.status_code == 400
    assert "不接受" in resp.json()["error"] or "未配置" in resp.json()["error"]
