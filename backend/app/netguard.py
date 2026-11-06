"""出站目标地址的安全校验（SSRF 防护）。

为什么单独成模块：MCP 测试/保存接口接受用户提供的 URL，随后由后端发起
请求。不校验目标就是经典 SSRF——可探测 169.254.169.254 云凭据、内网服务、
localhost 上的其他进程。此前 /api/mcp/test 还允许任意 command 拉起本机
进程，等于把命令执行开放给了普通登录用户。

原则（对齐 OWASP SSRF Prevention Cheat Sheet）：
  - 只允许 http/https；
  - 解析主机名后拒绝 IP 字面量落在私网/回环/链路本地/保留段；
  - 域名解析出的所有地址都必须通过校验（防 DNS rebinding 的第一层）；
  - 拒绝携带 userinfo（user:pass@host）的 URL。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

BLOCKED_RANGES = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),      # CGNAT / Tailscale 等内网段
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),     # 链路本地 + 云 metadata
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/3"),        # 组播 + 保留
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


class SSRFBlocked(ValueError):
    """目标地址命中内网/保留段或格式非法。"""


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(ip in net for net in BLOCKED_RANGES)


def assert_public_http_url(url: str, *, resolve: bool = True) -> str:
    """校验 URL 指向公网 http(s) 目标；通过则原样返回，否则抛 SSRFBlocked。

    resolve=False 时只做语法与 userinfo 检查（用于无需联网的快速拒绝路径）。
    """
    raw = str(url or "").strip()
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise SSRFBlocked("URL 无法解析") from exc
    if parts.scheme not in ("http", "https"):
        raise SSRFBlocked("地址必须以 http:// 或 https:// 开头")
    host = parts.hostname
    if not host:
        raise SSRFBlocked("URL 缺少主机名")
    if parts.username or parts.password:
        raise SSRFBlocked("不允许携带 userinfo（user:pass@host）")

    literal = self_ip = None
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_blocked(literal):
            raise SSRFBlocked(f"禁止访问内网/保留地址：{host}")
        return raw

    if not resolve:
        return raw
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFBlocked(f"域名解析失败：{host}") from exc
    for info in infos:
        try:
            self_ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_blocked(self_ip):
            raise SSRFBlocked(f"{host} 解析到内网/保留地址（{self_ip}），已拦截")
    return raw
