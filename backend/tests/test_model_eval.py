"""评测题库与判分器测试：判据必须"答对得分、答错扣分"，不能一律通过。

这是防自欺的关键测试：判分器如果太宽松，排行榜就没有意义。
每个用例都构造**正确回答**与**错误回答**，断言两者结果相反。
"""

from __future__ import annotations

import pytest
from app.eval_bank import QUESTIONS, get_questions, question_count
from app.model_eval import judge, score_answers


def _q(qid: str):
    return next(q for q in QUESTIONS if q.id == qid)


# --------------------------------------------------------------------------
# 题库本身
# --------------------------------------------------------------------------


def test_question_count_is_50():
    assert question_count() == 50


def test_all_ids_unique():
    ids = [q.id for q in QUESTIONS]
    assert len(ids) == len(set(ids))


def test_every_question_has_prompt_and_expect():
    for q in QUESTIONS:
        assert q.prompt.strip(), q.id
        assert q.expect.kind in {"number", "contains", "one_of", "all_of", "none_of"}, q.id
        assert q.weight >= 1, q.id


def test_categories_cover_expected_domains():
    cats = {q.category for q in QUESTIONS}
    assert {"parsing", "budget", "debt", "portfolio", "strategy", "reasoning"} <= cats


def test_get_questions_filters_category():
    rows = get_questions("strategy")
    assert rows
    assert all(r["category"] == "strategy" for r in rows)
    assert get_questions("nope") == []


# --------------------------------------------------------------------------
# 数字题：正确必须过，错误必须不过
# --------------------------------------------------------------------------


def test_number_exact_match_passes():
    ok, _ = judge(_q("B07"), "应急金应该是 72000 元")
    assert ok is True


def test_number_wrong_value_fails():
    ok, why = judge(_q("B07"), "应急金应该是 60000 元")
    assert ok is False
    assert "72000" in why or "期望" in why


def test_number_negative_answer():
    # F01 盈亏 -15900
    assert judge(_q("F01"), "浮动亏损 15900 元")[0] is True
    assert judge(_q("F01"), "-15900")[0] is True
    assert judge(_q("F01"), "盈利 15900 元")[0] is False


def test_number_extracts_best_match_not_first():
    """关键回归：模型常先复述成本再给答案，取第一个数会误判。"""
    answer = "成本价 1680 元/股，现价 1521 元/股，所以浮动亏损 15900 元"
    assert judge(_q("F01"), answer)[0] is True


def test_number_tolerance_rejects_near_miss():
    # F02 收益率 -9.4643，容差 0.05%（相对）
    assert judge(_q("F02"), "-9.46%")[0] is True
    assert judge(_q("F02"), "-8.00%")[0] is False


def test_number_with_percent_sign():
    assert judge(_q("B01"), "储蓄率 25%")[0] is True


def test_number_fullwidth_digits():
    # 全角数字应被归一化
    assert judge(_q("B07"), "７２０００元")[0] is True


def test_number_thousands_separator():
    assert judge(_q("S03"), "需要卖出 150,000 元")[0] is True


def test_empty_answer_fails():
    for qid in ("B07", "P01", "R02"):
        assert judge(_q(qid), "")[0] is False
        assert judge(_q(qid), "   ")[0] is False


def test_number_no_digits_fails():
    ok, why = judge(_q("B07"), "具体金额取决于你的情况")
    assert ok is False
    assert "数字" in why


# --------------------------------------------------------------------------
# 文本题
# --------------------------------------------------------------------------


def test_contains_passes_and_fails():
    assert judge(_q("R02"), "会低估储蓄率")[0] is True
    assert judge(_q("R02"), "会高估储蓄率")[0] is False


def test_contains_case_insensitive():
    assert judge(_q("R03"), "不能，这只是回溯模拟")[0] is True


def test_all_of_requires_every_part():
    # P02 需要 2 / 28 / 32 全在
    assert judge(_q("P02"), "记了 2 笔，分别 28 元和 32 元")[0] is True
    assert judge(_q("P02"), "记了 2 笔，28 元和 30 元")[0] is False


