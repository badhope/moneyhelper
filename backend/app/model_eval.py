"""模型评测执行器（M6.3）：跑题库、确定性判分、出排行榜。

关键设计：判分完全确定性，不用 LLM 当裁判。
- number：从回答里抽取最后一个数值，按相对/绝对容差比较
- contains / none_of：子串或数值包含判定（大小写、全半角归一）
- one_of：命中任一即可
- all_of：必须全部命中

这套判据对"胡说但数字对"和"数字对但口径错"都能区分：
比如 R02 只有答出"低估"才算对，答"高估"得 0。
"""

from __future__ import annotations

import re
import time
from typing import Any

from .eval_bank import QUESTIONS, Question, get_questions

# 全角数字/符号 → 半角，避免模型输出「１２００元」判错
_FULLWIDTH = str.maketrans(
    "０１２３４５６７８９．％－＋，", "0123456789.%-+，"
)

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _normalize(text: str) -> str:
    if not text:
        return ""
    t = str(text).translate(_FULLWIDTH)
    t = t.replace(",", "").replace("，", "")
    t = t.replace("％", "%")
    return t


def _extract_numbers(text: str) -> list[float]:
    out: list[float] = []
    for m in _NUM_RE.finditer(_normalize(text)):
        try:
            out.append(float(m.group()))
        except ValueError:
            continue
    return out


def _close(a: float, b: float, tolerance: float) -> bool:
    if tolerance <= 0:
        return abs(a - b) < 1e-9
    # 相对容差（对百分数/大金额更合理），至少 1e-9 避免除零
    return abs(a - b) <= max(abs(b) * tolerance / 100.0, 1e-9)


def judge(question: Question, answer: str) -> tuple[bool, str]:
    """判一道题。返回 (是否通过, 判据说明)。

    数字题取回答里**最能匹配期望值**的那个数，而不是死取第一个：
    模型常写「成本 1680，现价 1521，亏损 15900 元」——第一个数是 1680，
    直接用第一个会误判。取"最接近期望值且在容差内"的数更符合意图。

    负数处理：中文回答常写「亏损 15900」而不带负号。期望为负时，
    绝对值相等也算命中——否则所有"亏损 X 元"的正确回答都会被判错。
    """
    exp = question.expect
    text = _normalize(answer)
    if not text.strip():
        return False, "空回答"

    if exp.kind == "number":
        target = float(exp.value)
        nums = _extract_numbers(text)
        if not nums:
            return False, f"回答里没有数字（期望 {target}）"
        candidates = list(nums)
        # 「亏损 15900 / 下跌 25% / 回撤 25%」这类表述缺负号，补上负号候选项。
        # 但「盈利 15900」不能因此判成 -15900 —— 先看方向词。
        if target < 0:
            loss_words = ("亏损", "亏", "下跌", "跌", "回撤", "减少", "负")
            gain_words = ("盈利", "赚", "上涨", "涨", "增加", "正的")
            has_gain = any(w in text for w in gain_words)
            has_loss = any(w in text for w in loss_words)
            if has_loss or not has_gain:
                candidates += [-n for n in nums]
        hit = any(_close(n, target, exp.tolerance) for n in candidates)
        return hit, f"期望 ≈{target}（容差 {exp.tolerance}%），回答含 {nums[:6]}"

    if exp.kind == "contains":
        needle = _normalize(str(exp.value))
        ok = needle.lower() in text.lower()
        return ok, f"应包含「{needle}」"

    if exp.kind == "none_of":
        # 中文否定句里"不是投资收益"包含"是投资收益"这个子串，纯子串匹配会把
        # 正确答案判错。先剔除"不是X/不算X/并非X/不属于X/不能算X"这类否定结构，
        # 再做禁忌词匹配。
        neg_pairs = (
            ("不是", ""), ("不算", ""), ("并非", ""), ("不属于", ""),
            ("不能算", ""), ("不应该算", ""), ("不能当作", ""),
        )
        cleaned = text
        for neg, _ in neg_pairs:
            cleaned = cleaned.replace(neg, "非")
        bad = [_normalize(str(v)) for v in exp.value]
        hit = [b for b in bad if b.lower() in cleaned.lower()]
        return (not hit), f"不应包含 {bad}（命中 {hit}）" if hit else f"未命中禁忌表述 {bad}"

    if exp.kind == "one_of":
        opts = [_normalize(str(v)) for v in exp.value]
        hit = [o for o in opts if o.lower() in text.lower()]
        return bool(hit), f"应包含任一 {opts}（命中 {hit}）"

    if exp.kind == "all_of":
        parts = []
        missing = []
        for v in exp.value:
            needle = _normalize(str(v))
            # 纯数字项按数值匹配，避免"1200 元"和"1200.00"判不出
            if re.fullmatch(r"-?\d+(?:\.\d+)?", needle):
                target = float(needle)
                ok = any(_close(n, target, 1.0) for n in _extract_numbers(text))
            else:
                ok = needle.lower() in text.lower()
            parts.append((needle, ok))
            if not ok:
                missing.append(needle)
        return (not missing), f"应全部包含 {[p[0] for p in parts]}（缺 {missing}）"

    return False, f"未知判据类型 {exp.kind}"


