"""自然语言记账解析门面：词表 / 日期 / 条目 / 入口。

原则：规则先跑（确定性好测），模型只做兜底；拿不到金额一律返回 None，
不编造看似合理的账目。
"""

from __future__ import annotations

__all__ = ["parse", "parse_many", "parse_with_ai"]

from .nlparse_date import _parse_date  # noqa: F401,E402
from .nlparse_entry import parse, parse_many, parse_with_ai  # noqa: F401,E402
from .nlparse_item import (  # noqa: F401,E402
    _MULTI_RE,
    _NOT_ITEM_WORDS,
    QUERY_MARKERS,
    RECORD_VERBS,
    _clean_item,
)
from .nlparse_lexicon import (  # noqa: F401,E402
    _AMOUNT_PLAIN,
    _AMOUNT_PREFIX,
    _AMOUNT_SUFFIX,
    CATEGORY_KEYWORDS,
    INCOME_KEYWORDS,
    NOISE_WORDS,
    _cn_amount,
    _cn_to_float,
    _parse_amount,
    _to_amount,
)
