"""连接中心持久化门面：账户 / 配对码 / 同步任务 / 交易意图各成一模块。

表设计原则：
- 全部按租户隔离（user_id 复合主键），与仓库其他业务表口径一致；
- 平台密码、支付密码、短信验证码**永远不落库**：只存用户自己填的展示备注
  与「账号后四位」这类辨识信息；
- 任务与意图都是事件记录，不可变字段只追加，状态机单向推进；
- 每张表都带 created_at/updated_at，前端按时间排序不依赖 id。
"""

from __future__ import annotations

from ..timeutil import new_id as _new_id  # noqa: F401 — 旧口径兼容
from ..timeutil import now_iso as _now  # noqa: F401 — 时间戳策略守卫要求门面暴露 _now(AWARE)
from .store_common import (  # noqa: F401 — 对外同名导出
    CONNECTION_STATUSES,
    INTENT_STATUSES,
    JOB_STATUSES,
    MAX_CONNECTIONS,
    MAX_INTENTS,
    PAIRING_TTL_MINUTES,
    _dumps,
    _loads,
    log,
)
from .store_connections import (  # noqa: F401 — 对外同名导出
    create_connection,
    delete_connection,
    get_connection,
    list_connections,
    touch_sync,
    update_connection,
)
from .store_intents import (  # noqa: F401 — 对外同名导出
    create_intent,
    get_intent,
    list_intents,
    update_intent,
)
from .store_jobs import create_job, finish_job, list_jobs  # noqa: F401 — 对外同名导出
from .store_pairing import (  # noqa: F401 — 对外同名导出
    issue_pairing_code,
    redeem_pairing_code,
)
