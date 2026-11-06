"""桌面/单文件启动器：一个可执行文件同时提供 Web UI 与后台 API。

为什么需要它：Tauri 方案要求 Rust 工具链与平台 SDK，在多数机器上装不起来，
等于「桌面版」只存在于文档里。这个入口用 PyInstaller 打成单文件 exe 后，
用户双击即可：自动选端口 → 起服务 → 打开浏览器。零外部依赖、零配置。

设计：
  - 端口占用自动顺延（8080→8081…），不因端口冲突启动失败；
  - 数据目录默认放用户目录（Windows: %APPDATA%，其余: ~/.moneyhelper），
    避免「exe 放桌面，数据库也散在桌面」；
  - 首次启动自动建库并打印访问地址；
  - Ctrl+C / 关窗口时优雅关闭（关闭 DB 连接，避免 WAL 残留）。

用法：
    python -m moneyhelper.launcher            # 默认端口 8787，自动开浏览器
    python -m moneyhelper.launcher --no-open  # 不开浏览器（CI/服务器）
    python -m moneyhelper.launcher --port 9000
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _default_data_dir() -> Path:
    """用户级数据目录：跨平台、可写、不依赖当前工作目录。"""
    if sys.platform.startswith("win"):
        base = os.getenv("APPDATA") or str(Path.home())
        return Path(base) / "Moneyhelper"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Moneyhelper"
    return Path(os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")) / "moneyhelper"


def _free_port(start: int, tries: int = 20) -> int:
    """从 start 开始找一个可绑定端口；全被占用时抛 RuntimeError。"""
    for offset in range(tries):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError(f"{start}~{start + tries - 1} 端口都被占用，请用 --port 指定其他端口")


def _open_browser_later(url: str, delay: float = 2.0) -> None:
    """等服务器起来再开浏览器（否则会看到连接被拒）。"""
    def _run() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 — 打开失败不影响服务
            pass

    threading.Thread(target=_run, daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="moneyhelper-desktop",
        description="Moneyhelper 桌面启动器：起本地服务并打开界面",
    )
    try:
        default_port = int(os.environ.get("PORT") or 8787)
    except ValueError:
        # 某些平台注入 tcp://host:port 这类值；退回默认端口而不是抛堆栈
        print(f"忽略无法解析的 PORT={os.environ.get('PORT')!r}，改用 8787", file=sys.stderr)
        default_port = 8787
    parser.add_argument(
        "--port", type=int, default=default_port, help="监听端口（默认读 PORT 环境变量，被占用时自动顺延）"
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--data-dir", default="", help="数据目录（默认用户级目录）")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else _default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MONEYHELPER_DATA_DIR", str(data_dir))
    os.environ.setdefault("MONEYHELPER_DB_PATH", str(data_dir / "wealth.db"))

    port = _free_port(args.port)
    url = f"http://{args.host}:{port}"

    print("=" * 56)
    print(" Moneyhelper")
    print(f" 访问地址: {url}")
    print(f" 数据目录: {data_dir}")
    print(" 关闭此窗口即停止服务（数据已自动保存）")
    print("=" * 56)

    if not args.no_open:
        _open_browser_later(url)

    try:
        import uvicorn
    except ImportError:
        print("缺少依赖：uvicorn。请先执行 pip install -r requirements.txt", file=sys.stderr)
        return 1

    # 延迟导入，确保上面的环境变量已生效（DB 路径在 import 时读取）
    try:
        from app.main import app  # type: ignore[import-not-found]
    except ImportError:
        # PyInstaller 打包后模块路径可能不同，退回相对导入
        try:
            from backend.app.main import app  # type: ignore[import-not-found]
        except ImportError as exc:
            print(f"无法加载应用：{exc}", file=sys.stderr)
            return 1

    try:
        uvicorn.run(app, host=args.host, port=port, log_level="info", access_log=False)
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
