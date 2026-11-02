"""可配置的真实券商 API 适配器（v4.7）。

已接入的真实通道：
- futu：富途 OpenD（futu-api），需要本机 OpenD 11111 端口与交易权限；
- longport：长桥 OpenAPI（longport），需要 App Key/Secret/Access Token；
- tiger：老虎 OpenAPI（tigeropen），需要 Tiger ID/私钥/账户；
- ib：盈透 TWS/IB Gateway（ib_insync），需要本机 7496/7497 连接；
- xtquant / easytrader：延续 v4.6 的 QMT 与 GUI 通道。

每个适配器都支持：probe → connect → cash/positions → preview → submit → poll。
真实凭据由上层通过 vault 解密后以 dict 传入；本模块不从请求体记录密码，不打印凭据。
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any

from .broker_adapter import OrderRequest, OrderResult, OrderSide, OrderStatus

log = logging.getLogger(__name__)


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


class FutuBroker(LiveAdapterBase):
    """富途 OpenD：支持港股/美股/中国 A 股（取决于账号权限与 OpenD 配置）。"""

    name = "futu"

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        super().__init__(credentials)
        self._ctx: Any = None
        self.host = self._cred("host", "FUTU_OPEND_HOST") or "127.0.0.1"
        self.port = int(self._cred("port", "FUTU_OPEND_PORT") or "11111")
        self.market = self._cred("market", "FUTU_TRADE_MARKET") or "HK"
        self.account_id = int(self._cred("account_id", "FUTU_ACCOUNT_ID") or "0")
        self.env = self._cred("trade_env", "FUTU_TRADE_ENV") or "REAL"
        self.currency = self._cred("currency", "FUTU_CURRENCY") or "HKD"

    def probe(self) -> dict[str, Any]:
        problems: list[str] = []
        try:
            import futu  # type: ignore  # noqa: F401
        except ImportError:
            problems.append("未安装 futu-api")
        if not self.account_id:
            problems.append("未设置 FUTU_ACCOUNT_ID（或通过连接配置）")
        return {
            "name": self.name,
            "available": not problems,
            "supports_trading": True,
            "problems": problems,
            "note": "需要本机运行 Futu OpenD（默认 127.0.0.1:11111）与富途交易权限"
            if not problems
            else "；".join(problems),
        }

    def connect(self) -> None:
        info = self.probe()
        if not info["available"]:
            raise RuntimeError(info["note"])
        import futu as ft  # type: ignore

        market = getattr(ft.TrdMarket, self.market, ft.TrdMarket.HK)
        firm = getattr(ft.SecurityFirm, self._cred("security_firm", "FUTU_SECURITY_FIRM") or "NONE", ft.SecurityFirm.NONE)
        self._ctx = ft.OpenSecTradeContext(
            filter_trdmarket=market,
            host=self.host,
            port=self.port,
            security_firm=firm,
        )
        ret, _data = self._ctx.get_acc_list()
        if ret != ft.RET_OK:
            self._ctx.close()
            self._ctx = None
            raise RuntimeError(f"Futu OpenD 连接失败：{_data}")
        self._connected = True

    def disconnect(self) -> None:
        try:
            if self._ctx:
                self._ctx.close()
        finally:
            self._ctx = None
            self._connected = False

    def _trd_env(self) -> Any:
        import futu as ft  # type: ignore

        return getattr(ft.TrdEnv, self.env, ft.TrdEnv.REAL)

    def get_cash(self) -> Decimal:
        if not self._connected:
            return Decimal("0")
        ret, data = self._ctx.accinfo_query(
            trd_env=self._trd_env(), acc_id=self.account_id, currency=self.currency
        )
        if ret != 0 or data is None or len(data) == 0:
            return Decimal("0")
        row = data.iloc[0].to_dict()
        return Decimal(str(row.get("cash") or row.get("available_cash") or 0))

    def get_positions(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        ret, data = self._ctx.position_list_query(
            trd_env=self._trd_env(), acc_id=self.account_id, currency=self.currency
        )
        if ret != 0 or data is None:
            return []
        return [
            {
                "symbol": str(row.get("code") or "").split(".")[-1],
                "market_symbol": str(row.get("code") or ""),
                "name": str(row.get("stock_name") or ""),
                "shares": float(row.get("qty") or 0),
                "available": float(row.get("can_sell_qty") or row.get("qty") or 0),
                "cost": float(row.get("cost_price") or 0),
                "market_value": float(row.get("market_val") or 0),
            }
            for row in data.to_dict("records")
        ]

    def submit(self, req: OrderRequest) -> OrderResult:
        if not self._connected:
            return OrderResult(None, OrderStatus.REJECTED, message="futu 未连接")
        import futu as ft  # type: ignore

        code = req.symbol
        if self.market == "HK" and "." not in code:
            code = f"HK.{code}"
        elif self.market == "US" and "." not in code:
            code = f"US.{code}"
        elif self.market == "CN" and "." not in code:
            code = f"SH.{code}" if code.startswith(("6", "68")) else f"SZ.{code}"
        side = ft.TrdSide.BUY if req.side == OrderSide.BUY else ft.TrdSide.SELL
        order_type = ft.OrderType.NORMAL
        ret, data = self._ctx.place_order(
            price=float(req.limit_price),
            qty=int(req.quantity),
            code=code,
            trd_side=side,
            order_type=order_type,
            trd_env=self._trd_env(),
            acc_id=self.account_id,
            remark=req.reason or "moneyhelper",
        )
        if ret != ft.RET_OK:
            return OrderResult(None, OrderStatus.REJECTED, message=f"Futu 拒单：{data}")
        order_id = str(data.iloc[0].get("order_id") if hasattr(data, "iloc") else data)
        return OrderResult(order_id, OrderStatus.SUBMITTED, message="Futu 委托已提交，需轮询成交")

    def poll_orders(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        ret, data = self._ctx.order_list_query(
            trd_env=self._trd_env(), acc_id=self.account_id, order_market="N/A"
        )
        if ret != 0 or data is None:
            return []
        return data.to_dict("records")


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
