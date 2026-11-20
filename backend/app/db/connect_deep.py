"""连接域深度能力门面：发票 / 交割单导入 / 条件单 / 风控设置。

子模块各管一张表族，门面保留 `_now`（带偏移）以守住时间戳策略。
"""

from __future__ import annotations

from ..logging_utils import get_logger
from ..timeutil import now_iso as _now  # noqa: F401 — 时间戳策略按模块名守，必须保留

log = get_logger(__name__)

__all__ = [
    "create_conditional",
    "delete_conditional",
    "delete_invoice",
    "file_hash",
    "get_conditional",
    "get_invoice",
    "get_risk_settings",
    "invoice_summary",
    "list_brokerage_imports",
    "list_conditionals",
    "list_invoices",
    "record_brokerage_import",
    "save_invoice",
    "save_risk_settings",
    "update_conditional_status",
    "update_invoice_status",
]

from .connect_conditionals import (  # noqa: F401,E402 — 对外同名导出
    CONDITIONAL_STATUSES,
    MAX_CONDITIONAL,
    TRIGGER_TYPES,
    create_conditional,
    delete_conditional,
    get_conditional,
    list_conditionals,
    update_conditional_status,
)
from .connect_imports import (  # noqa: F401,E402 — 对外同名导出
    list_brokerage_imports,
    record_brokerage_import,
)
from .connect_invoices import (  # noqa: F401,E402 — 对外同名导出
    INVOICE_STATUSES,
    MAX_INVOICES,
    delete_invoice,
    file_hash,
    get_invoice,
    invoice_summary,
    list_invoices,
    save_invoice,
    update_invoice_status,
)
from .connect_risk import (  # noqa: F401,E402 — 对外同名导出
    RISK_DEFAULTS,
    get_risk_settings,
    save_risk_settings,
)
