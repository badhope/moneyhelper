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
import secrets
import time
from dataclasses import dataclass
from typing import Any

from .broker_easytrader import EasytraderBroker
from .broker_paper import NullBroker, PaperBroker
from .broker_types import (
    BrokerAdapter,
    OrderRequest,
    OrderSide,
    OrderStatus,
)
from .broker_xtquant import XtQuantBroker

# ---------------------------------------------------------------------------
# 默认：只读
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# 实盘：QMT / miniQMT
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 实盘：easytrader（GUI 自动化）
# ---------------------------------------------------------------------------




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
    preview_only: bool = False,
) -> dict[str, Any]:
    """唯一允许报单的入口：先过全部护栏，再调 adapter.submit()。

    返回 {ok, stage, message, result}；stage 标明在哪一步被拦下，便于前端解释。

    ``preview_only=True`` 只给"预检取令牌"用：预检本身不下单，但要先生成
    token 交给调用方；若预检也校验 token，dry_run=false 时会出现"要令牌
    才能拿令牌"的死锁。预检只走 adapter.preview()，绝不进 submit()。
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

    if not preview_only and not g.get("dry_run"):
        err = consume_confirmation(confirmation_token, req)
        if err:
            return {"ok": False, "stage": "confirmation", "message": err, "result": None}

    if preview_only or g.get("dry_run"):
        result = adapter.preview(req)
        return {
            "ok": True,
            "stage": "dry_run" if g.get("dry_run") else "preview",
            "message": "dry-run：未真实报单（trading.dry_run=true）"
            if g.get("dry_run")
            else "preview：仅预检，未报单",
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


