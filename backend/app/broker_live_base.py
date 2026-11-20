"""实盘适配器基类：凭据注入、连接状态、本地预检（100 股整数倍）。"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

from .broker_types import OrderRequest, OrderResult, OrderSide, OrderStatus


class LiveAdapterBase:
    name = "live"
    supports_trading = True

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        self.credentials = {**(credentials or {})}
        self._connected = False

    def _cred(self, key: str, env: str = "") -> str:
        value = str(self.credentials.get(key) or "").strip()
        return value or os.getenv(env, "").strip()

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def get_cash(self) -> Decimal:
        return Decimal("0")

    def get_positions(self) -> list[dict[str, Any]]:
        return []

    def preview(self, req: OrderRequest) -> OrderResult:
        if not self._connected:
            return OrderResult(None, OrderStatus.REJECTED, message=f"{self.name} 未连接")
        if req.side == OrderSide.BUY and req.quantity % 100 != 0:
            return OrderResult(None, OrderStatus.REJECTED, message="买入必须 100 股整数倍")
        return OrderResult(None, OrderStatus.SUBMITTED, message=f"{self.name} 本地预检通过，实际委托需 submit")
