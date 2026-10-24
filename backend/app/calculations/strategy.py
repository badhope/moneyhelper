"""再平衡与目标配置：漂移计算、带内容忍、可执行调仓清单。

设计取舍：
- 只输出"买/卖多少金额、约多少股"，不自动下单——A 股 T+1 与最小 100 股整手
  必须由人确认，自动成交会变成真实资金风险。
- 整手取整按标的类型：股票/场内 ETF 100 股一手；场外基金按 1 元。
- 现金作为一个可配置的目标项（symbol=CASH），避免"必须满仓"的隐含假设。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LOT_SIZE_DEFAULT = 100
FUND_KINDS = ("基金", "场外基金", "理财")


@dataclass
class Drift:
    symbol: str
    name: str
    current_pct: float
    target_pct: float
    drift_pct: float
    current_value: float
    target_value: float
    action: str  # buy / sell / hold
    amount: float
    approx_shares: float | None
    price: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "current_pct": self.current_pct,
            "target_pct": self.target_pct,
            "drift_pct": self.drift_pct,
            "current_value": self.current_value,
            "target_value": self.target_value,
            "action": self.action,
            "amount": self.amount,
            "approx_shares": self.approx_shares,
            "price": self.price,
        }


@dataclass
class RebalancePlan:
    total_value: float
    band_pct: float
    needs_rebalance: bool
    max_drift_pct: float
    items: list[Drift] = field(default_factory=list)
    target_sum_pct: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_value": self.total_value,
            "band_pct": self.band_pct,
            "needs_rebalance": self.needs_rebalance,
            "max_drift_pct": self.max_drift_pct,
            "target_sum_pct": self.target_sum_pct,
            "items": [i.to_dict() for i in self.items],
            "notes": list(self.notes),
        }


def _lot(kind: str) -> int:
    return 1 if kind in FUND_KINDS else LOT_SIZE_DEFAULT


def compute_rebalance(
    positions: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    band_pct: float = 5.0,
) -> RebalancePlan:
    """positions: [{symbol,name,kind,shares,last}]; targets: [{symbol,name,target_pct}]。

    权重分母 = 全部持仓市值（含现金）。目标合计不足 100% 时，剩余部分视为现金目标。
    """
    values: dict[str, dict[str, Any]] = {}
    for p in positions:
        sym = str(p.get("symbol") or "").strip()
        if not sym:
            continue
        shares = float(p.get("shares", 0) or 0)
        price = float(p.get("last", 0) or 0)
        mv = shares * price
        values[sym] = {
            "symbol": sym,
            "name": str(p.get("name") or sym),
            "kind": str(p.get("kind") or ""),
            "value": mv,
            "price": price,
        }
    total = sum(v["value"] for v in values.values())
    plan = RebalancePlan(total_value=round(total, 2), band_pct=round(band_pct, 2), needs_rebalance=False, max_drift_pct=0.0)

    cleaned = []
    for t in targets:
        sym = str(t.get("symbol") or "").strip()
        pct = float(t.get("target_pct", 0) or 0)
        if not sym or pct <= 0:
            continue
        cleaned.append({"symbol": sym, "name": str(t.get("name") or sym), "target_pct": pct})
    if not cleaned:
        plan.notes.append("尚未设置目标配置，无法计算再平衡")
        return plan
    if total <= 0:
        plan.notes.append("当前没有持仓市值，无法计算再平衡")
        return plan

    plan.target_sum_pct = round(sum(c["target_pct"] for c in cleaned), 2)
    if abs(plan.target_sum_pct - 100.0) > 0.01:
        plan.notes.append(f"目标配置合计 {plan.target_sum_pct:.2f}%（建议调整为 100%）")

    by_symbol = {c["symbol"]: c for c in cleaned}
    # 未列入目标的现有持仓：按当前权重视为"保持"，并提示
    for sym, v in values.items():
        if sym not in by_symbol:
            plan.notes.append(f"「{v['name']}」未设置目标配置，按当前权重保留")

    max_drift = 0.0
    for c in cleaned:
        v = values.get(c["symbol"])
        current_value = v["value"] if v else 0.0
        price = v["price"] if v else 0.0
        name = v["name"] if v else c["name"]
        kind = v["kind"] if v else ""
        current_pct = current_value / total * 100 if total else 0.0
        target_value = total * c["target_pct"] / 100.0
        diff = target_value - current_value
        drift = current_pct - c["target_pct"]
        max_drift = max(max_drift, abs(drift))
        action = "hold"
        amount = abs(diff)
        # 带内不动：避免为 0.3% 的漂移反复交易、白付手续费
        if abs(drift) > band_pct and abs(diff) >= 1.0:
            action = "buy" if diff > 0 else "sell"
        else:
            amount = 0.0
        approx = None
        if action != "hold" and kind and kind != "现金" and price > 0:
            lot = _lot(kind)
            if action == "sell":
                # A 股卖出可以卖零股（不足一手也能卖），因此只按整数股向下取整；
                # 买入必须是整手（100 股），不足一手时保留金额但标注无法整手买入。
                approx = int(amount // price)
                if approx <= 0:
                    action = "hold"
                    amount = 0.0
                    approx = None
            else:
                approx = int(amount // price // lot * lot) if lot > 1 else round(amount / price, 2)
                if approx <= 0:
                    action = "hold"
                    amount = 0.0
                    approx = None
                    plan.notes.append(f"「{name}」目标缺口不足 1 手，本次不买入")
        plan.items.append(
            Drift(
                symbol=c["symbol"],
                name=name,
                current_pct=round(current_pct, 2),
                target_pct=round(c["target_pct"], 2),
                drift_pct=round(drift, 2),
                current_value=round(current_value, 2),
                target_value=round(target_value, 2),
                action=action,
                amount=round(amount, 2),
                approx_shares=approx,
                price=round(price, 4) if price else None,
            )
        )

    plan.items.sort(key=lambda i: -abs(i.drift_pct))
    plan.max_drift_pct = round(max_drift, 2)
    plan.needs_rebalance = any(i.action != "hold" for i in plan.items)
    buy_total = sum(i.amount for i in plan.items if i.action == "buy")
    sell_total = sum(i.amount for i in plan.items if i.action == "sell")
    if plan.needs_rebalance:
        plan.notes.append(f"计划买入 {buy_total:,.2f} 元、卖出 {sell_total:,.2f} 元（差额为现金缓冲/取整）")
    else:
        plan.notes.append(f"全部持仓在 ±{band_pct:.0f}% 容忍带内，无需调仓")
    return plan


def compute_fire(
    monthly_expense: float,
    monthly_income: float,
    savings_rate_pct: float | None,
    current_net_worth: float,
    expected_return_pct: float = 5.0,
    withdrawal_rate_pct: float = 4.0,
) -> dict[str, Any]:
    """FIRE 数字：目标本金 = 年支出 / 提取率；按复利估算达成年限。"""
    annual_expense = max(0.0, monthly_expense * 12)
    wr = max(0.1, withdrawal_rate_pct) / 100.0
    target = annual_expense / wr if wr > 0 else 0.0
    if savings_rate_pct is not None:
        sr = max(-100.0, min(100.0, savings_rate_pct)) / 100.0
    elif monthly_income > 0:
        sr = max(0.0, (monthly_income - monthly_expense) / monthly_income)
    else:
        sr = 0.0
    annual_saving = max(0.0, monthly_income * 12 * sr)
    r = expected_return_pct / 100.0
    years: float | None = None
    reachable = True
    if target <= 0 or current_net_worth >= target:
        years = 0.0
    elif annual_saving > 0:
        # 每年年初投入、按 r 复利：FV = PV(1+r)^n + PMT * ((1+r)^n - 1)/r
        # 用二分求 n。先判断"到底能不能到"：净值 ≤ 0 且收益率 ≤ 0 时，
        # 复利只会让缺口越滚越大，二分上界会返回一个假的"100 年"。
        if current_net_worth <= 0 and r <= 0:
            reachable = False
        else:
            # 上界要足够大但可判定：用 200 年做硬上限，超过即视为不可达
            lo, hi = 0.0, 200.0
            converged = False
            for _ in range(120):
                mid = (lo + hi) / 2.0
                if abs(r) < 1e-9:
                    fv = current_net_worth + annual_saving * mid
                else:
                    g = (1.0 + r) ** mid
                    fv = current_net_worth * g + annual_saving * (g - 1.0) / r
                if fv >= target:
                    hi = mid
                    converged = True
                else:
                    lo = mid
            years = round(hi, 1) if converged else None
            if years is None:
                reachable = False
    else:
        reachable = False
    coverage_pct = round(current_net_worth / target * 100, 1) if target > 0 else None
    return {
        "annual_expense": round(annual_expense, 2),
        "target_principal": round(target, 2),
        "current_net_worth": round(current_net_worth, 2),
        "progress_pct": coverage_pct,
        "savings_rate_pct": round(sr * 100, 1),
        "annual_saving": round(annual_saving, 2),
        "expected_return_pct": expected_return_pct,
        "withdrawal_rate_pct": withdrawal_rate_pct,
        "years_to_fire": years,
        "reachable": reachable,
        "fire_age_hint": None if years is None else round(years, 1),
    }
