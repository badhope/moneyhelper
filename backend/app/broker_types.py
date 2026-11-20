"""券商适配层的数据类型：方向/状态枚举、下单请求与结果、适配器协议。

从 broker_adapter.py 拆出，适配器实现与护栏逻辑分居其它模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class OrderSide(str, Enum):  # noqa: UP042 — 需兼容 Python 3.10（StrEnum 是 3.11+）
    BUY = "buy"
    SELL = "sell"

class OrderStatus(str, Enum):  # noqa: UP042 — 同上
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"

@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: OrderSide
    quantity: int
    limit_price: Decimal
    client_order_id: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "limit_price": float(self.limit_price),
            "client_order_id": self.client_order_id,
            "reason": self.reason,
        }

@dataclass
class OrderResult:
    broker_order_id: str | None
    status: OrderStatus
    filled_quantity: int = 0
    average_price: Decimal | None = None
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "broker_order_id": self.broker_order_id,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "average_price": float(self.average_price) if self.average_price is not None else None,
            "message": self.message,
        }

@runtime_checkable
class BrokerAdapter(Protocol):
    name: str
    supports_trading: bool

    def probe(self) -> dict[str, Any]: ...
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...
    def get_cash(self) -> Decimal: ...
    def get_positions(self) -> list[dict[str, Any]]: ...
    def preview(self, req: OrderRequest) -> OrderResult: ...
    def submit(self, req: OrderRequest) -> OrderResult: ...
    def poll_orders(self) -> list[dict[str, Any]]: ...
