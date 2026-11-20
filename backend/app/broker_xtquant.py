"""QMT/miniQMT 实盘适配器：import xtquant 才可用，否则明确报错。

从 broker_adapter.py 拆出，不改变「本机无客户端只能构造与探测」的边界。
"""

from __future__ import annotations

import os
import platform
import time
from decimal import Decimal
from typing import Any

from .broker_paper import _probe_payload
from .broker_types import OrderRequest, OrderResult, OrderSide, OrderStatus
from .logging_utils import get_logger

log = get_logger(__name__)

class XtQuantBroker:
    """QMT / miniQMT 适配器。

    要求：
    - Windows；
    - 券商已开通 miniQMT 权限；
    - `xtquant` 可从券商终端目录（userdata_mini）导入；
    - 环境变量 `QMT_USERDATA_PATH` 指向 userdata_mini，`QMT_ACCOUNT_ID` 为资金账号。
    """

    name = "xtquant"
    supports_trading = True

    def __init__(self) -> None:
        self._trader: Any = None
        self._account: Any = None
        self._connected = False
        self.path = os.getenv("QMT_USERDATA_PATH", "").strip()
        self.account_id = os.getenv("QMT_ACCOUNT_ID", "").strip()

    def probe(self) -> dict[str, Any]:
        problems = []
        if platform.system() != "Windows":
            problems.append("QMT 仅支持 Windows")
        try:
            import xtquant  # type: ignore  # noqa: F401
        except ImportError:
            problems.append("未安装 xtquant（需从券商 QMT 终端目录获取，不能 pip 安装）")
        if not self.path:
            problems.append("未设置 QMT_USERDATA_PATH（指向 userdata_mini 目录）")
        if not self.account_id:
            problems.append("未设置 QMT_ACCOUNT_ID（资金账号）")
        return _probe_payload(
            self.name, True, problems, ok_note="券商官方通道；需开通 miniQMT 权限"
        )

    def connect(self) -> None:
        info = self.probe()
        if not info["available"]:
            raise RuntimeError(info["note"])
        from xtquant import xtconstant  # type: ignore  # noqa: F401
        from xtquant.xttrader import XtQuantTrader  # type: ignore
        from xtquant.xttype import StockAccount  # type: ignore

        session_id = int(time.time()) % 2_000_000_000
        self._trader = XtQuantTrader(self.path, session_id)
        self._trader.start()
        if self._trader.connect() != 0:
            raise RuntimeError("QMT 连接失败（session 冲突或客户端未登录）")
        self._account = StockAccount(self.account_id, "STOCK")
        self._trader.subscribe(self._account)
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False
        self._trader = None
        self._account = None

    def is_connected(self) -> bool:
        return self._connected

    def get_cash(self) -> Decimal:
        if not self._connected:
            return Decimal("0")
        try:
            asset = self._trader.query_stock_asset(self._account)
            return Decimal(str(getattr(asset, "cash", 0) or 0))
        except Exception:  # noqa: BLE001 — 查询失败不抛给 UI
            return Decimal("0")

    def get_positions(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        try:
            rows = self._trader.query_stock_positions(self._account) or []
        except Exception:  # noqa: BLE001
            return []
        return [
            {
                "symbol": str(getattr(p, "stock_code", ""))[:6],
                "shares": float(getattr(p, "volume", 0) or 0),
                "available": float(getattr(p, "can_use_volume", 0) or 0),
                "cost": float(getattr(p, "open_price", 0) or 0),
            }
            for p in rows
        ]

    def preview(self, req: OrderRequest) -> OrderResult:
        # QMT 没有官方 dry-run：用本地校验代替，明确标注
        if not self._connected:
            return OrderResult(None, OrderStatus.REJECTED, message="QMT 未连接")
        if req.quantity % 100 != 0 and req.side == OrderSide.BUY:
            return OrderResult(None, OrderStatus.REJECTED, message="买入必须 100 股整数倍")
        return OrderResult(
            None,
            OrderStatus.SUBMITTED,
            message="QMT 无官方 dry-run，此处仅本地校验，实际报单由 submit 执行",
        )

    def submit(self, req: OrderRequest) -> OrderResult:
        if not self._connected:
            return OrderResult(None, OrderStatus.REJECTED, message="QMT 未连接")
        try:
            from xtquant import xtconstant  # type: ignore

            side_const = (
                xtconstant.STOCK_BUY if req.side == OrderSide.BUY else xtconstant.STOCK_SELL
            )
            code = req.symbol if "." in req.symbol else f"{req.symbol}.SH"
            order_id = self._trader.order_stock(
                self._account,
                code,
                side_const,
                int(req.quantity),
                xtconstant.FIX_PRICE,
                float(req.limit_price),
                "moneyhelper",
                req.client_order_id or "",
            )
            if order_id is None or int(order_id) < 0:
                return OrderResult(None, OrderStatus.REJECTED, message=f"QMT 拒单（返回 {order_id}）")
            return OrderResult(
                str(order_id),
                OrderStatus.SUBMITTED,
                message="委托已提交（不代表成交，需轮询对账）",
            )
        except Exception as exc:  # noqa: BLE001 — 券商异常统一转结果
            return OrderResult(None, OrderStatus.REJECTED, message=f"QMT 报单异常：{type(exc).__name__}: {exc}")

    def poll_orders(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        try:
            orders = self._trader.query_stock_orders(self._account, False) or []
        except Exception:  # noqa: BLE001
            return []
        return [
            {
                "broker_order_id": str(getattr(o, "order_id", "")),
                "symbol": str(getattr(o, "stock_code", ""))[:6],
                "status": str(getattr(o, "order_status", "")),
                "filled": float(getattr(o, "traded_volume", 0) or 0),
                "price": float(getattr(o, "traded_price", 0) or 0),
            }
            for o in orders
        ]
