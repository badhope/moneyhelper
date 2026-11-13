"""程序自身目录的保护闸（切片 9：代理权限边界）。

背景：这个应用把「数据目录」放在仓库内（backend/data）。如果不加区分，
任何能写文件的能力都可以顺着相对路径改到源码、配置甚至 .git。
默认规则：

- 允许写：数据目录、日志目录（由调用方显式限定根目录）；
- 禁止写：源码目录、前端源码、.git、依赖清单、启动脚本；
- 读取同样按需：路径解析到受保护根时拒绝，除非显式开启
  MONEYHELPER_ALLOW_SYSTEM_ACCESS=1（最高权限）。

这不是替代沙箱，而是「程序不能自己改自己」的最后一道硬闸。
"""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 受保护的路径：源码、前端、版本库、依赖与启动脚本。
_PROTECTED_DIRS = (
    _PROJECT_ROOT / "backend" / "app",
    _PROJECT_ROOT / "backend" / "tests",
    _PROJECT_ROOT / "frontend" / "src",
    _PROJECT_ROOT / ".git",
    _PROJECT_ROOT / ".github",
    _PROJECT_ROOT / "desktop",
    _PROJECT_ROOT / "moneyhelper",
)
_PROTECTED_FILES = (
    _PROJECT_ROOT / "backend" / "requirements.txt",
    _PROJECT_ROOT / "frontend" / "package.json",
    _PROJECT_ROOT / "frontend" / "package-lock.json",
    _PROJECT_ROOT / "pyproject.toml",
    _PROJECT_ROOT / "Dockerfile",
    _PROJECT_ROOT / "docker-compose.yml",
)


def system_access_allowed() -> bool:
    """最高权限开关：只有部署者显式设置环境变量才允许碰程序自身目录。"""
    return os.getenv("MONEYHELPER_ALLOW_SYSTEM_ACCESS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _resolved(path: str | Path) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except Exception:  # noqa: BLE001 — 无法解析的路径按受保护处理
        return Path(str(path))


def is_protected(path: str | Path) -> bool:
    """路径是否落在程序自身目录/文件内。"""
    target = _resolved(path)
    for root in _PROTECTED_DIRS:
        try:
            target.relative_to(root)
            return True
        except ValueError:
            continue
    return any(target == f for f in _PROTECTED_FILES)

def assert_not_protected(path: str | Path, *, operation: str = "访问") -> None:
    """路径命中受保护目录时抛 PermissionError（除非最高权限已开启）。"""
    if system_access_allowed():
        return
    if is_protected(path):
        raise PermissionError(
            f"禁止{operation}程序自身目录：{path}。"
            "如确需这样做，请由部署者设置 MONEYHELPER_ALLOW_SYSTEM_ACCESS=1。"
        )


def assert_within(path: str | Path, root: str | Path, *, operation: str = "访问") -> None:
    """路径必须位于指定根目录内（用于数据目录、备份、收件箱）。"""
    target = _resolved(path)
    base = _resolved(root)
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise PermissionError(f"禁止{operation}根目录之外的路径：{path}") from exc
