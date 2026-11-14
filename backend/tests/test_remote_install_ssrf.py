"""远程安装的 SSRF 纵深防御（审计 M-5）。

首跳校验由路由完成；这里锁的是「重定向不得绕过校验」：
follow_redirects=True 会让攻击者控制的公网 URL 302 到内网 metadata。
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from app.netguard import SSRFBlocked
from app.studio import installer


async def test_redirect_to_internal_address_is_blocked(monkeypatch) -> None:
    """第一跳公网 302 → 169.254.169.254 必须在校验处被拒，不能真的发出第二跳。"""

    class FakeResp:
        status_code = 302
        is_redirect = True
        headers: ClassVar[dict[str, str]] = {
            "location": "http://169.254.169.254/latest/meta-data/"
        }
        content = b""

    class FakeClient:
        def __init__(self, *a, **kw):
            self.requests: list[str] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None):
            self.requests.append(url)
            return FakeResp()

    created: list[FakeClient] = []

    def factory(*a, **kw):
        c = FakeClient()
        created.append(c)
        return c

    monkeypatch.setattr(installer.httpx, "AsyncClient", factory)
    with pytest.raises((SSRFBlocked, ValueError)):
        await installer.fetch_remote_text("https://evil.example.com/x.md")
    # 关键：不允许跟随到内网地址
    assert all("169.254" not in u for u in created[0].requests)


async def test_non_http_scheme_rejected() -> None:
    with pytest.raises(ValueError, match="http"):
        await installer.fetch_remote_text("file:///etc/passwd")
    with pytest.raises(ValueError, match="http"):
        await installer.fetch_remote_text("ftp://example.com/a")
