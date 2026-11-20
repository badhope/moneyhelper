"""富途 OpenD 通道：港股/美股/A 股，依赖本机 OpenD 11111。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .broker_live_base import LiveAdapterBase
from .broker_types import OrderRequest, OrderResult, OrderSide, OrderStatus


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
