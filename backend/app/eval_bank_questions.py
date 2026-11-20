"""50 道可判分题库门面：按 parsing/budget/debt/portfolio/strategy/reasoning 分组。

纯数据；正文按分组拆在 `eval_bank_q_ledger/plan/market/reasoning.py`，
此处按原顺序拼接为单一 `QUESTIONS`，跨版本可比性靠稳定 id。
"""

from __future__ import annotations

from .eval_bank_q_ledger import QUESTIONS as _ledger
from .eval_bank_q_market import QUESTIONS as _market
from .eval_bank_q_plan import QUESTIONS as _plan
from .eval_bank_q_reasoning import QUESTIONS as _reason
from .eval_bank_types import Question

QUESTIONS: tuple[Question, ...] = (*_ledger, *_plan, *_market, *_reason)
