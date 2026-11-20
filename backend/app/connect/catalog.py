"""连接器目录门面：枚举与构造器见 catalog_base，清单正文见 catalog_connectors。

一份连接器 = 一个外部平台/数据源的接入说明：接入方式（public_api / deep_link /
browser_login / file_import / gateway）、能力标记、自动化程度、官方入口地址。
"""

from __future__ import annotations

from typing import Any

from .catalog_base import AUTOMATION, CATEGORIES, KINDS  # noqa: F401 — 对外同名导出
from .catalog_connectors import CONNECTORS  # noqa: F401 — 对外同名导出

_BY_ID = {c["id"]: c for c in CONNECTORS}


def get_connector(cid: str) -> dict[str, Any] | None:
    """按 id 取连接器定义（返回副本，调用方修改不会污染目录）。"""
    hit = _BY_ID.get(str(cid).strip())
    return dict(hit) if hit else None


def grouped_catalog() -> dict[str, Any]:
    """按分类分组的目录 + 统计，供前端一次渲染。"""
    groups: list[dict[str, Any]] = []
    for key, label in CATEGORIES:
        items = [c for c in CONNECTORS if c["category"] == key]
        if not items:
            continue
        groups.append({"key": key, "label": label, "items": items})
    counts = {
        "total": len(CONNECTORS),
        "auto": sum(1 for c in CONNECTORS if c["automation"] == "auto"),
        "semi": sum(1 for c in CONNECTORS if c["automation"] == "semi"),
        "manual": sum(1 for c in CONNECTORS if c["automation"] == "manual"),
        "trade": sum(1 for c in CONNECTORS if c["supports_trade"]),
    }
    return {"groups": groups, "counts": counts, "kinds": list(KINDS), "automation": list(AUTOMATION)}
