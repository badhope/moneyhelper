"""可判分题库 · 持仓收益与策略。

从 eval_bank_questions.py 按分组拆出；题目与 id 原样保留，只做物理分组。
"""

from __future__ import annotations

from .eval_bank_types import Expect, Question

QUESTIONS: tuple[Question, ...] = (
    # ------------------------------------------------------------------
    # 持仓与收益（portfolio）
    # ------------------------------------------------------------------
    Question(
        "F01",
        "portfolio",
        "买入 100 股，成本 1680 元/股，现价 1521 元/股，浮动盈亏是多少元？",
        Expect("number", -15900, 0.01),
        2,
        ["盈亏"],
    ),
    Question(
        "F02",
        "portfolio",
        "上题（成本 1680、现价 1521）的收益率是多少百分比？",
        Expect("number", -9.4643, 0.05),
        2,
        ["收益率"],
    ),
    Question(
        "F03",
        "portfolio",
        "持仓 3 只，市值分别 50 万、30 万、20 万，第一大持仓占比是多少百分比？",
        Expect("number", 50, 0.1),
        1,
        ["集中度"],
    ),
    Question(
        "F04",
        "portfolio",
        "组合总市值 100 万，其中现金 20 万，非现金仓位比例是多少百分比？",
        Expect("number", 80, 0.1),
        1,
        ["仓位"],
    ),
    Question(
        "F05",
        "portfolio",
        "单只标的占组合 45%，集中度预警阈值 40%，超出多少个百分点？",
        Expect("number", 5, 0.1),
        1,
        ["集中度"],
    ),
    Question(
        "F06",
        "portfolio",
        "成本 10000，当前市值 12000，持有 2 年，年化收益率约多少百分比？（复利）",
        Expect("number", 9.54, 0.2),
        3,
        ["复利"],
    ),
    Question(
        "F07",
        "portfolio",
        "100 股买入价 10 元，卖出价 12 元，忽略费用，盈利多少元？",
        Expect("number", 200, 0.01),
        1,
        ["盈亏"],
    ),
    Question(
        "F08",
        "portfolio",
        "持仓 4 只，权重 50%/25%/15%/10%，前两大合计权重是多少百分比？",
        Expect("number", 75, 0.1),
        1,
        ["集中度"],
    ),
    # ------------------------------------------------------------------
    # 策略（strategy）：风险指标、再平衡、定投、FIRE
    # ------------------------------------------------------------------
    Question(
        "S01",
        "strategy",
        "组合年化收益 8%，年化波动 16%，无风险利率 2%，夏普比率是多少？",
        Expect("number", 0.375, 0.01),
        3,
        ["夏普"],
    ),
    Question(
        "S02",
        "strategy",
        "净值从 1.20 跌到 0.90，最大回撤是多少百分比？",
        Expect("number", -25, 0.1),
        2,
        ["回撤"],
    ),
    Question(
        "S03",
        "strategy",
        "目标配置 60/40，当前 75/25，总市值 100 万，需要卖出多少元 A 资产？",
        Expect("number", 150000, 0.01),
        3,
        ["再平衡"],
    ),
    Question(
        "S04",
        "strategy",
        "每月定投 3000，坚持 24 个月，累计投入多少元？",
        Expect("number", 72000, 0.01),
        1,
        ["定投"],
    ),
    Question(
        "S05",
        "strategy",
        "年支出 12 万，按 4% 提取率，FIRE 目标本金是多少元？",
        Expect("number", 3000000, 0.01),
        2,
        ["FIRE"],
    ),
    Question(
        "S06",
        "strategy",
        "FIRE 目标 300 万，当前净值 90 万，完成度是多少百分比？",
        Expect("number", 30, 0.1),
        1,
        ["FIRE"],
    ),
    Question(
        "S07",
        "strategy",
        "日收益标准差 1%，按 252 个交易日年化，波动率约多少百分比？",
        Expect("number", 15.87, 0.3),
        3,
        ["年化"],
    ),
    Question(
        "S08",
        "strategy",
        "组合 Beta 1.2，基准上涨 10%，无风险利率忽略，组合预期涨幅约多少百分比？",
        Expect("number", 12, 0.2),
        2,
        ["Beta"],
    ),
    Question(
        "S09",
        "strategy",
        "当前价 80，近一年区间 50~100，价格位置分位是多少百分比？",
        Expect("number", 60, 0.2),
        2,
        ["估值分位"],
    ),
    Question(
        "S10",
        "strategy",
        "价格位置分位 15%，属于低位区、中枢还是高位区？",
        Expect("contains", "低位"),
        1,
        ["分区"],
    ),
    Question(
        "S11",
        "strategy",
        "组合年化收益 12%，最大回撤 -20%，Calmar 比率是多少？",
        Expect("number", 0.6, 0.01),
        2,
        ["Calmar"],
    ),
    Question(
        "S12",
        "strategy",
        "单日 95% VaR 为 -2.5%，含义是什么？用一句话说明。",
        Expect("all_of", ["95", "2.5"]),
        2,
        ["VaR"],
    ),
)