def score_answers(answers: dict[str, str], category: str = "") -> dict[str, Any]:
    """对一批回答判分。answers: {question_id: answer}。"""
    pool = [q for q in QUESTIONS if not category or q.category == category]
    details = []
    earned = 0
    total = 0
    passed = 0
    by_cat: dict[str, dict[str, int]] = {}
    for q in pool:
        total += q.weight
        ans = answers.get(q.id, "")
        ok, why = judge(q, ans)
        if ok:
            earned += q.weight
            passed += 1
        cat = by_cat.setdefault(q.category, {"passed": 0, "total": 0, "weight_earned": 0, "weight_total": 0})
        cat["total"] += 1
        cat["weight_total"] += q.weight
        if ok:
            cat["passed"] += 1
            cat["weight_earned"] += q.weight
        details.append(
            {
                "id": q.id,
                "category": q.category,
                "weight": q.weight,
                "passed": ok,
                "reason": why,
                "answer_preview": (ans or "")[:200],
            }
        )
    for c in by_cat.values():
        c["accuracy_pct"] = round(c["passed"] / c["total"] * 100, 1) if c["total"] else 0.0
    return {
        "score_pct": round(earned / total * 100, 1) if total else 0.0,
        "weight_earned": earned,
        "weight_total": total,
        "passed": passed,
        "question_count": len(pool),
        "by_category": by_cat,
        "details": details,
        "graded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


async def evaluate_model(
    model: str = "",
    category: str = "",
    *,
    max_questions: int = 0,
) -> dict[str, Any]:
    """用当前配置的模型跑题库。

    - 未配置模型 / 调用失败：返回 scored=false 与明确原因，不伪造分数。
    - max_questions > 0 时只跑前 N 题（调试用，排行榜要求全量）。
    """
    from . import llm

    pool = [q for q in QUESTIONS if not category or q.category == category]
    if max_questions > 0:
        pool = pool[:max_questions]
    if not await llm.llm_available():
        return {
            "scored": False,
            "reason": "尚未配置模型（设置 → AI 回答 里填 Base URL / Model / API Key）",
            "question_count": len(pool),
        }

    answers: dict[str, str] = {}
    failures: list[str] = []
    started = time.time()
    for q in pool:
        try:
            reply = await llm.litellm_chat(
                [
                    {"role": "system", "content": "你是个人财务助手。只回答问题，不要寒暄；数值题只给结论数字或一句结论。"},
                    {"role": "user", "content": q.prompt},
                ],
                model=model or None,
                temperature=0.0,
                timeout=45.0,
            )
            if reply is None:
                failures.append(f"{q.id}: 模型调用返回空")
                answers[q.id] = ""
            else:
                answers[q.id] = reply
        except Exception as exc:  # noqa: BLE001 — 单题失败不应中断整轮评测
            failures.append(f"{q.id}: {type(exc).__name__}: {exc}")
            answers[q.id] = ""
    result = score_answers(answers, category="")
    # 只保留本次实际跑过的题
    ran = {q.id for q in pool}
    result["details"] = [d for d in result["details"] if d["id"] in ran]
    result["scored"] = True
    result["model"] = model or "default"
    result["duration_seconds"] = round(time.time() - started, 1)
    if failures:
        result["failures"] = failures[:10]
    return result


LEADERBOARD_SEED: list[dict[str, Any]] = []


def leaderboard(entries: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """排行榜：按分数降序。没有真实评测数据时返回空列表，绝不塞假条目。"""
    rows = entries if entries is not None else LEADERBOARD_SEED
    return sorted(rows, key=lambda r: (-float(r.get("score_pct", 0)), str(r.get("model", ""))))


__all__ = [
    "QUESTIONS",
    "evaluate_model",
    "get_questions",
    "judge",
    "leaderboard",
    "score_answers",
]
