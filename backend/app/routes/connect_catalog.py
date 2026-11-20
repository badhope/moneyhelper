"""连接器目录与公开源连通性：目录分组、已建连接、自动化统计。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..connect import marketdata, store
from ..connect.catalog import grouped_catalog

router = APIRouter(dependencies=[Depends(get_current_user)])

# ---------------------------------------------------------------------------
# 目录
# ---------------------------------------------------------------------------


@router.get("/api/connect/catalog")
async def connect_catalog() -> dict[str, Any]:
    """连接器目录（按分类分组）+ 当前已建立的连接 + 自动化统计。"""
    connections = await store.list_connections()
    by_connector: dict[str, list[dict[str, Any]]] = {}
    for c in connections:
        by_connector.setdefault(c["connector_id"], []).append(c)
    catalog = grouped_catalog()
    for group in catalog["groups"]:
        for item in group["items"]:
            item["connections"] = by_connector.get(item["id"], [])
    return {**catalog, "connections": connections, "kinds_label": _kind_labels()}


def _kind_labels() -> dict[str, str]:
    return {
        "public_api": "公开接口 · 后台自动拉取",
        "deep_link": "官方入口 · 一键跳转登录",
        "browser_login": "浏览器代登录 · 配对码回传",
        "file_import": "文件导入 · 收件目录自动入账",
    }


@router.get("/api/connect/sources/status")
async def connect_sources_status() -> dict[str, Any]:
    """公开数据源连通性探测（东财行情 / 天天基金 / 涨跌榜）。"""
    return await marketdata.source_status()
