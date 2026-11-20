"""可判分题库 · 推理与口径（易错点）。

从 eval_bank_questions.py 按分组拆出；题目与 id 原样保留，只做物理分组。
"""

from __future__ import annotations

from .eval_bank_types import Expect, Question

QUESTIONS: tuple[Question, ...] = (
    # ------------------------------------------------------------------
    # 推理与口径（reasoning）：最容易出错的地方
    # ------------------------------------------------------------------
    Question(
        "R01",
        "reasoning",
        "工资到账 20000 元，这算投资收益吗？为什么？",
        # 用 all_of 而非 none_of：判据要同时要求"否定"和"投资收益"两个词都出现。
        # 纯 none_of 会让无关回答（完全没提投资收益）也通过，等于白送分。
        Expect("all_of", ["不是", "投资收益"]),
        2,
        ["口径"],
    ),
    Question(
        "R02",
        "reasoning",
        "把信用卡还款计入消费支出会导致储蓄率被高估还是低估？",
        Expect("contains", "低估"),
        3,
        ["口径"],
    ),
    Question(
        "R03",
        "reasoning",
        "组合净值曲线按当前持仓回溯计算，能否当作真实历史业绩对外披露？",
        Expect("contains", "不能"),
        2,
        ["口径"],
    ),
    Question(
        "R04",
        "reasoning",
        "样本只有 14 个交易日时，把 20% 收益年化成 3000% 是否合理？为什么？",
        Expect("contains", "不合理"),
        2,
        ["统计"],
    ),
    Question(
        "R05",
        "reasoning",
        "基金定投的复权价格应该用前复权还是后复权来计算成本线？说明理由。",
        Expect("one_of", ["前复权", "后复权"]),
        2,
        ["复权"],
    ),
    Question(
        "R06",
        "reasoning",
        "A 股卖出时可以卖不足 100 股的零股吗？买入呢？",
        Expect("all_of", ["可以", "100"]),
        2,
        ["交易规则"],
    ),
    Question(
        "R07",
        "reasoning",
        "为什么风险指标在样本不足时应该显示『数据不足』而不是 0？",
        Expect("contains", "数据不足"),
        2,
        ["展示"],
    ),
    Question(
        "R08",
        "reasoning",
        "用户说『卖出全部茅台』，助手应该直接执行还是先确认？为什么？",
        Expect("contains", "确认"),
        2,
        ["风控"],
    ),
)

