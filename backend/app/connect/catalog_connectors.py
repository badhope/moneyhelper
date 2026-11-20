"""内置连接器清单门面：汇总四个业务段的条目为单一 `CONNECTORS` 列表。

顺序保持拆分前语义（行情 → 券商 → 基金/银行 → 支付/发票/财税）。
"""

from __future__ import annotations

from typing import Any

from .catalog_conn_broker import ENTRIES as _broker
from .catalog_conn_fund_bank import ENTRIES as _fund_bank
from .catalog_conn_pay_flow import ENTRIES as _pay_flow
from .catalog_conn_quote import ENTRIES as _quote

CONNECTORS: list[dict[str, Any]] = [*_quote, *_broker, *_fund_bank, *_pay_flow]
