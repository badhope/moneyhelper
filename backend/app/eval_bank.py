"""财务能力评测题库门面：结构见 eval_bank_types，题目见 eval_bank_questions。

设计原则：每题都有确定性判据（精确数值或明确规则结论），判分只看数字与关键词，
不调用 LLM —— 用 LLM 给 LLM 打分是自欺。
"""

from __future__ import annotations

from typing import Any

from .eval_bank_questions import QUESTIONS  # noqa: F401 — 对外同名导出
from .eval_bank_types import Expect, ExpectKind, Question  # noqa: F401 — 对外同名导出


def get_questions(category: str = "") -> list[dict[str, Any]]:
    """返回题库（可按分类过滤）。"""
    items = QUESTIONS if not category else tuple(q for q in QUESTIONS if q.category == category)
    return [q.to_dict() for q in items]


def question_count() -> int:
    return len(QUESTIONS)
