"""版本号单一真源。

改造前三处版本号各自漂移：`backend/app/__init__.py` 是 1.0.0、
`frontend/package.json` 是 1.4.0、`pyproject.toml` 与 `xiaoman/__init__.py` 是 2.1.0。
用户看到的版本取决于问哪个文件——发版说明与实际代码对不上。

现在：
- 本文件是唯一真源
- 后端各处在运行时读它（`__version__` 与 FastAPI version）
- 前端通过 Vite 的 define 在构建时注入（见 vite.config.ts），
  避免手工同步
- 发版脚本（scripts/release.sh）只改这一个文件 + package.json

版本语义遵循 SemVer；发布流程见 docs/RELEASE.md。
"""

from __future__ import annotations

# 当前版本。发版脚本会改写这一行，格式必须保持 `__version__ = "x.y.z"`。
__version__ = "2.9.2"

# 上一版（用于"自上次发版以来的变更"提示；发版脚本自动维护）
PREVIOUS_VERSION = "2.3.0"
