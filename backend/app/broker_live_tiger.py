"""老虎 OpenAPI 通道：Tiger ID/私钥/账户。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .broker_live_base import LiveAdapterBase
from .broker_types import OrderRequest, OrderResult, OrderSide, OrderStatus


class TigerBroker(LiveAdapterBase):
    """老虎 OpenAPI：官方 Python SDK，支持美港股；A 股不一定在账户权限内。"""

    name = "tiger"

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        super().__init__(credentials)
        self._client: Any = None
        self.account = self._cred("account", "TIGER_ACCOUNT")

    def probe(self) -> dict[str, Any]:
        problems: list[str] = []
        try:
            from tigeropen.tiger_open_client import TigerOpenClient  # type: ignore  # noqa: F401
            from tigeropen.tiger_open_config import TigerOpenClientConfig  # type: ignore  # noqa: F401
        except ImportError:
            problems.append("未安装 tigeropen")
        for key, env in (("tiger_id", "TIGER_ID"), ("private_key", "TIGER_PRIVATE_KEY"), ("account", "TIGER_ACCOUNT")):
            if not self._cred(key, env):
                problems.append(f"未配置 {key}（或环境变量 {env}）")
        return {
            "name": self.name,
            "available": not problems,
            "supports_trading": True,
            "problems": problems,
            "note": "老虎官方 OpenAPI：需要 Tiger ID / 私钥 / 账户"
            if not problems
            else "；".join(problems),
        }

    def connect(self) -> None:
        info = self.probe()
        if not info["available"]:
            raise RuntimeError(info["note"])
        import logging

        from tigeropen.tiger_open_client import TigerOpenClient  # type: ignore
        from tigeropen.tiger_open_config import TigerOpenClientConfig  # type: ignore

        cfg = TigerOpenClientConfig(props_path=False)
        cfg.tiger_id = self._cred("tiger_id", "TIGER_ID")
        cfg.account = self.account
        cfg.private_key = self._cred("private_key", "TIGER_PRIVATE_KEY")
        cfg.license = self._cred("license", "TIGER_LICENSE") or None
        cfg.is_paper = self._cred("paper", "TIGER_PAPER").lower() in ("1", "true", "yes")
        # Tiger SDK 在 logger=None 时有版本 bug：后续访问 __logger 会 AttributeError。
        self._client = TigerOpenClient(cfg, logger=logging.getLogger("tigeropen"))
        self._connected = True

    def disconnect(self) -> None:
        self._client = None
        self._connected = False

    def get_cash(self) -> Decimal:
        if not self._connected:
            return Decimal("0")
        rows = self._client.trade.get_assets(self.account) or []
        if isinstance(rows, list) and rows:
            row = rows[0]
            return Decimal(str(getattr(row, "net_liquidation", 0) or getattr(row, "cash", 0) or 0))
        return Decimal("0")

    def get_positions(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        rows = self._client.trade.get_positions(self.account) or []
        return [
            {
                "symbol": str(getattr(p, "contract", "") or getattr(p, "symbol", "")),
                "shares": float(getattr(p, "quantity", 0) or 0),
                "available": float(getattr(p, "quantity", 0) or 0),
                "cost": float(getattr(p, "average_cost", 0) or 0),
            }
            for p in rows
        ]

    def submit(self, req: OrderRequest) -> OrderResult:
        if not self._connected:
            return OrderResult(None, OrderStatus.REJECTED, message="tiger 未连接")
        try:
            from tigeropen.trade.domain.contract import Contract, SecurityType  # type: ignore
            from tigeropen.trade.domain.order import OrderType  # type: ignore

            exchange = "NYSE" if req.symbol.isalpha() else "SEHK"
            contract = Contract(symbol=req.symbol, currency="USD", sec_type=SecurityType.STK, exchange=exchange)
            action = "BUY" if req.side == OrderSide.BUY else "SELL"
            order = self._client.trade.create_order(
                self.account,
                contract,
                action,
                OrderType.LMT,
                int(req.quantity),
                limit_price=float(req.limit_price),
            )
            result = self._client.trade.place_order(order)
            oid = str(getattr(result, "id", None) or getattr(result, "order_id", result))
            return OrderResult(oid, OrderStatus.SUBMITTED, message="Tiger 委托已提交，需轮询成交")
        except Exception as exc:  # noqa: BLE001
            return OrderResult(None, OrderStatus.REJECTED, message=f"Tiger 报单异常：{type(exc).__name__}: {exc}")

    def poll_orders(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        try:
            rows = self._client.trade.get_open_orders(self.account) or []
        except Exception:  # noqa: BLE001
            return []
        return [{"broker_order_id": str(getattr(o, "id", "")), "status": str(getattr(o, "status", ""))} for o in rows]
