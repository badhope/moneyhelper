"""统一日志：RotatingFileHandler 落 backend/logs/moneyhelper.log，控制台输出。

用法：
    from .logging_utils import get_logger
    log = get_logger(__name__)
    log.info("agent action: sell 600519 @ 1500.00")
    log.exception("unexpected error in /api/ask")   # 带完整 traceback 写 error

文件按 5MB 轮转，保留 3 份历史；控制台始终输出 INFO+。
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "moneyhelper.log"
_ROTATE_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_ROTATE_BACKUP_COUNT = 3
_FMT = "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_configured = False


class _SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """对轮转做容错：Windows 下日志文件若被其他句柄占用（如 IDE / 另一进程读取），
    常规 doRollover 的 os.rename 会抛 PermissionError，导致 logging 刷「Logging error」。
    此处吞掉文件占用类错误，跳过本次轮转、继续写当前文件，保证服务不因日志轮转受影响。"""

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except OSError:
            # 文件被占用（WinError 32）等：跳过本次轮转，保留当前句柄继续写
            pass


def _configure_root() -> None:
    global _configured
    if _configured:
        return
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 控制台（stdout，开发/容器场景）
    stream = logging.StreamHandler()
    stream.setLevel(logging.INFO)
    stream.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(stream)

    # 文件轮转（生产/本地诊断）
    file_h = _SafeRotatingFileHandler(
        _LOG_FILE,
        maxBytes=_ROTATE_MAX_BYTES,
        backupCount=_ROTATE_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(file_h)

    # 第三方库降噪：DEBUG 级对本项目排查无用，且会持续把日志文件刷爆
    # （曾因 LiteLLM/aiosqlite 的 DEBUG 行把单文件刷到数百 MB）。
    for noisy in (
        "httpx",
        "httpcore",
        "uvicorn.access",
        "aiosqlite",
        "openai",
        "mcp",
        "sse_starlette",
        "chromadb",
        # asyncio 的 Proactor 实现每建一个事件循环就打一行 DEBUG，
        # 在 Windows 上能把日志刷满整屏、把真正的告警挤没。
        "asyncio",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # LiteLLM：成本表查询/模型映射的 DEBUG 行带 traceback，看着像报错但不是；
    # 压到 ERROR（真实调用错误仍会输出）。
    logging.getLogger("LiteLLM").setLevel(logging.ERROR)
    # 平台事件循环内部实现（IocpProactor / selector）同样只保留告警以上
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """模块级 logger，统一前缀 moneyhelper.<module>。"""
    _configure_root()
    logger_name = name if name.startswith("moneyhelper") else f"moneyhelper.{name}"
    return logging.getLogger(logger_name)


def log_path() -> Path:
    return _LOG_FILE


def read_log_lines(limit: int = 200) -> list[str]:
    """读取日志文件最近 limit 行（从尾部），供 /api/logs 接口使用。"""
    if not _LOG_FILE.exists():
        return []
    with open(_LOG_FILE, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        # 读最后 200KB 足够覆盖 200 行
        f.seek(max(0, size - 200 * 1024))
        data = f.read().decode("utf-8", errors="replace")
    lines = data.splitlines()
    return lines[-limit:]


def clear_logs() -> int:
    """清空当前日志文件，返回清空前行数（供 /api/logs/clear 使用）。"""
    if not _LOG_FILE.exists():
        return 0
    with open(_LOG_FILE, encoding="utf-8", errors="replace") as f:
        count = sum(1 for _ in f)
    _LOG_FILE.write_text("")
    return count
