"""长任务门面：落盘 / 模板 / 任务定义 / 执行器。

长任务的本质是 **持久化 + 分段 + 可续跑**，用最少的代码把这三件事做对；
多 agent 编排归 agent_graph，不在这里做。
"""

from __future__ import annotations

from .logging_utils import get_logger
from .timeutil import now_str as _now  # noqa: F401 — 时间戳策略按模块名守，必须保留

log = get_logger(__name__)

__all__ = [
    "MAX_STAGES",
    "MAX_STAGE_CHARS",
    "MAX_TOTAL_SECONDS",
    "TEMPLATES",
    "cancel_task",
    "create_task",
    "get_task",
    "list_tasks",
    "list_templates",
    "read_artifact",
    "run_task",
    "start_task",
]

from .longtask_runner import (  # noqa: F401,E402
    MAX_STAGE_CHARS,
    MAX_TOTAL_SECONDS,
    cancel_task,
    run_task,
    start_task,
)
from .longtask_store import (  # noqa: F401,E402
    _artifact_dir,
    _read,
    _root,
    _task_dir,
    _write,
)
from .longtask_tasks import (  # noqa: F401,E402
    MAX_STAGES,
    _context,
    create_task,
    get_task,
    list_tasks,
    read_artifact,
)
from .longtask_templates import TEMPLATES, list_templates  # noqa: F401,E402
