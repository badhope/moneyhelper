"""可观测性：零依赖的耗时统计与慢请求记录。

为什么不用 OpenTelemetry/Phoenix：
- 该能力需要额外 4 个包 + 一个外部 collector 才能生效，默认永远是 no-op；
- 项目真正需要的是"哪个模型/工具慢、哪个环节失败"这类本地诊断信息；
- 这些用标准库即可做到，且不引入第二套 span 体系与 audit_logs 重复。

设计：
- `timed(label)`：上下文管理器，记录一次耗时并累加到内存统计（P50/P95 用近似桶）；
- `snapshot()`：导出统计，供 /api/metrics 与日志使用；
- 超过阈值（默认 5s）时打 WARNING，方便线上直接 grep。
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .compat_env import getenv
from .logging_utils import get_logger

log = get_logger(__name__)

_SLOW_MS = int(getenv("MONEYHELPER_SLOW_MS", "5000"))

# label -> [count, total_ms, max_ms, error_count]
_stats: dict[str, list[float]] = defaultdict(lambda: [0, 0.0, 0.0, 0])


@contextmanager
def timed(label: str, **meta: Any) -> Iterator[None]:
    """包一段耗时逻辑；异常也会被计数并原样抛出。"""
    started = time.perf_counter()
    ok = True
    try:
        yield
    except Exception:
        ok = False
        raise
    finally:
        ms = (time.perf_counter() - started) * 1000
        row = _stats[label]
        row[0] += 1
        row[1] += ms
        row[2] = max(row[2], ms)
        if not ok:
            row[3] += 1
        if ms >= _SLOW_MS:
            extra = " ".join(f"{k}={v}" for k, v in meta.items())
            log.warning("slow op label=%s ms=%.0f %s", label, ms, extra)


def snapshot() -> dict[str, dict[str, float]]:
    """导出当前统计（进程内累计，重启清零）。"""
    out: dict[str, dict[str, float]] = {}
    for label, (count, total, max_ms, errors) in _stats.items():
        out[label] = {
            "count": int(count),
            "avg_ms": round(total / count, 1) if count else 0.0,
            "max_ms": round(max_ms, 1),
            "errors": int(errors),
        }
    return out


def reset() -> None:
    _stats.clear()


# ---- 兼容旧调用点（main.py 曾在 lifespan 里调用 _init/flush）----------------
def _init() -> None:
    """保留空实现：调用方无需改动，实际统计在首次 timed() 时自然开始。"""


def flush() -> None:
    """保留空实现：统计常驻内存，由 /api/metrics 或日志直接读取。"""
