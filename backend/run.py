"""小满 EXE 入口：双击启动后端 + 自动打开浏览器。

打包后用户双击 xiaoman.exe：
1. 启动 FastAPI 后端（127.0.0.1:8788）
2. 自动打开默认浏览器
3. 控制台窗口显示日志，关掉窗口就停服务
"""

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# 数据目录：打包后统一放用户目录，避免写在程序（临时解压）目录里导致重启丢数据
_DATA_DIR = Path(os.getenv("XIAOMAN_DATA_DIR") or (Path.home() / ".xiaoman"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("XIAOMAN_DATA_DIR", str(_DATA_DIR))

# 确保 app 目录在 path 里（源码运行时需要；打包后已在 sys.path）
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).parent))

import uvicorn  # noqa: E402
from app.main import app  # noqa: E402


def _safe_console() -> None:
    """让控制台能输出中文。

    Windows 上双击运行 exe 时 stdout 默认是 GBK（cp936）或 cp1252，
    打印中文横幅会抛 UnicodeEncodeError 直接闪退（CI 冒烟测试实测复现）。
    这里把标准输出/错误切成 UTF-8，并忽略无法编码的字符作为最后兜底。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — 老 Python / 被重定向时不支持 reconfigure
            pass


def open_browser_later(delay: float = 1.5):
    """延迟几秒后打开浏览器，等后端起来。

    XIAOMAN_NO_BROWSER=1 时跳过：自动化验证/截图流程用 Playwright 自己的浏览器，
    不应该在用户桌面弹出系统浏览器窗口。
    """
    if os.getenv("XIAOMAN_NO_BROWSER", "").strip() in ("1", "true", "yes"):
        return

    def _open():
        time.sleep(delay)
        webbrowser.open(f"http://127.0.0.1:{os.getenv('PORT', '8788')}")

    threading.Thread(target=_open, daemon=True).start()


def main():
    port = int(os.getenv("PORT", "8788"))
    host = "127.0.0.1"

    _safe_console()
    print("=" * 50)
    print("  小满 — 对话优先的个人理财 Agent")
    print("=" * 50)
    print(f"  地址：http://{host}:{port}")
    print(f"  数据目录：{_DATA_DIR}")
    print("=" * 50)
    print("  按 Ctrl+C 或关掉窗口退出")
    print()

    # 自动打开浏览器
    open_browser_later()

    # 启动后端
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
