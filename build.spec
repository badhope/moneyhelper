# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：产出单文件可执行程序（Windows .exe / macOS / Linux 通用）。

为什么用 PyInstaller 而不是只在文档里写 Tauri：
  Tauri 需要 Rust + 平台 SDK（WiX/Xcode/webkit2gtk），多数机器装不起来；
  PyInstaller 只需 Python，任何平台都能产出可双击的程序。
  两者不冲突：Tauri 提供原生窗口体验，PyInstaller 提供「一定能跑」的兜底。

构建：
    pip install pyinstaller
    pyinstaller build.spec --clean --noconfirm
产物：
    dist/Moneyhelper.exe       （Windows）
    dist/Moneyhelper           （macOS / Linux）

注意：必须在 frontend/dist 已构建的前提下打包（否则界面 404）。
"""

from pathlib import Path

# 项目根目录（本文件所在位置）
ROOT = Path(SPECPATH).resolve()  # noqa: F821 — PyInstaller 注入的是 spec 所在目录
BACKEND = ROOT / "backend"
FRONTEND_DIST = ROOT / "frontend" / "dist"

# 界面静态资源必须随包分发：没有它 exe 打开是白屏。
datas: list[tuple[str, str]] = []
if FRONTEND_DIST.is_dir():
    # 目标路径必须是 static：app/main.py 的 _frontend_dist() 在
    # PyInstaller 环境下读 sys._MEIPASS/static（历史约定）。
    datas.append((str(FRONTEND_DIST), "static"))

# 后端的非 .py 数据文件必须随包分发：PyInstaller 只收集导入到的模块代码，
# 不会自动带上 package 目录里的 .json/.md。历史上漏收 default_studio.json，
# 导致打包版每次启动刷 30 行 "studio.default_pack_broken: No such file"，
# Studio 的内置角色/技能/约束全部缺失（服务能起，功能是空的）。
_backend_app = BACKEND / "app"
if _backend_app.is_dir():
    for pattern in ("**/*.json", "**/*.md"):
        for f in _backend_app.glob(pattern):
            if "__pycache__" in f.parts:
                continue
            # 目标路径保持相对 backend/ 的结构，模块内 __file__ 才能找到同目录文件
            datas.append((str(f), str(f.parent.relative_to(BACKEND))))

# litellm 在 import 时读取自带的 model_prices_and_context_window_backup.json，
# 该文件不是 .py，PyInstaller 默认不收 → 打包后启动即 FileNotFoundError。
# 用官方 collect_data_files 把整个包的数据文件带上。
from PyInstaller.utils.hooks import collect_data_files, collect_submodules  # noqa: E402

lib_datas: list[tuple[str, str]] = []
try:
    lib_datas += collect_data_files("litellm")
except Exception:  # noqa: BLE001 — 未安装 litellm 时不阻断构建
    pass
datas += lib_datas

# 后端纯 Python 模块需要显式收集（PyInstaller 静态分析抓不到动态导入）
hiddenimports = [
    "app.main",
    "app.db",
    "app.calculations.decisions",
    "app.calculations.bridge",
    "app.calculations.accounts",
    "app.networth_series",
    "app.report",
    "app.tool_policy",
    "app.netguard",
    "app.context",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "aiosqlite",
    "tiktoken",
    "tiktoken_ext.openai_public",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "moneyhelper" / "launcher.py")],
    pathex=[str(BACKEND), str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "matplotlib", "tkinter", "PyQt5", "PySide6"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Moneyhelper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX 常被杀软误报，金融软件不做这层压缩
    console=True,       # 保留控制台：用户能看到端口与日志，也便于排障
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
