"""券商执行适配层（v4.6）：把「自动下单」做成可插拔、默认关闭、有护栏的能力。

调研结论（见 docs/connect-hub-deep.md 的引用）：
- **QMT / miniQMT（xtquant）** 是国内唯一「券商官方提供」的个人可用交易 API，
  但有资金/权限门槛，且 `xtquant` 不能 pip 安装（需从券商终端目录取）；
- **easytrader** 用 pywinauto 驱动券商客户端 GUI，脆弱（客户端升级即失效、需要 Windows），
  但覆盖面最广、零门槛；
- **vnpy** 更偏机构，股票实盘网关通常需机构权限。

因此本模块的定位是**适配层 + 护栏**，不是一个「能直接下单」的黑盒：

    BrokerAdapter（协议）
      ├── NullBroker      默认：只读、拒绝一切下单
      ├── PaperBroker     模拟盘：复用既有 calculations.paper 撮合
      ├── XtQuantBroker   实盘：import xtquant 才可用，否则明确报错
      └── EasytraderBroker 实盘：import easytrader 才可用，仅 Windows

安全护栏（全部在 `guarded_submit()` 里强制执行，适配器自身无法绕过）：
1. 全局开关 `trading_enabled`（默认 false）；
2. dry_run 默认 true；
3. 白名单券商；
4. 单笔/单日金额上限、单票持仓比例上限；
5. 二次确认 token（由 `preview()` 签发，绑定标的/方向/价格/数量，5 分钟过期）；
6. 全量审计（provenance）；
7. 券商返回值只代表「委托已提交」，成交状态必须靠 `poll_orders()` 对账。

本机没有券商客户端，因此实盘适配器只能做**构造与探测**，不能真实下单——
这不是缺陷，是设计：本模块交付的是「可被用户在自己的机器上启用的执行层」。
"""

from __future__ import annotations

import os
import platform
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
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


# ---------------------------------------------------------------------------
# 默认：只读
# ---------------------------------------------------------------------------


class NullBroker:
    """默认适配器：永远拒绝下单，只返回空数据。用于未启用交易的实例。"""

    name = "null"
    supports_trading = False

    def probe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": True,
            "supports_trading": False,
            "note": "默认只读适配器：未启用任何券商通道",
        }

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def is_connected(self) -> bool:
        return False

    def get_cash(self) -> Decimal:
        return Decimal("0")

    def get_positions(self) -> list[dict[str, Any]]:
        return []

    def preview(self, req: OrderRequest) -> OrderResult:
        return OrderResult(None, OrderStatus.REJECTED, message="交易未启用（NullBroker）")

    def submit(self, req: OrderRequest) -> OrderResult:
        return OrderResult(None, OrderStatus.REJECTED, message="交易未启用（NullBroker）")

    def poll_orders(self) -> list[dict[str, Any]]:
        return []


# ---------------------------------------------------------------------------
# 模拟盘
# ---------------------------------------------------------------------------


class PaperBroker:
    """模拟盘适配器：不做真实下单，只把委托交给调用方（路由层）写模拟盘。

    这里保持无状态：真正撮合在 routes 层用 calculations.paper 完成，
    适配器只负责形状统一，避免两套撮合逻辑。
    """

    name = "paper"
    supports_trading = False

    def probe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": True,
            "supports_trading": False,
            "note": "模拟盘：委托由系统按 A 股口径撮合，不产生真实交易",
        }

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def is_connected(self) -> bool:
        return True

    def get_cash(self) -> Decimal:
        return Decimal("0")

    def get_positions(self) -> list[dict[str, Any]]:
        return []

    def preview(self, req: OrderRequest) -> OrderResult:
        return OrderResult(None, OrderStatus.SUBMITTED, message="模拟盘预检通过（未真实报单）")

    def submit(self, req: OrderRequest) -> OrderResult:
        return OrderResult(f"paper-{secrets.token_hex(4)}", OrderStatus.SUBMITTED, message="已交给模拟盘撮合")

    def poll_orders(self) -> list[dict[str, Any]]:
        return []


