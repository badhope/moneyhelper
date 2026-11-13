"""收益率计算模块：XIRR（内部收益率）、TWR（时间加权收益率）、简单收益率。

纯确定性实现，所有现金流的"正负号"规则：
- 投入（买入、转入）= 负值（资金流出）
- 赎回（卖出、转出）= 正值（资金流入）
- XIRR 要求至少一次流入和一次流出

参考：
- XIRR: https://en.wikipedia.org/wiki/Internal_rate_of_return
- TWR:  GIPS (Global Investment Performance Standards)
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from pyxirr import xirr as _pyxirr_xirr


def calculate_xirr(cashflows: list[tuple[date, float]]) -> float:
    """计算 XIRR（不规则现金流内部收益率）。

    Args:
        cashflows: [(日期, 金额), ...]
            投入为负、赎回为正（与 Excel XIRR 约定一致）

    Returns:
        年化内部收益率（小数形式，如 0.08 = 8%）

    Raises:
        ValueError: 现金流少于 2 条 / 全部同号 / 非法输入 / 无解

    Algorithm:
        使用 pyxirr（Rust 实现，维护活跃）求解
        sum(cf_i / (1+r)^((d_i - d_0)/365)) = 0。
        多根、不收敛与极端值由库处理；本函数只保留输入校验与 ValueError 契约。
    """
    if len(cashflows) < 2:
        raise ValueError("XIRR 计算至少需要 2 条现金流")

    # 类型校验（在排序之前，避免 sort 本身 TypeError）
    for d, _cf in cashflows:
        if not isinstance(d, date):
            raise ValueError(f"现金流日期必须为 datetime.date 类型，got {type(d).__name__}")

    cfs = sorted(cashflows, key=lambda x: x[0])

    # 必须同时存在流入和流出
    has_positive = any(cf > 0 for _, cf in cfs)
    has_negative = any(cf < 0 for _, cf in cfs)
    if not (has_positive and has_negative):
        raise ValueError("XIRR 计算要求现金流同时包含流入（正）和流出（负），全部同号无解")

    try:
        result = _pyxirr_xirr(
            [d for d, _cf in cfs],
            [cf for _d, cf in cfs],
            guess=0.1,
        )
    except Exception as exc:  # noqa: BLE001 — 统一转换为本模块的 ValueError 契约
        raise ValueError(f"XIRR 迭代未收敛，请检查现金流是否合理：{exc}") from exc

    if result is None or not math.isfinite(result):
        raise ValueError("XIRR 迭代未收敛，请检查现金流是否合理")
    return round(float(result), 6)


def calculate_twr(transactions: list[dict[str, Any]]) -> float:
    """计算时间加权收益率（Time-Weighted Return）。

    在每个外部现金流（存入/提取）发生时切分子期间，子期间收益率几何连乘。
    TWR 消除了现金流时机的影响，适合评价投资本身的表现。

    Args:
        transactions: 按时间排序的交易列表，每条需含：
            - "date": date 或 str (YYYY-MM-DD)
            - "type":  "deposit" / "withdraw" / "valuation"
            - "amount": float（deposit/withdraw 为现金流金额，valuation 为期末市值）

    Returns:
        时间加权收益率（小数形式，如 0.12 = 12%）

    Raises:
        ValueError: 交易列表少于 2 条 / 无 valuation / 市值为零或负
    """
    if len(transactions) < 2:
        raise ValueError("TWR 计算至少需要 2 条记录")

    # 按日期排序
    sorted_txns = sorted(transactions, key=lambda x: str(x.get("date", "")))

    # 找到所有 valuation 点
    valuations = [t for t in sorted_txns if t.get("type") == "valuation"]
    if len(valuations) < 2:
        raise ValueError("TWR 计算至少需要 2 个估值点（type=valuation）")

    # 构建子期间：在相邻 valuation 之间，记录期间内的净现金流（deposit/withdraw）
    sub_period_returns: list[float] = []

    for i in range(1, len(valuations)):
        prev_val = float(valuations[i - 1].get("amount", 0))
        curr_val = float(valuations[i].get("amount", 0))
        prev_date = _to_date(valuations[i - 1].get("date"))
        curr_date = _to_date(valuations[i].get("date"))

        if prev_val <= 0:
            raise ValueError(f"估值金额必须为正，期间 {prev_date} 金额为 {prev_val}")

        # 期间内的外部现金流（deposit 为正 = 投入，withdraw 为负 = 取出）
        net_flow = 0.0
        for t in sorted_txns:
            if t.get("type") in ("deposit", "withdraw"):
                t_date = _to_date(t.get("date"))
                if prev_date <= t_date < curr_date:
                    flow = float(t.get("amount", 0))
                    if t["type"] == "withdraw":
                        flow = -flow
                    net_flow += flow

        # 子期间收益率 = (期末市值 - 期初市值 - 净现金流) / (期初市值 + 净现金流)
        # 简化：假设现金流发生在期末，故 r = V_n / (V_{n-1} + F) - 1
        denominator = prev_val + net_flow
        if denominator <= 0:
            raise ValueError(
                f"期间 {prev_date} -> {curr_date} 分母非正（期初 {prev_val} + 净现金流 {net_flow} = {denominator}），"
                "无法计算 TWR"
            )
        sub_r = curr_val / denominator - 1.0
        sub_period_returns.append(sub_r)

    # 几何连乘
    twr = 1.0
    for r in sub_period_returns:
        twr *= (1.0 + r)
    twr -= 1.0

    return round(twr, 6)


def calculate_simple_return(
    start_value: float,
    end_value: float,
    net_inflows: float = 0.0,
) -> float:
    """计算简单收益率（Money-Weighted / 原始收益）。

    公式：r = (期末价值 - 期初价值 - 净流入) / (期初价值 + 净流入)
    其中净流入为期间内追加投入的金额（正 = 投入，负 = 取出）。
    若 period 内没有现金流：r = (end - start) / start

    Args:
        start_value:  期初价值（必须 > 0）
        end_value:    期末价值
        net_inflows:  期间净投入（正 = 追加投入，负 = 取出），默认 0

    Returns:
        简单收益率（小数形式）

    Raises:
        ValueError: 期初价值非正或分母为零
    """
    if start_value <= 0:
        raise ValueError(f"期初价值必须为正，got {start_value}")

    denominator = start_value + net_inflows
    if denominator <= 0:
        raise ValueError(f"分母为零或负（期初 {start_value} + 净流入 {net_inflows} = {denominator}）")

    r = (end_value - start_value - net_inflows) / denominator
    return round(r, 6)


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def _to_date(val: Any) -> date:
    """把 date 或 YYYY-MM-DD 字符串转为 date。"""
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        parts = val.split("-")
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
    raise ValueError(f"无法解析日期: {val!r}")
