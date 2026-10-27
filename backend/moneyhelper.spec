# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：Moneyhelper 单文件可执行程序。

用法（在 backend/ 下）：
    ..\\frontend> npm run build        # 先构建前端
    cd ..\\backend
    .venv\\Scripts\\python -m pip install pyinstaller
    .venv\\Scripts\\pyinstaller moneyhelper.spec

产物：dist/moneyhelper(.exe) —— 双击启动后端并自动打开浏览器。

数据目录：默认 ~/.moneyhelper（见 run.py），删掉可执行文件不影响数据。
"""

import re
from pathlib import Path

import litellm  # 用于定位其数据文件与子模块（打包必须带上）


def _app_version() -> str:
    """版本号单一真源：backend/app/version.py。"""
    text = (Path(SPECPATH).parent / "backend" / "app" / "version.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__ = "([^"]+)"', text, re.M)
    return m.group(1) if m else "0.0.0"


APP_VERSION = _app_version()

# PyInstaller 的 version= 需要「版本资源文件」的路径，不是版本号字符串。
# 这里按版本号生成一个临时文件（Windows 资源编译器用），保证 exe 属性里能看到版本。
_VERSION_INFO = Path(SPECPATH).parent / "build" / "version_info.txt"
_VERSION_INFO.parent.mkdir(parents=True, exist_ok=True)
_v = APP_VERSION.split(".")
_v += ["0"] * (4 - len(_v))
_VERSION_INFO.write_text(
    f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({_v[0]}, {_v[1]}, {_v[2]}, {_v[3]}), prodvers=({_v[0]}, {_v[1]}, {_v[2]}, {_v[3]}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080404b0', [StringStruct('CompanyName', 'Moneyhelper Contributors'), StringStruct('FileDescription', 'Moneyhelper - local-first personal finance agent'), StringStruct('FileVersion', '{APP_VERSION}'), StringStruct('InternalName', 'moneyhelper'), StringStruct('OriginalFilename', 'moneyhelper.exe'), StringStruct('ProductName', 'Moneyhelper'), StringStruct('ProductVersion', '{APP_VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""",
    encoding="utf-8",
)

LITELLM_DIR = Path(litellm.__file__).parent


def _all_submodules(pkg) -> list[str]:
    """递归收集包内全部子模块（走文件系统，不依赖 pkgutil 的加载器）。

    LiteLLM 有大量按需导入的子模块（如 litellm_core_utils.tokenizers），
    PyInstaller 静态分析发现不了；逐个手写 hiddenimports 必然漏。
    """
    root = Path(pkg.__file__).parent
    out: list[str] = []
    for py in root.rglob("*.py"):
        rel = py.relative_to(root).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        if any(part.startswith("_") and part not in ("__init__",) for part in parts):
            continue
        out.append("litellm." + ".".join(parts))
    return sorted(set(out))

# 前端静态文件目录（已构建）。
# SPECPATH 是 spec 所在目录（backend/），其父目录即仓库根，前端产物在根下的 frontend/dist。
FRONTEND_DIST = Path(SPECPATH).parent / "frontend" / "dist"
assert FRONTEND_DIST.is_dir(), f"前端未构建：{FRONTEND_DIST}（先 cd frontend && npm run build）"

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[
        (str(FRONTEND_DIST), "static"),
        ("app/agents", "app/agents"),
        # Studio 默认包（提示词/约束/Hook/内置工具）是运行时读取的 JSON，不是 Python 模块，
        # PyInstaller 静态分析发现不了；漏了它打包版设置页就是空的。
        ("app/studio", "app/studio"),
        # LiteLLM 运行时读取的模型价格表、tokenizer 等非 Python 资源。
        # 整目录收集比逐个列文件可靠（版本间文件名会变，漏一个就启动失败）。
        (str(LITELLM_DIR), "litellm"),
    ],
    hiddenimports=[
        # Web 层
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "sse_starlette",
        # 模型接入
        *_all_submodules(litellm),
        "openai",
        "tiktoken",
        # 编排
        "langgraph",
        "langgraph.checkpoint.sqlite",
        "langgraph.checkpoint.sqlite.aio",
        "langgraph.types",
        # MCP
        "fastmcp",
        "mcp",
        # 数据
        "aiosqlite",
        "cryptography",
        "jwt",
        "passlib",
        "bcrypt",
        # 调度与工具
        "apscheduler",
        "apscheduler.triggers.cron",
        "cn2an",
        "cachetools",
        "rank_bm25",
        "duckduckgo_search",
        "python_multipart",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 明确排除未使用的重依赖，避免打进无用体积
        "tkinter",
        "matplotlib",
        "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="moneyhelper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,  # 保留控制台便于看日志；改 False 则为纯窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(Path(SPECPATH) / "app.ico"),
    version=str(_VERSION_INFO),
)
