"""可判分题库 · 记账解析与记账方向。

从 eval_bank_questions.py 按分组拆出；题目与 id 原样保留，只做物理分组。
"""

from __future__ import annotations

from .eval_bank_types import Expect, Question

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
)
