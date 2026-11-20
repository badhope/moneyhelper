"""中间件共享常量：免鉴权内部端点清单。"""

from __future__ import annotations

_SKIP_AUTH_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/user-count",
    # 书签脚本回传：从用户浏览器（可能跨域）发起，凭据是 URL 里的一次性配对码。
    # 配对码 10 分钟有效、用后即焚，且只能写入不能读出，因此不要求 JWT；
    # 仍受限流与 Host 防护约束。
    "/api/connect/ingest",
}
