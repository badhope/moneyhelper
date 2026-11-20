"""登录防爆破：内存滑动窗口限流与客户端 IP 归属判断。

从 auth.py 拆出。`X-Forwarded-For` 仅在 `MONEYHELPER_TRUST_PROXY=1` 时采信。
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request

from .compat_env import getenv

_LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)  # key → [timestamp, ...]
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 60


def _rate_limited(key: str) -> bool:
    """检查是否超出速率限制（True = 被限流）。"""
    now = time.time()
    attempts = _LOGIN_ATTEMPTS[key]
    # 清除过期记录
    cutoff = now - _WINDOW_SECONDS
    _LOGIN_ATTEMPTS[key] = [t for t in attempts if t > cutoff]
    # 防止无限增长：空条目立即删除
    if not _LOGIN_ATTEMPTS[key]:
        del _LOGIN_ATTEMPTS[key]
    if len(_LOGIN_ATTEMPTS[key]) >= _MAX_ATTEMPTS:
        return True
    _LOGIN_ATTEMPTS[key].append(now)
    return False


# --- 端点处理 ---


def client_ip(request: Request | None) -> str:
    """取客户端 IP 用于限流键。

    `X-Forwarded-For` 只有在显式声明"我部署在可信反代后面"时才采信
    （`MONEYHELPER_TRUST_PROXY=1`）。默认不信任：否则任何能直连端口的
    人都能伪造该头，给每次登录换一个"IP"，把按 IP 的限流整个绕开。
    反代部署需在 nginx 里覆盖（而非追加）该头，见 docs/DEPLOY.md。
    """
    if request is None:
        return "unknown"
    if getenv("MONEYHELPER_TRUST_PROXY").strip() in ("1", "true", "yes"):
        fwd = request.headers.get("x-forwarded-for", "")
        first = fwd.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"
