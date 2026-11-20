"""采购/应付数据层门面：供应商 → 采购单 → 应付单 → 付款。

实现按域拆到 procurement_vendor / procurement_po / procurement_payable，
共享小工具在 procurement_common；`db` 包仍从本模块取同名函数。
"""

from __future__ import annotations

from ..timeutil import now_str as _now  # noqa: F401,E402 — 时钟策略守卫要求门面暴露 _now
from .procurement_payable import (  # noqa: F401,E402
    payable_approve,
    payable_create,
    payable_get,
    payable_list,
    payable_pay,
    payable_submit,
)
from .procurement_po import (  # noqa: F401,E402
    po_approve,
    po_create,
    po_get,
    po_list,
    po_submit,
)
from .procurement_vendor import vendor_create, vendor_list  # noqa: F401,E402
