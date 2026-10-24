"""财务能力评测题库（M6.3）：50 道可判分的中文财务问答题。

设计原则（这是本项目"可复核"定位的延伸）：
1. **每题都有确定性判据**：要么是精确数值、要么是明确的规则结论，
   不写"你怎么看"这种没有标准答案的开放题。
2. **判分只看数字和关键词，不调用 LLM**：用 LLM 给 LLM 打分是自欺，
   本项目用一个独立的确定性 judge（见 evaluate_model）。
3. **题目覆盖真实使用场景**：记账解析、预算、负债、持仓、风险、策略、
   日期/单位换算，而不是抽象的金融名词解释。

题目结构：
- id:      稳定编号（排行榜可跨版本对比）
- category: bookkeeping / budget / debt / portfolio / strategy / parsing / reasoning
- prompt:  给模型的原始问题（含必要数据，避免依赖运行时库）
- expect:  判据（kind=number / contains / one_of / all_of）
- weight:  分值（难题权重高）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ExpectKind = Literal["number", "contains", "one_of", "all_of", "none_of"]


@dataclass
class Expect:
    kind: ExpectKind
    value: Any
    tolerance: float = 0.0
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "value": self.value, "tolerance": self.tolerance, "hint": self.hint}


@dataclass
class Question:
    id: str
    category: str
    prompt: str
    expect: Expect
    weight: int = 1
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "prompt": self.prompt,
            "expect": self.expect.to_dict(),
            "weight": self.weight,
            "tags": list(self.tags),
        }


QUESTIONS: tuple[Question, ...] = (
    # ------------------------------------------------------------------
    # 记账解析（parsing）：金额、单位、方向、分类
    # ------------------------------------------------------------------
    Question(
        "P01",
        "parsing",
        "把这句话解析成记账条目：『昨天打车 32 元』。请给出日期、金额、分类。",
        Expect("all_of", ["32", "交通"]),
        2,
        ["单位", "分类"],
    ),
    Question(
        "P02",
        "parsing",
        "『咖啡 28 打车 32』一句话里记了几笔？金额分别是多少？",
        Expect("all_of", ["2", "28", "32"]),
        2,
        ["多笔"],
    ),
    Question(
        "P03",
        "parsing",
        "『工资 1w 到账』应记收入多少元？",
        Expect("number", 10000, 0.01),
        1,
        ["万"],
    ),
    Question(
        "P04",
        "parsing",
        "『房租 5k』是多少元？",
        Expect("number", 5000, 0.01),
        1,
        ["k"],
    ),
    Question(
        "P05",
        "parsing",
        "『午饭 30，打车 25，买书 68』合计支出多少元？",
        Expect("number", 123, 0.01),
        2,
        ["合计"],
    ),
    Question(
        "P06",
        "parsing",
        "『三千五百块工资』是多少元？",
        Expect("number", 3500, 0.01),
        1,
        ["中文数字"],
    ),
    Question(
        "P07",
        "parsing",
        "『还信用卡 3200』这笔属于消费支出还是资金转移？说明理由。",
        Expect("contains", "还款"),
        2,
        ["口径"],
    ),
    Question(
        "P08",
        "parsing",
        "『买菜 45.5 元』金额是多少？",
        Expect("number", 45.5, 0.001),
        1,
        ["小数"],
    ),
    # ------------------------------------------------------------------
    # 预算（budget）
    # ------------------------------------------------------------------
    Question(
        "B01",
        "budget",
        "月收入 20000 元，月支出 15000 元，储蓄率是多少？只给百分数。",
        Expect("number", 25, 0.1),
        1,
        ["储蓄率"],
    ),
    Question(
        "B02",
        "budget",
        "月预算 8000 元，已花 6800 元，剩余百分比是多少？",
        Expect("number", 15, 0.1),
        1,
        ["预算"],
    ),
    Question(
        "B03",
        "budget",
        "月预算 6000，已花 7200，超支金额与超支比例分别是多少？",
        Expect("all_of", ["1200", "20"]),
        2,
        ["超支"],
    ),
    Question(
        "B04",
        "budget",
        "月收入 15000，固定支出（房租 4000 + 债务月供 2000 + 订阅 300），每月最多能存多少？",
        Expect("number", 8700, 0.01),
        1,
        ["结余"],
    ),
    Question(
        "B05",
        "budget",
        "预算 10000，已花 4000，本月还剩 20 天，剩余预算的日均可用额度是多少元？",
        Expect("number", 300, 0.01),
        2,
        ["日均"],
    ),
    Question(
        "B06",
        "budget",
        "储蓄率目标 20%，月收入 18000，需要每月至少存多少元？",
        Expect("number", 3600, 0.01),
        1,
        ["目标"],
    ),
    Question(
        "B07",
        "budget",
        "月支出 12000，应急金目标 6 个月，应急金总额应该是多少？",
        Expect("number", 72000, 0.01),
        1,
        ["应急金"],
    ),
    Question(
        "B08",
        "budget",
        "应急金 90000，月必要支出 12000，能覆盖几个月？",
        Expect("number", 7.5, 0.05),
        1,
        ["应急金"],
    ),
    # ------------------------------------------------------------------
    # 负债（debt）
    # ------------------------------------------------------------------
    Question(
        "D01",
        "debt",
        "月收入 20000，月供合计 7000，负债收入比是多少百分比？",
        Expect("number", 35, 0.1),
        1,
        ["DTI"],
    ),
    Question(
        "D02",
        "debt",
        "DTI 超过多少通常被视为偏高？只给数字。",
        Expect("number", 40, 0.1),
        1,
        ["阈值"],
    ),
    Question(
        "D03",
        "debt",
        "信用卡分期年化 13%，房贷 3.45%，优先还哪个？给出利率差。",
        Expect("all_of", ["信用卡", "9.55"]),
        2,
        ["优先级"],
    ),
    Question(
        "D04",
        "debt",
        "贷款余额 120000，年利率 6%，一年利息是多少元（单利）？",
        Expect("number", 7200, 0.01),
        1,
        ["利息"],
    ),
    Question(
        "D05",
        "debt",
        "月供 3000，剩余 24 期，总还款额是多少元？",
        Expect("number", 72000, 0.01),
        1,
        ["总还款"],
    ),
    Question(
        "D06",
        "debt",
        "高息负债的年化利率阈值通常取多少？只给百分数。",
        Expect("number", 8, 0.1),
        1,
        ["阈值"],
    ),
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


def get_questions(category: str = "") -> list[dict[str, Any]]:
    """返回题库（可按分类过滤）。"""
    items = QUESTIONS if not category else tuple(q for q in QUESTIONS if q.category == category)
    return [q.to_dict() for q in items]


def question_count() -> int:
    return len(QUESTIONS)
