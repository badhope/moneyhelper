"""环境变量兼容层。

品牌改名后新变量为 `MONEYHELPER_*`；既有部署（docker-compose / systemd / .env）
里仍是旧前缀，直接改名会让数据目录、数据库路径在无声中回落到默认值——
那等于"看起来启动了，实际换了一个空账本"。这里统一按
`MONEYHELPER_* > 旧前缀 > 默认值` 解析，旧部署可平滑过渡。
"""

from __future__ import annotations

import os

_NEW_PREFIX = "MONEYHELPER_"
_LEGACY_PREFIX = "XIAOMAN_"


def getenv(name: str, default: str = "") -> str:
    """读取配置项；name 用新名（如 MONEYHELPER_DB_PATH），自动回退旧名。"""
    if not name.startswith(_NEW_PREFIX):
        raise ValueError(f"配置名必须以 {_NEW_PREFIX} 开头：{name}")
    value = os.getenv(name)
    if not value:
        value = os.getenv(_LEGACY_PREFIX + name[len(_NEW_PREFIX):])
    if not value:
        return default
    return value
