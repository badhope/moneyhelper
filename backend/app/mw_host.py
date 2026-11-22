"""Host/Origin 防护：无口令模式下的来源校验、白名单与口令共用判定。"""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

from .auth import verify_api_token
from .mw_common import _SKIP_AUTH_PATHS

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}


def _hostname(value: str) -> str:
    """剥离端口的主机名（支持 host:port 与 [v6]:port）。"""
    v = (value or "").strip().lower()
    if v.startswith("["):
        return v.split("]", 1)[0] + "]"
    return v.rsplit(":", 1)[0] if v.count(":") == 1 else v


def _allowed_hosts() -> set[str]:
    extra = {
        h.strip().lower()
        for h in os.getenv("ALLOWED_HOSTS", "").split(",")
        if h.strip()
    }
    return _LOCAL_HOSTS | extra


def _host_allowed(host: str, allowed: set[str]) -> bool:
    """ALLOWED_HOSTS 含 * 时放行所有主机名（预览域名等不可枚举的场景）。"""
    if "*" in allowed:
        return True
    return host in allowed


def _client_is_local(request: Request) -> bool:
    """判断直连来源是否本机/内网。

    Host 头可被任意客户端伪造，因此无口令模式不能只靠 Host 判断：
    公网来源即使伪造 `Host: localhost` 也必须拒绝。
    """
    client = request.client
    if client is None or not client.host:
        # TestClient / ASGI 内嵌调用没有 client 信息，按本机处理（与历史行为一致）
        return True
    ip = client.host
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        # client.host 不是 IP 说明不是 TCP 直连（unix socket / 进程内 ASGI / TestClient），
        # 这些场景本身就在本机，放行并交给 Host 头校验兜底。
        return True
    if addr.is_loopback:
        return True
    return addr.is_private or addr.is_link_local


def token_ok(request: Request) -> bool:
    """口令判定：未设 API_TOKEN 时恒为 True（无口令模式），否则要求匹配。

    供主中间件与 MCP 子应用共用，避免两处各自实现导致口径漂移。
    """
    key = os.getenv("API_TOKEN", "").strip()
    if not key:
        return True
    return verify_api_token(request) is not None


def host_guard_check(request: Request) -> str | None:
    """无口令模式的来源校验，返回错误文案；通过返回 None。

    两条例外：配对入口（一次性令牌就是凭据）与已带远程设备 cookie 的请求
    （cookie 是否有效由 auth_gate 决定；这里不拦，否则手机从公网回来会被挡在
    验证之前）。

    三条同时满足才放行：
    1. 直连来源是本机/内网（防公网直连伪造 Host）
    2. Host 在白名单内
    3. Origin（若有）在白名单内
    """
    if request.url.path == "/api/remote/pair":
        return None
    if request.cookies.get("mh_remote"):
        return None
    if os.getenv("API_TOKEN", "").strip():
        return None  # 有口令时以口令为准（反代部署不按 Host 拦截）
    if not _client_is_local(request):
        return "不允许的来源：未设置 API_TOKEN 时仅允许本机/内网访问，请设置口令后再对外提供服务"
    allowed = _allowed_hosts()
    host = _hostname(request.headers.get("host", ""))
    if host and not _host_allowed(host, allowed):
        return (
            "不允许的 Host：未设置 API_TOKEN 时仅限本机/内网访问，"
            "如需按主机名部署请设置 ALLOWED_HOSTS 或 API_TOKEN"
        )
    origin = request.headers.get("origin", "")
    if origin:
        oh = (urlsplit(origin).hostname or "").lower()
        if oh and not _host_allowed(oh, allowed) and oh != host:
            return "不允许的 Origin"
    return None


async def host_guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in _SKIP_AUTH_PATHS:
        denied = host_guard_check(request)
        if denied is not None:
            return JSONResponse({"error": denied}, status_code=403)
    return await call_next(request)