# ---------------------------------------------------------------------------
# 实盘：QMT / miniQMT
# ---------------------------------------------------------------------------


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
        return {
            "name": self.name,
            "available": not problems,
            "supports_trading": True,
            "problems": problems,
            "note": "券商官方通道；需开通 miniQMT 权限" if not problems else "；".join(problems),
        }

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


# ---------------------------------------------------------------------------
# 实盘：easytrader（GUI 自动化）
# ---------------------------------------------------------------------------


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
        return {
            "name": self.name,
            "available": not problems,
            "supports_trading": True,
            "problems": problems,
            "note": "GUI 自动化，客户端升级易失效；建议锁定客户端版本"
            if not problems
            else "；".join(problems),
        }

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


# ---------------------------------------------------------------------------
# 注册表 + 护栏
# ---------------------------------------------------------------------------

# 真实 SDK 适配器懒导入：SDK 缺失不影响应用启动，probe() 会精确返回缺项。
try:
    from .broker_live import FutuBroker, IBKRBroker, LongPortBroker, TigerBroker
except Exception:  # noqa: BLE001 — 可选 SDK/平台缺失时保留基础适配器
    FutuBroker = LongPortBroker = TigerBroker = IBKRBroker = None  # type: ignore[assignment]

_ADAPTERS: dict[str, type] = {
    "null": NullBroker,
    "paper": PaperBroker,
    "xtquant": XtQuantBroker,
    "easytrader": EasytraderBroker,
}
if FutuBroker is not None:
    _ADAPTERS.update({
        "futu": FutuBroker,
        "longport": LongPortBroker,
        "tiger": TigerBroker,
        "ibkr": IBKRBroker,
    })

# 白名单：只允许这些名字，防止动态传入任意类名
ALLOWED_BROKERS = tuple(_ADAPTERS)

DEFAULT_GUARDRAILS = {
    "trading_enabled": False,
    "dry_run": True,
    "broker": "null",
    "max_order_amount": 10_000.0,
    "max_daily_amount": 50_000.0,
    "max_position_ratio": 0.3,
    "confirmation_ttl_seconds": 300,
}


def list_adapters() -> list[dict[str, Any]]:
    """列出所有适配器及其本机可用性（不连接，只探测）。"""
    out = []
    for name, cls in _ADAPTERS.items():
        try:
            info = cls().probe()
        except Exception as exc:  # noqa: BLE001 — 探测失败也要列出
            info = {"name": name, "available": False, "supports_trading": False, "problems": [str(exc)]}
        info["id"] = name
        out.append(info)
    return out


def build_adapter(name: str, credentials: dict[str, Any] | None = None) -> BrokerAdapter:
    if name not in _ADAPTERS:
        raise ValueError(f"未知券商适配器：{name}（可选：{', '.join(ALLOWED_BROKERS)}）")
    cls = _ADAPTERS[name]
    try:
        return cls(credentials)  # type: ignore[call-arg]
    except TypeError:
        # 兼容 v4.6 基础适配器无参构造；真实通道接收解密后的凭据 dict
        return cls()



@dataclass
class Confirmation:
    token: str
    expires_at: float
    request: OrderRequest


_tokens: dict[str, Confirmation] = {}


def issue_confirmation(req: OrderRequest, ttl_seconds: int = 300) -> Confirmation:
    """签发二次确认 token（绑定标的/方向/价格/数量）。"""
    token = secrets.token_urlsafe(18)
    conf = Confirmation(token=token, expires_at=time.time() + ttl_seconds, request=req)
    _tokens[token] = conf
    # 清理过期
    now = time.time()
    for key in [k for k, v in _tokens.items() if v.expires_at < now]:
        _tokens.pop(key, None)
    return conf


def consume_confirmation(token: str, req: OrderRequest) -> str | None:
    """校验并消费 token；返回错误文案或 None。"""
    conf = _tokens.pop(token or "", None)
    if conf is None:
        return "确认令牌无效或已被使用"
    if conf.expires_at < time.time():
        return "确认令牌已过期，请重新确认"
    a, b = conf.request, req
    if (
        a.symbol != b.symbol
        or a.side != b.side
        or a.quantity != b.quantity
        or a.limit_price != b.limit_price
    ):
        return "确认令牌与委托内容不一致"
    return None


