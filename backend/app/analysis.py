"""确定性分析内核门面：风控规则、下一步建议、模板叙述与仪表盘快照。

原则：数字只来自数据，规则永远比模型可靠。模型只负责把这里的结果"讲成人话"，
模板叙述则保证无模型时也能给出完整、可复核的回答。

本模块不碰网络（行情由 quotes 层负责）；实现按域拆到 analysis_rules /
analysis_template / analysis_dashboard，门面 re-export 保持 analysis.X 可用。
"""

from __future__ import annotations

from .analysis_dashboard import (  # noqa: F401 — 缓存实例与快照入口
    _DASHBOARD_TTL_SECONDS,
    _dashboard_cache,
    collect_dashboard,
    invalidate_dashboard_cache,
)
from .analysis_rules import next_step_advice, risk_checks  # noqa: F401 — 对外同名导出
from .analysis_template import (  # noqa: F401 — 对外同名导出
    NO_DATA_ANSWER,
    NO_DATA_ANSWER_EN,
    no_data_answer,
    template_answer,
)

DISCLAIMER = "以上为基于你的组合与账本数据的洞察，不构成投资建议。"
DISCLAIMER_EN = "This is an insight based on your portfolio and ledger data, not investment advice."

from .analysis_health import (  # noqa: F401,E402 — 对外同名导出
    HEALTH_STATUS_EN,
    HEALTH_WORDS,
    goal_progress,
    health_check,
    health_report_text,
)
from .analysis_views import (  # noqa: F401,E402 — 对外同名导出
    CONCENTRATION_MAX_PCT,
    DTI_WARN_PCT,
    HIGH_RATE_DEBT,
    SAVINGS_RATE_WARN_PCT,
    _month_prefix,
    _num,
    ledger_view,
    market_view,
)
