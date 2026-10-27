"""登录限流的客户端 IP 解析。

`X-Forwarded-For` 是可伪造的请求头：只有在运维显式声明"我在可信反代后面"
时才该采信，否则攻击者每次登录换一个头就能绕开按 IP 的限流。
"""

from __future__ import annotations

from app.auth import client_ip
from starlette.requests import Request


def _req(xff: str | None = None, host: str = "10.0.0.7") -> Request:
    headers = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    return Request({"type": "http", "headers": headers, "client": (host, 1234)})


def test_xff_ignored_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MONEYHELPER_TRUST_PROXY", raising=False)
    monkeypatch.delenv("XIAOMAN_TRUST_PROXY", raising=False)
    assert client_ip(_req("1.2.3.4")) == "10.0.0.7"


def test_xff_used_when_trust_proxy_enabled(monkeypatch) -> None:
    monkeypatch.setenv("MONEYHELPER_TRUST_PROXY", "1")
    assert client_ip(_req("1.2.3.4, 10.0.0.1")) == "1.2.3.4"


def test_falls_back_to_socket_ip_when_xff_empty(monkeypatch) -> None:
    monkeypatch.setenv("MONEYHELPER_TRUST_PROXY", "1")
    assert client_ip(_req("")) == "10.0.0.7"


def test_none_request() -> None:
    assert client_ip(None) == "unknown"
