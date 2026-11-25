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

import importlib
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


def _litellm_data_files() -> list[tuple[str, str]]:
    """收集 LiteLLM 运行时读取的数据文件，不碰 __pycache__ 和下载来的代理面板。"""
    suffixes = {".json", ".yaml", ".yml", ".txt", ".jsonl"}
    out: list[tuple[str, str]] = []
    for file in LITELLM_DIR.rglob("*"):
        if not file.is_file() or file.suffix.lower() not in suffixes:
            continue
        rel = file.relative_to(LITELLM_DIR)
        if "__pycache__" in rel.parts or rel.parts[:2] == ("proxy", "_experimental"):
            continue
        out.append((str(file), str(Path("litellm") / rel.parent)))
    return out


def _package_data(pkg, package_name: str) -> list[tuple[str, str]]:
    """收集没有 PyInstaller hook 的包内数据文件（schema、语法、CA 证书等）。

    这类文件不是 .py，静态分析看不见；源码运行正常，打包后 import 就 FileNotFoundError。
    """
    root = Path(pkg.__file__).parent
    out: list[tuple[str, str]] = []
    for file in root.rglob("*"):
        if not file.is_file() or "__pycache__" in file.parts:
            continue
        if file.suffix in {".py", ".pyc"}:
            continue
        rel = file.relative_to(root)
        out.append((str(file), str(Path(package_name) / rel.parent)))
    return out


def _optional_package_data(module_name: str, package_name: str) -> list[tuple[str, str]]:
    """可选依赖才带数据；requirements 没装时不能把 spec 直接 import 崩掉。"""
    try:
        package = importlib.import_module(module_name)
    except ImportError:
        return []
    return _package_data(package, package_name)


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
        # LiteLLM 只读取这个备份价格表（get_model_cost_map.py 用 importlib.resources
        # 定位它）。旧实现整目录收集，会把 proxy 的 OpenAPI 快照、几十个 YAML 和
        # __pycache__ 全打进去，还在 FUSE 盘上遍历时卡死。只带运行时真正需要的文件。
        # LiteLLM 的多个模块在 import 阶段直接 open 包内 JSON（价格表、anthropic
        # tokenizer、containers/endpoints.json 等），漏一个就是启动即崩。这里按扩展名
        # 收齐数据文件，仍排除 __pycache__ 与 proxy 的 Next.js 快照，避免遍历卡死。
        *_litellm_data_files(),
        # 这些包没有官方 hook，数据文件必须手动带；漏了就是 import 期崩溃。
        *_optional_package_data("rfc3987_syntax", "rfc3987_syntax"),
        *_optional_package_data("jsonschema_specifications", "jsonschema_specifications"),
        *_optional_package_data("openapi_spec_validator", "openapi_spec_validator"),
        *_optional_package_data("certifi", "certifi"),
        *_optional_package_data("tzdata", "tzdata"),
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
        # 测试专用（requirements-dev.txt）：opencv 单目录 111MB、reportlab、qrcode。
        # 运行时只有发票识别会 try-import cv2/PIL，缺失时按「能力不可用」降级，
        # 属于已实现的优雅降级路径，不该让发行包背这 100+ MB。
        "cv2",
        # litellm 的 Bedrock 适配器会 try-import boto3；本产品从不走 Bedrock，
        # 但 PyInstaller 会把 27MB botocore 服务模型全收进去，且在某些网络盘上
        # 遍历 botocore/data 会卡死（本机 hpvs_fs 实测）。明确排除。
        "boto3",
        "botocore",
        "s3transfer",
        "aiobotocore",
        "pandas",
        "reportlab",
        "qrcode",
        "pyzbar",
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
