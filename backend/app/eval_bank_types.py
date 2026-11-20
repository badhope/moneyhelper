"""题库数据契约：判据与题目结构。"""

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