def test_all_of_numeric_part_uses_tolerance():
    # D03 要「信用卡」+ 9.55
    assert judge(_q("D03"), "优先还信用卡，利率差 9.55 个百分点")[0] is True
    assert judge(_q("D03"), "优先还信用卡，利率差 5 个百分点")[0] is False


def test_none_of_rejects_forbidden_statement():
    # R01 不应出现「算投资收益」
    assert judge(_q("R01"), "工资是劳动收入，不是投资收益")[0] is True
    assert judge(_q("R01"), "这是投资收益")[0] is False


def test_one_of_accepts_any_option():
    assert judge(_q("R05"), "用前复权")[0] is True
    assert judge(_q("R05"), "用后复权")[0] is True
    assert judge(_q("R05"), "不复权")[0] is False


# --------------------------------------------------------------------------
# 聚合判分
# --------------------------------------------------------------------------


def test_score_answers_all_correct():
    answers = {
        "B07": "72000",
        "B08": "7.5",
        "B01": "25%",
        "F01": "-15900",
        "R02": "低估",
    }
    r = score_answers(answers)
    # 只答了 5 题，其余为空 → 分数不应是 100
    assert r["passed"] == 5
    assert r["score_pct"] < 100
    assert r["question_count"] == 50


def test_score_answers_all_wrong():
    answers = {q.id: "完全无关的回答" for q in QUESTIONS}
    r = score_answers(answers)
    assert r["passed"] == 0
    assert r["score_pct"] == 0


def test_score_answers_perfect_run():
    """构造一份满分答卷，验证判分器不会因为判据写错而永远拿不到 100。"""
    perfect = {
        "P01": "昨天，32 元，交通",
        "P02": "2 笔，28 元和 32 元",
        "P03": "10000 元",
        "P04": "5000 元",
        "P05": "123 元",
        "P06": "3500 元",
        "P07": "属于还款，是资金转移不是消费支出",
        "P08": "45.5 元",
        "B01": "25%",
        "B02": "15%",
        "B03": "超支 1200 元，超支比例 20%",
        "B04": "8700 元",
        "B05": "300 元",
        "B06": "3600 元",
        "B07": "72000 元",
        "B08": "7.5 个月",
        "D01": "35%",
        "D02": "40",
        "D03": "优先还信用卡，利率差 9.55 个百分点",
        "D04": "7200 元",
        "D05": "72000 元",
        "D06": "8%",
        "F01": "浮动亏损 15900 元",
        "F02": "-9.46%",
        "F03": "50%",
        "F04": "80%",
        "F05": "超出 5 个百分点",
        "F06": "约 9.54%",
        "F07": "200 元",
        "F08": "75%",
        "S01": "0.375",
        "S02": "-25%",
        "S03": "150000 元",
        "S04": "72000 元",
        "S05": "3000000 元",
        "S06": "30%",
        "S07": "15.87%",
        "S08": "12%",
        "S09": "60%",
        "S10": "低位区",
        "S11": "0.6",
        "S12": "有 95% 的概率单日亏损不超过 2.5%",
        "R01": "不是投资收益，工资是劳动收入",
        "R02": "低估",
        "R03": "不能，这只是按当前持仓回溯的模拟净值",
        "R04": "不合理，14 天样本太短，年化会被极端放大",
        "R05": "用前复权",
        "R06": "卖出可以卖不足 100 股的零股，买入必须 100 股整手",
        "R07": "样本不足时 0 会被误读成真实值，显示数据不足更诚实",
        "R08": "先确认，清仓是不可逆操作",
    }
    r = score_answers(perfect)
    assert r["passed"] == 50, [d for d in r["details"] if not d["passed"]]
    assert r["score_pct"] == pytest.approx(100.0)


def test_score_answers_by_category():
    r = score_answers({"B01": "25%"}, category="budget")
    assert r["question_count"] == 8
    assert r["by_category"]["budget"]["passed"] == 1
    assert r["by_category"]["budget"]["accuracy_pct"] == pytest.approx(12.5)


def test_score_answers_has_details_for_every_question():
    r = score_answers({})
    assert len(r["details"]) == 50
    assert all("reason" in d for d in r["details"])


def test_score_answers_empty_bank_category():
    r = score_answers({}, category="nonexistent")
    assert r["question_count"] == 0
    assert r["score_pct"] == 0