def guarded_submit(
    *,
    adapter: BrokerAdapter,
    req: OrderRequest,
    guardrails: dict[str, Any],
    confirmation_token: str = "",
    daily_used_amount: float = 0.0,
    portfolio_value: float = 0.0,
    position_value: float = 0.0,
) -> dict[str, Any]:
    """唯一允许报单的入口：先过全部护栏，再调 adapter.submit()。

    返回 {ok, stage, message, result}；stage 标明在哪一步被拦下，便于前端解释。
    """
    g = {**DEFAULT_GUARDRAILS, **(guardrails or {})}

    if not g.get("trading_enabled"):
        return {"ok": False, "stage": "switch", "message": "交易总开关未开启（trading_enabled=false）", "result": None}
    if g.get("broker") not in ALLOWED_BROKERS:
        return {"ok": False, "stage": "whitelist", "message": f"适配器不在白名单：{g.get('broker')}", "result": None}
    if adapter.name != g.get("broker"):
        return {
            "ok": False,
            "stage": "whitelist",
            "message": f"适配器 {adapter.name} 与配置 {g.get('broker')} 不一致",
            "result": None,
        }

    amount = float(req.limit_price) * req.quantity
    if amount > float(g["max_order_amount"]):
        return {
            "ok": False,
            "stage": "max_order",
            "message": f"单笔金额 {amount:,.2f} 超过上限 {g['max_order_amount']:,.2f}",
            "result": None,
        }
    if daily_used_amount + amount > float(g["max_daily_amount"]):
        return {
            "ok": False,
            "stage": "max_daily",
            "message": f"当日累计 {daily_used_amount + amount:,.2f} 超过上限 {g['max_daily_amount']:,.2f}",
            "result": None,
        }
    if portfolio_value > 0 and req.side == OrderSide.BUY:
        after = (position_value + amount) / portfolio_value
        if after > float(g["max_position_ratio"]):
            return {
                "ok": False,
                "stage": "position_ratio",
                "message": f"买入后该标的占比 {after:.1%} 超过上限 {g['max_position_ratio']:.0%}",
                "result": None,
            }

    if not g.get("dry_run"):
        err = consume_confirmation(confirmation_token, req)
        if err:
            return {"ok": False, "stage": "confirmation", "message": err, "result": None}

    if g.get("dry_run"):
        result = adapter.preview(req)
        return {
            "ok": True,
            "stage": "dry_run",
            "message": "dry-run：未真实报单（trading.dry_run=true）",
            "result": result.to_dict(),
        }

    result = adapter.submit(req)
    return {
        "ok": result.status != OrderStatus.REJECTED,
        "stage": "submitted",
        "message": result.message,
        "result": result.to_dict(),
    }


def default_guardrails() -> dict[str, Any]:
    """从环境变量读取护栏配置（未设置时全用安全默认值）。"""
    def _bool(name: str, default: bool) -> bool:
        raw = os.getenv(name, "").strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
        return default

    def _float(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, "").strip() or default)
        except ValueError:
            return default

    return {
        "trading_enabled": _bool("MONEYHELPER_TRADING_ENABLED", False),
        "dry_run": _bool("MONEYHELPER_TRADING_DRY_RUN", True),
        "broker": os.getenv("MONEYHELPER_TRADING_BROKER", "null").strip() or "null",
        "max_order_amount": _float("MONEYHELPER_TRADING_MAX_ORDER", 10_000.0),
        "max_daily_amount": _float("MONEYHELPER_TRADING_MAX_DAILY", 50_000.0),
        "max_position_ratio": _float("MONEYHELPER_TRADING_MAX_RATIO", 0.3),
        "confirmation_ttl_seconds": int(_float("MONEYHELPER_TRADING_TOKEN_TTL", 300)),
    }


def trading_status() -> dict[str, Any]:
    """当前交易状态：开关、dry-run、适配器探测结果。"""
    g = default_guardrails()
    adapters = list_adapters()
    current = next((a for a in adapters if a["id"] == g["broker"]), None)
    return {
        "guardrails": g,
        "adapters": adapters,
        "current": current,
        "note": "默认 NullBroker + dry_run=true：不会产生任何真实委托",
    }


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
