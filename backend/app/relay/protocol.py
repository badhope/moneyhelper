"""中继控制协议：JSON 文本帧 + base64 二进制负载。

一条控制 WebSocket 上复用多条手机 TCP 连接：
- register  → 桌面端注册，中继分配公网端口
- open      → 有手机连入，桌面端连本地服务
- data      → 双向字节流
- close     → 任一端关闭
"""

from __future__ import annotations

import base64
import json
from typing import Any


def pack(kind: str, **fields: Any) -> str:
    return json.dumps({"type": kind, **fields}, separators=(",", ":"))


def unpack(raw: str) -> dict[str, Any]:
    try:
        obj = json.loads(raw)
    except (TypeError, ValueError):
        return {"type": "invalid"}
    return obj if isinstance(obj, dict) else {"type": "invalid"}


def encode_data(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def decode_data(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))
