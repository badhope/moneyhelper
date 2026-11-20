"""easytrader 实盘适配器：pywinauto 驱动客户端 GUI，仅 Windows 可用。

从 broker_adapter.py 拆出。
"""

from __future__ import annotations

import os
import platform
import secrets
from decimal import Decimal
from typing import Any

from .broker_paper import _probe_payload
from .broker_types import OrderRequest, OrderResult, OrderSide, OrderStatus
from .logging_utils import get_logger

log = get_logger(__name__)

class EasytraderBroker:
    """easytrader 适配器：驱动券商客户端 GUI。

    只在 Windows + 已登录客户端时可用；脆弱但零门槛。
    真实环境下用户需自己锁定客户端版本（见调研结论）。
    """

    name = "easytrader"
    supports_trading = True

    def __init__(self) -> None:
        self._user: Any = None
        self._connected = False
        self.exe_path = os.getenv("EASYTRADER_EXE_PATH", "").strip()
        self.account = os.getenv("EASYTRADER_ACCOUNT", "").strip()
        self.password = os.getenv("EASYTRADER_PASSWORD", "").strip()

    def probe(self) -> dict[str, Any]:
        problems = []
        if platform.system() != "Windows":
            problems.append("easytrader 仅支持 Windows")
        try:
            import easytrader  # type: ignore  # noqa: F401
        except ImportError:
            problems.append("未安装 easytrader（pip install easytrader）")
        if not self.exe_path:
            problems.append("未设置 EASYTRADER_EXE_PATH（券商下单程序路径）")
        if not self.account or not self.password:
            problems.append("未设置 EASYTRADER_ACCOUNT / EASYTRADER_PASSWORD")
        return _probe_payload(
            self.name,
            True,
            problems,
            ok_note="GUI 自动化，客户端升级易失效；建议锁定客户端版本",
        )

    def connect(self) -> None:
        info = self.probe()
        if not info["available"]:
            raise RuntimeError(info["note"])
        import easytrader  # type: ignore

        self._user = easytrader.use("universal_client")
        self._user.prepare(user=self.account, password=self.password, exe_path=self.exe_path)
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False
        self._user = None

    def is_connected(self) -> bool:
        return self._connected

    def get_cash(self) -> Decimal:
        if not self._connected:
            return Decimal("0")
        try:
            balance = self._user.balance
            if isinstance(balance, list) and balance:
                return Decimal(str(balance[0].get("资金余额") or 0))
            return Decimal(str(balance.get("资金余额") or 0))
        except Exception:  # noqa: BLE001
            return Decimal("0")

    def get_positions(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        try:
            rows = self._user.position or []
        except Exception:  # noqa: BLE001
            return []
        out = []
        for row in rows:
            code = str(row.get("证券代码") or "")[:6]
            if not code:
                continue
            out.append(
                {
                    "symbol": code,
                    "shares": float(row.get("股票余额") or 0),
                    "available": float(row.get("可用余额") or 0),
                    "cost": float(row.get("成本价") or 0),
                }
            )
        return out

    def preview(self, req: OrderRequest) -> OrderResult:
        if not self._connected:
            return OrderResult(None, OrderStatus.REJECTED, message="easytrader 未连接")
        if req.quantity % 100 != 0 and req.side == OrderSide.BUY:
            return OrderResult(None, OrderStatus.REJECTED, message="买入必须 100 股整数倍")
        return OrderResult(None, OrderStatus.SUBMITTED, message="easytrader 无 dry-run，仅本地校验")

    def submit(self, req: OrderRequest) -> OrderResult:
        if not self._connected:
            return OrderResult(None, OrderStatus.REJECTED, message="easytrader 未连接")
        try:
            if req.side == OrderSide.BUY:
                self._user.buy(req.symbol, price=float(req.limit_price), amount=int(req.quantity))
            else:
                self._user.sell(req.symbol, price=float(req.limit_price), amount=int(req.quantity))
            return OrderResult(
                f"et-{secrets.token_hex(4)}",
                OrderStatus.SUBMITTED,
                message="委托已提交（GUI 操作，需查当日委托确认）",
            )
        except Exception as exc:  # noqa: BLE001
            return OrderResult(None, OrderStatus.REJECTED, message=f"easytrader 报单异常：{type(exc).__name__}: {exc}")

    def poll_orders(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        try:
            rows = self._user.today_entrusts or []
        except Exception:  # noqa: BLE001
            return []
        return [
            {
                "broker_order_id": str(r.get("委托编号") or ""),
                "symbol": str(r.get("证券代码") or "")[:6],
                "status": str(r.get("委托状态") or ""),
                "filled": float(r.get("成交数量") or 0),
                "price": float(r.get("成交均价") or 0),
            }
            for r in rows
        ]
