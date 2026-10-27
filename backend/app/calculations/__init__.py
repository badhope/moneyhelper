"""确定性金融计算引擎：所有数值计算纯代码执行，LLM 只做叙述解读。

本包提供：
- net_worth:      净值追踪（持仓市值 + 现金 - 负债 = 净值）
- returns:        收益率计算（XIRR / TWR / 简单收益率）
- health:         财务健康评分（五维 0-100 分）
- goals:          目标进度确定性计算
- portfolio_risk: 风险指标（波动率/夏普/索提诺/最大回撤/Calmar/Beta/Alpha/VaR）
- strategy:       再平衡（目标配置 + 容忍带 + 调仓清单）与 FIRE 计算
- valuation:      估值位置分位与定投计划回测

v4.0 新增（财务工作台垂直深化）：
- technical:        技术指标（MA/MACD/RSI/BOLL/KDJ）与信号合成（股票投研）
- backtest:         策略回测（双均线 / 定投），收益/回撤/夏普/胜率/资金曲线
- financial_statements: 财报分析（三表 → 20+ 指标 / 杜邦 / 同比 / 异常预警）

v4.1 新增：
- forecast:         股票价格统计预测（线性趋势 / 历史波动率 / 蒙特卡洛 GBM 分位区间）

设计原则：
1. 所有函数均为纯函数（无副作用、无 I/O、无全局状态），可直接单测。
2. 仅依赖 Python 标准库（datetime, dataclasses, math, statistics, random），不引入 numpy/scipy。
3. 金额统一 round(..., 2)，日期使用 datetime.date。
4. 数值稳定性检查前置，异常输入立即 raise ValueError。
5. 与 analysis.py / evaluate.py 常量保持一致（CONCENTRATION_MAX_PCT, DTI_WARN_PCT 等）。
6. 指标口径写进 docstring：宁可标注"数据不足"，也不返回看起来合理的假数值。
7. 蒙特卡洛类随机计算固定随机种子（可复现、可审计）。

参考：FinRobot 设计哲学 — "所有数值计算必须纯代码确定性执行，LLM 只做叙述解读"。
"""

from .backtest import backtest_dca, backtest_ma_cross, backtest_text, run_backtest
from .financial_statements import analyze_statements, compute_period_metrics
from .forecast import forecast, forecast_text
from .goals import GoalProgress, calculate_goal_progress
from .health import FinancialHealthScore, calculate_health_score
from .net_worth import NetWorthSnapshot, calculate_net_worth
from .paper import (
    build_equity_curve as build_snapshot_curve,
)
from .paper import (
    estimate,
    fee_for,
    ranking,
    round_lots,
    team_summary,
    validate_trade,
)
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
from .technical import technical_analysis, trend_text
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
    "analyze_statements",
    "annualized_return",
    "annualized_volatility",
    "backtest_dca",
    "backtest_ma_cross",
    "backtest_text",
    "beta_alpha",
    "build_equity_curve",
    "build_snapshot_curve",
    "calculate_goal_progress",
    "calculate_health_score",
    "calculate_net_worth",
    "calculate_simple_return",
    "calculate_twr",
    "calculate_xirr",
    "compute_dca_stats",
    "compute_fire",
    "compute_period_metrics",
    "compute_rebalance",
    "compute_risk_metrics",
    "compute_valuation",
    "daily_returns",
    "estimate",
    "fee_for",
    "forecast",
    "forecast_text",
    "max_drawdown",
    "next_run_date",
    "ranking",
    "round_lots",
    "run_backtest",
    "sharpe_ratio",
    "sortino_ratio",
    "team_summary",
    "technical_analysis",
    "trend_text",
    "validate_trade",
]
