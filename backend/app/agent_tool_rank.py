"""按问题相关度裁剪工具表（纯函数，无 IO）。

为什么需要：小模型端到端跑不动全量工具面。实测 MiniCPM5-2B 在 40 个工具的
schema（约 7.4k token）下**一个工具都不调**，直接凭上下文编答案；把工具压到
4 个（get_ledger_view / get_trend / get_budget / get_gl_summary）后立刻正确调用。
这不是"模型不会用工具"，而是工具太多导致选择困难 + prompt 过长（prefill 3 分钟）。

因此提供 `LLM_TOOL_LIMIT` 开关：默认 0（不裁剪，行为完全不变），设置后按问题
相关度保留前 N 个。打分只看"问题与工具名/描述的字面重叠"，不引入向量模型——
工具只有几十个，字面重叠已经够用，且结果可解释、可测试。
"""

from __future__ import annotations

import re
from typing import Any

_PUNCT = re.compile(r"[^\w\u4e00-\u9fff]+")


def _bigrams(text: str) -> set[str]:
    """中文按二字切片，英文按整词；都做小写归一。"""
    clean = _PUNCT.sub(" ", text.lower())
    grams: set[str] = set()
    for chunk in clean.split():
        if chunk.isascii():
            if len(chunk) >= 2:
                grams.add(chunk)
            continue
        for i in range(len(chunk) - 1):
            grams.add(chunk[i : i + 2])
    return grams


def _tool_text(schema: dict[str, Any]) -> str:
    fn = schema.get("function") or {}
    return f"{fn.get('name') or ''} {fn.get('description') or ''}"


def rank_tools(
    question: str, schemas: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """按与问题的字面相关度排序，返回前 limit 个（limit<=0 时原样返回）。

    显式点名的工具（问题里出现工具名）一律优先，避免"用户说了工具名却被裁掉"。
    同分保持原有顺序，保证结果稳定、可断言。
    """
    if limit <= 0 or len(schemas) <= limit:
        return list(schemas)
    q_grams = _bigrams(question)
    scored: list[tuple[int, int, int, dict[str, Any]]] = []
    for idx, schema in enumerate(schemas):
        name = str((schema.get("function") or {}).get("name") or "")
        explicit = bool(name) and name.lower() in question.lower()
        overlap = len(q_grams & _bigrams(_tool_text(schema)))
        scored.append((0 if explicit else 1, -overlap, idx, schema))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [item[3] for item in scored[:limit]]
