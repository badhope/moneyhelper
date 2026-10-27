"""Moneyhelper —— 能自主干活的 AI 财务部门。

本包是分层门面（M1.1），把后端拆成四个语义清晰的层：

    moneyhelper.core    确定性内核：账本 / 分析 / 行情 / 解析 / 加密 / 导入
    moneyhelper.server  HTTP 壳：FastAPI 应用、路由、中间件
    moneyhelper.cli     命令行入口
    moneyhelper.mcp     MCP Server（模块名避开顶层 "mcp"，那是官方 SDK）

设计约束（后续所有改动都应遵守）：

1. **core 不认识 HTTP**。core 里不 import fastapi / starlette / request。
   这样 CLI、MCP、部门模式、脚本都能直接复用同一套内核。
2. **server 依赖 core，core 不依赖 server**。反向引用一律视为设计缺陷。
3. **旧路径保持可用**。`backend.app.*` 与本包并存，迁移期不做破坏性改名；
   `moneyhelper.core` 等通过 re-export 暴露既有实现，不复制代码。

当前阶段：门面已建立并可用，实现仍在 `app/` 下（见各子包 docstring 的映射表）。
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_app_importable() -> None:
    """让 `app.*`（既有实现）在任意工作目录下都能导入。

    门面层通过 re-export 暴露 `app.*` 的实现，所以导入本包的前提是 `app` 可见。
    源码运行（仓库内）时它就在 `backend/` 下；用 `pip install .` 安装后
    `backend/` 可能不在 sys.path 中，这里按两种布局依次探测：

    - 源码布局：<repo>/moneyhelper/__init__.py  → <repo>/backend
    - 安装布局：<site-packages>/moneyhelper/__init__.py → 无 backend，需用户设 PYTHONPATH

    探测失败不抛错：只影响 core/server 门面，`moneyhelper.cli --help` 之类应仍可用。
    """
    if "app" in sys.modules:
        return
    candidates = [
        Path(__file__).resolve().parent.parent / "backend",  # 源码布局
        Path.cwd() / "backend",  # 从仓库根运行
        Path.cwd(),  # 已在 backend/ 下运行
    ]
    for cand in candidates:
        if (cand / "app" / "__init__.py").is_file():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            return


_ensure_app_importable()


def _load_version() -> str:
    """版本号来自后端单一真源 app/version.py（避免多份版本各自漂移）。"""
    _ensure_app_importable()
    try:
        from app.version import __version__ as v

        return v
    except Exception:  # noqa: BLE001 — 导入失败时降级，保证包仍可用
        return "0.0.0"


__version__ = _load_version()


__all__ = ["__version__"]
