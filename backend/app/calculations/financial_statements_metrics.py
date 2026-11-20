"""三表 → 单期指标（盈利/偿债/营运/现金流质量），缺数据一律 None。"""

from __future__ import annotations

from typing import Any

GOODWILL_WARN_RATIO = 0.20
OCF_NP_WARN_RATIO = 0.50
DEBT_RATIO_WARN = 0.70
CURRENT_RATIO_WARN = 1.0
GROSS_MARGIN_DROP_PCT = 5.0


def _num(raw: Any) -> float | None:
    """数值解析：None/空/非数字 → None；0 与负数合法。"""
    if raw is None or raw == "" or raw == "-" or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _pct(n: float | None, d: float | None) -> float | None:
    """比率 → 百分比；分母无效返回 None。"""
    if n is None or d is None or d == 0:
        return None
    return round(n / d * 100.0, 2)


def _ratio(n: float | None, d: float | None) -> float | None:
    """倍数比率（如周转率、流动比率）；分母无效返回 None。"""
    if n is None or d is None or d == 0:
        return None
    return round(n / d, 2)


def _yoy(cur: float | None, prev: float | None) -> float | None:
    """同比变化百分比；上一期缺失/为 0 返回 None。"""
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100.0, 2)


def compute_period_metrics(bs: dict[str, Any], is_: dict[str, Any], cf: dict[str, Any]) -> dict[str, Any]:
    """单期 20+ 指标。字段名与前端组件一一对应。"""
    ta = _num(bs.get("total_assets"))
    tl = _num(bs.get("total_liabilities"))
    te = _num(bs.get("total_equity"))
    ca = _num(bs.get("current_assets"))
    cl = _num(bs.get("current_liabilities"))
    cash = _num(bs.get("cash_and_equivalents"))
    inv = _num(bs.get("inventory"))
    ar = _num(bs.get("accounts_receivable"))
    gw = _num(bs.get("goodwill"))

    rev = _num(is_.get("revenue"))
    gp = _num(is_.get("gross_profit"))
    op = _num(is_.get("operating_profit"))
    np = _num(is_.get("net_profit"))
    ebit = _num(is_.get("ebit")) if _num(is_.get("ebit")) is not None else op
    ie = _num(is_.get("interest_expense"))

    ocf = _num(cf.get("operating_cashflow"))
    icf = _num(cf.get("investing_cashflow"))
    fcf = _num(cf.get("financing_cashflow"))

    equity = te if te is not None else (ta - tl if ta is not None and tl is not None else None)

    return {
        # 盈利能力
        "gross_margin_pct": _pct(gp, rev),
        "operating_margin_pct": _pct(op, rev),
        "net_margin_pct": _pct(np, rev),
        "roe_pct": _pct(np, equity),
        "roa_pct": _pct(np, ta),
        # 偿债能力
        "debt_ratio_pct": _pct(tl, ta),
        "current_ratio": _ratio(ca, cl),
        "quick_ratio": _ratio(ca - inv if ca is not None and inv is not None else None, cl),
        "interest_coverage": _ratio(ebit, ie),
        # 营运能力
        "asset_turnover": _ratio(rev, ta),
        "inventory_turnover": _ratio(rev, inv),
        "receivables_turnover": _ratio(rev, ar),
        # 现金流质量
        "ocf_to_np": _ratio(ocf, np),
        "ocf_ratio_pct": _pct(ocf, rev),
        "ocf": ocf,
        "icf": icf,
        "fcf": fcf,
        # 原始值（供趋势图与核对）
        "revenue": rev,
        "net_profit": np,
        "gross_profit": gp,
        "total_assets": ta,
        "total_liabilities": tl,
        "total_equity": equity,
        "inventory": inv,
        "accounts_receivable": ar,
        "goodwill": gw,
        "cash": cash,
    }
