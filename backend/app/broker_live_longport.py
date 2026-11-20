"""长桥 OpenAPI 通道：App Key/Secret/Access Token。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .broker_live_base import LiveAdapterBase
from .broker_types import OrderRequest, OrderResult, OrderStatus


class LongPortBroker(LiveAdapterBase):
    """长桥 OpenAPI：股票/期权/基金通道，官方 Python SDK。"""

    name = "longport"

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        super().__init__(credentials)
        self._ctx: Any = None

    def probe(self) -> dict[str, Any]:
        problems: list[str] = []
        try:
            from longport.openapi import Config  # type: ignore  # noqa: F401
        except ImportError:
            problems.append("未安装 longport")
        for key, env in (("app_key", "LONGPORT_APP_KEY"), ("app_secret", "LONGPORT_APP_SECRET"), ("access_token", "LONGPORT_ACCESS_TOKEN")):
            if not self._cred(key, env):
                problems.append(f"未配置 {key}（或环境变量 {env}）")
        return {
            "name": self.name,
            "available": not problems,
            "supports_trading": True,
            "problems": problems,
            "note": "长桥官方 OpenAPI：需要申请 App Key/Secret/Access Token"
            if not problems
            else "；".join(problems),
        }

    def connect(self) -> None:
        info = self.probe()
        if not info["available"]:
            raise RuntimeError(info["note"])
        from longport.openapi import Config, TradeContext  # type: ignore

        cfg = Config.from_apikey(
            self._cred("app_key", "LONGPORT_APP_KEY"),
            self._cred("app_secret", "LONGPORT_APP_SECRET"),
            self._cred("access_token", "LONGPORT_ACCESS_TOKEN"),
        )
        self._ctx = TradeContext(cfg)
        self._connected = True

    def disconnect(self) -> None:
        self._ctx = None
        self._connected = False

    def get_cash(self) -> Decimal:
        if not self._connected:
            return Decimal("0")
        balances = self._ctx.account_balance()
        if not balances:
            return Decimal("0")
        total = getattr(balances[0], "total_cash", None) or getattr(balances[0], "net_assets", 0)
        return Decimal(str(total or 0))

    def get_positions(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        rows = self._ctx.stock_positions()
        out = []
        for group in rows or []:
            items = getattr(group, "channel", None) or getattr(group, "positions", None) or group
            for p in items or []:
                out.append(
                    {
                        "symbol": str(getattr(p, "symbol", "")).split(".")[0],
                        "market_symbol": str(getattr(p, "symbol", "")),
                        "name": str(getattr(p, "stock_name", "")),
                        "shares": float(getattr(p, "quantity", 0) or 0),
                        "available": float(getattr(p, "available_quantity", 0) or 0),
                        "cost": float(getattr(p, "cost_price", 0) or 0),
                    }
                )
        return out

    def _symbol(self, symbol: str) -> str:
        if "." in symbol:
            return symbol
        return f"{symbol}.SH" if symbol.startswith(("6", "68")) else f"{symbol}.SZ"

    def submit(self, req: OrderRequest) -> OrderResult:
        if not self._connected:
            return OrderResult(None, OrderStatus.REJECTED, message="longport 未连接")
        from longport.openapi import OrderSide, OrderType, TimeInForceType  # type: ignore

        side = OrderSide.Buy if req.side == OrderSide.BUY else OrderSide.Sell
        response = self._ctx.submit_order(
            self._symbol(req.symbol),
            OrderType.LO,
            side,
            int(req.quantity),
            TimeInForceType.Day,
            submitted_price=float(req.limit_price),
            remark=req.reason or "moneyhelper",
        )
        order_id = str(getattr(response, "order_id", response))
        return OrderResult(order_id, OrderStatus.SUBMITTED, message="LongPort 委托已提交，需轮询成交")

    def poll_orders(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        return [
            {
                "broker_order_id": str(getattr(o, "order_id", "")),
                "symbol": str(getattr(o, "symbol", "")),
                "status": str(getattr(o, "status", "")),
                "filled": float(getattr(o, "executed_quantity", 0) or 0),
                "price": float(getattr(o, "executed_price", 0) or 0),
            }
            for o in (self._ctx.today_orders() or [])
        ]
