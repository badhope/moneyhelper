"""路由层统一响应助手。

## 为什么有这个文件

拆分路由时，`_bad()` 这个「错误响应」助手被复制进了 12 个 route 文件
（banking / connect / connect_deep / debt_payoff / execute / expenses /
finance_tax / gl / longtask / org / procurement / studio），实现完全相同：

    def _bad(msg, code=400):
        return JSONResponse({"error": msg}, status_code=code)

改一处错误响应格式（比如加 `code` 字段、加 `request_id`）要改 12 个文件，
漏改就让前端在不同接口拿到不同错误结构。收敛到本模块后，路由只 import。

`ok()` 同理：多个路由手写 `JSONResponse({"ok": True})` 或裸 dict 返回，
统一走这里，保证成功/失败结构对称。
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def bad(msg: str, code: int = 400) -> JSONResponse:
    """统一的失败响应：`{"error": msg}` + 指定 HTTP 状态码。"""
    return JSONResponse({"error": msg}, status_code=code)


def fail(msg: str, code: int = 400) -> JSONResponse:
    """带 `ok: false` 的失败响应（Studio 系接口的既有契约）。"""
    return JSONResponse({"ok": False, "error": msg}, status_code=code)


def ok(data: Any = None, code: int = 200) -> JSONResponse:
    """统一的成功响应：`{"ok": true}`，或携带 `data`。"""
    if data is None:
        return JSONResponse({"ok": True}, status_code=code)
    return JSONResponse({"ok": True, "data": data}, status_code=code)
