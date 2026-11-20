"""内置工具共享小助手：错误回执。"""

from __future__ import annotations


def _fail(msg: str) -> str:
    return f"错误：{msg}"
