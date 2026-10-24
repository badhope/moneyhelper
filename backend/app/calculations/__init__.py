"""确定性金融计算引擎：所有数值计算纯代码执行，LLM 只做叙述解读。

本包提供：
- net_worth:      净值追踪（持仓市值 + 现金 - 负债 = 净值）
- returns:        收益率计算（XIRR / TWR / 简单收益率）
- health:         财务健康评分（五维 0-100 分）
- goals:          目标进度确定性计算
- portfolio_risk: 风险指标（波动率/夏普/索提诺/最大回撤/Calmar/Beta/Alpha/VaR）
- strategy:       再平衡（目标配置 + 容忍带 + 调仓清单）与 FIRE 计算
- valuation:      估值位置分位与定投计划回测

设计原则：
1. 所有函数均为纯函数（无副作用、无 I/O、无全局状态），可直接单测。
2. 仅依赖 Python 标准库（datetime, dataclasses, math），不引入 numpy/scipy。
3. 金额统一 round(..., 2)，日期使用 datetime.date。
4. 数值稳定性检查前置，异常输入立即 raise ValueError。
5. 与 analysis.py / evaluate.py 常量保持一致（CONCENTRATION_MAX_PCT, DTI_WARN_PCT 等）。
6. 指标口径写进 docstring：宁可标注"数据不足"，也不返回看起来合理的假数值。

参考：FinRobot 设计哲学 — "所有数值计算必须纯代码确定性执行，LLM 只做叙述解读"。
"""

from .goals import GoalProgress, calculate_goal_progress
from .health import FinancialHealthScore, calculate_health_score
from .net_worth import NetWorthSnapshot, calculate_net_worth
from .portfolio_risk import (
    RiskMetrics,
    annualized_return,
    annualized_volatility,
    beta_alpha,
    build_equity_curve,
    compute_risk_metrics,
    daily_returns,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
)
from .returns import calculate_simple_return, calculate_twr, calculate_xirr
from .strategy import RebalancePlan, compute_fire, compute_rebalance
from .valuation import (
    Valuation,
    compute_dca_stats,
    compute_valuation,
    next_run_date,
)

__all__ = [
    "FinancialHealthScore",
    "GoalProgress",
    "NetWorthSnapshot",
    "RebalancePlan",
    "RiskMetrics",
    "Valuation",
    "annualized_return",
    "annualized_volatility",
    "beta_alpha",
    "build_equity_curve",
    "calculate_goal_progress",
    "calculate_health_score",
    "calculate_net_worth",
    "calculate_simple_return",
    "calculate_twr",
    "calculate_xirr",
    "compute_dca_stats",
    "compute_fire",
    "compute_rebalance",
    "compute_risk_metrics",
    "compute_valuation",
    "daily_returns",
    "max_drawdown",
    "next_run_date",
    "sharpe_ratio",
    "sortino_ratio",
]
