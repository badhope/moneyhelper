"""无副作用适配器：NullBroker（默认拒绝）与 PaperBroker（走模拟盘撮合）。

从 broker_adapter.py 拆出；探测逻辑 _probe_payload 一并放在这里。
"""

from __future__ import annotations

import secrets
from decimal import Decimal
from typing import Any

from .broker_types import OrderRequest, OrderResult, OrderStatus
from .logging_utils import get_logger

log = get_logger(__name__)

def _probe_payload(
    name: str,
    supports_trading: bool,
    problems: list[str],
    ok_note: str,
) -> dict[str, Any]:
    """`probe()` 的统一返回形状：可用性、问题清单、人话结论。

    四个适配器原本各自手写同一份 dict 字面量，改字段（比如加 `hint`）要改四处；
    收敛后只有这一个出口，`problems` 为空即视为可用。
    """
    return {
        "name": name,
        "available": not problems,
        "supports_trading": supports_trading,
        "problems": problems,
        "note": ok_note if not problems else "；".join(problems),
    }

class _NoopBroker:
    """无外部通道的适配器基类：把「什么都不做」的接口留一份实现。

    NullBroker 与 PaperBroker 的 `connect/disconnect/poll_orders/get_cash/
    get_positions` 逐字相同（空实现），原来各写一遍；这里只写一次，
    子类只覆盖真正有差异的 `is_connected/preview/submit/probe`。
    """

    name = "noop"
    supports_trading = False

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def poll_orders(self) -> list[dict[str, Any]]:
        return []

    def get_cash(self) -> Decimal:
        return Decimal("0")

    def get_positions(self) -> list[dict[str, Any]]:
        return []

class NullBroker(_NoopBroker):
    """默认适配器：永远拒绝下单，只返回空数据。用于未启用交易的实例。"""

    name = "null"

    def probe(self) -> dict[str, Any]:
        return _probe_payload(
            self.name, False, problems=[], ok_note="默认只读适配器：未启用任何券商通道"
        )

    def is_connected(self) -> bool:
        return False

    def preview(self, req: OrderRequest) -> OrderResult:
        return OrderResult(None, OrderStatus.REJECTED, message="交易未启用（NullBroker）")

    def submit(self, req: OrderRequest) -> OrderResult:
        return OrderResult(None, OrderStatus.REJECTED, message="交易未启用（NullBroker）")

class PaperBroker(_NoopBroker):
    """模拟盘适配器：不做真实下单，只把委托交给调用方（路由层）写模拟盘。

    这里保持无状态：真正撮合在 routes 层用 calculations.paper 完成，
    适配器只负责形状统一，避免两套撮合逻辑。
    """

    name = "paper"

    def probe(self) -> dict[str, Any]:
        return _probe_payload(
            self.name,
            False,
            problems=[],
            ok_note="模拟盘：委托由系统按 A 股口径撮合，不产生真实交易",
        )

    def is_connected(self) -> bool:
        return True

    def preview(self, req: OrderRequest) -> OrderResult:
        return OrderResult(None, OrderStatus.SUBMITTED, message="模拟盘预检通过（未真实报单）")

    def submit(self, req: OrderRequest) -> OrderResult:
        return OrderResult(f"paper-{secrets.token_hex(4)}", OrderStatus.SUBMITTED, message="已交给模拟盘撮合")
