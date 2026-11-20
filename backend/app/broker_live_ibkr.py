"""盈透 TWS/IB Gateway 通道：ib_insync，默认 127.0.0.1:7497。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .broker_live_base import LiveAdapterBase
from .broker_types import OrderRequest, OrderResult, OrderStatus


class IBKRBroker(LiveAdapterBase):
    """Interactive Brokers TWS/IB Gateway：ib_insync，支持美股/港股等市场。"""

    name = "ibkr"

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        super().__init__(credentials)
        self._ib: Any = None
        self.host = self._cred("host", "IB_HOST") or "127.0.0.1"
        self.port = int(self._cred("port", "IB_PORT") or "7497")
        self.client_id = int(self._cred("client_id", "IB_CLIENT_ID") or "31")

    def probe(self) -> dict[str, Any]:
        problems: list[str] = []
        try:
            import ib_insync  # type: ignore  # noqa: F401
        except ImportError:
            problems.append("未安装 ib_insync")
        return {
            "name": self.name,
            "available": not problems,
            "supports_trading": True,
            "problems": problems,
            "note": "需要本机运行 TWS/IB Gateway（默认 127.0.0.1:7497）"
            if not problems
            else "；".join(problems),
        }

    def connect(self) -> None:
        info = self.probe()
        if not info["available"]:
            raise RuntimeError(info["note"])
        from ib_insync import IB  # type: ignore

        self._ib = IB()
        self._ib.connect(self.host, self.port, clientId=self.client_id, timeout=5)
        self._connected = self._ib.isConnected()
        if not self._connected:
            raise RuntimeError("IB Gateway 连接失败")

    def disconnect(self) -> None:
        if self._ib:
            self._ib.disconnect()
        self._ib = None
        self._connected = False

    def get_cash(self) -> Decimal:
        if not self._connected:
            return Decimal("0")
        for row in self._ib.accountSummary():
            if row.tag in ("AvailableFunds", "NetLiquidation") and row.currency == "USD":
                return Decimal(str(row.value))
        return Decimal("0")

    def get_positions(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        out = []
        for p in self._ib.positions():
            out.append(
                {
                    "symbol": p.contract.symbol,
                    "market_symbol": p.contract.symbol,
                    "shares": float(p.position),
                    "available": float(p.position),
                    "cost": float(p.avgCost),
                }
            )
        return out

    def submit(self, req: OrderRequest) -> OrderResult:
        if not self._connected:
            return OrderResult(None, OrderStatus.REJECTED, message="IBKR 未连接")
        from ib_insync import LimitOrder, Stock  # type: ignore

        contract = Stock(req.symbol, "SMART", "USD")
        order = LimitOrder(req.side.value.upper(), req.quantity, float(req.limit_price))
        self._ib.placeOrder(contract, order)
        return OrderResult(str(order.orderId), OrderStatus.SUBMITTED, message="IB 委托已提交，需轮询成交")

    def poll_orders(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        return [
            {
                "broker_order_id": str(t.order.orderId),
                "symbol": t.contract.symbol,
                "status": str(t.orderStatus.status),
                "filled": float(t.orderStatus.filled or 0),
                "price": float(t.orderStatus.avgFillPrice or 0),
            }
            for t in self._ib.openTrades()
        ]
