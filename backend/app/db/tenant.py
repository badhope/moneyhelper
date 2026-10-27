"""租户上下文：当前请求属于哪个用户。

为什么用 ContextVar 而不是给每个函数加 user_id 参数：
- 数据层有 100+ 个函数、路由有 90+ 个调用点，逐个加参会引入大量签名漂移；
- ContextVar 按 asyncio task 隔离，天然不会在并发请求间串号；
- 关键写操作仍显式传 owner_id（见 db/*.py），上下文只负责"默认归属"。

约定：
- 0 表示"本机单用户"（未启用登录时的默认租户）；
- 登录后中间件把当前用户 id 写进上下文，所有读写默认落在这个租户下；
- 迁移来的历史数据统一归到第一个用户，admin 可见全部。
"""

from __future__ import annotations

from contextvars import ContextVar

# 默认租户：未启用多用户（或系统内部任务，如定时晨报）时使用
LOCAL_USER_ID = 0

_current_user_id: ContextVar[int] = ContextVar("moneyhelper_user_id", default=LOCAL_USER_ID)


def current_user_id() -> int:
    """当前租户 id（0 = 本机默认租户）。"""
    return _current_user_id.get()


def set_current_user_id(user_id: int) -> object:
    """设置当前租户，返回可用于还原的 token。"""
    return _current_user_id.set(int(user_id or LOCAL_USER_ID))


def reset_current_user_id(token: object) -> None:
    _current_user_id.reset(token)  # type: ignore[arg-type]


class use_user:
    """同步/异步上下文里临时切换租户（后台任务、跨租户统计用）。"""

    def __init__(self, user_id: int) -> None:
        self.user_id = int(user_id or LOCAL_USER_ID)
        self._token: object | None = None

    def __enter__(self) -> int:
        self._token = set_current_user_id(self.user_id)
        return self.user_id

    def __exit__(self, *exc: object) -> None:
        if self._token is not None:
            reset_current_user_id(self._token)
        self._token = None
