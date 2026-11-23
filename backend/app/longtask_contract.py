"""长任务阶段契约：最少交付标准与产物校验。

为什么要有：只把模型返回写进文件就标 done，等于把“模型编了点什么”当成完成。
契约把每阶段的最低字数、必需小节、占位符禁令显式化，执行器在落盘前校验；
不合格先重写一次，仍不合格落 failed，并把违反项写进阶段错误。

边界：契约只校验可观测文本，不判断事实真假、不替代人工审稿。
"""

from __future__ import annotations

import re
from typing import Any

MAX_CONTRACT_CHARS = 12000
DEFAULT_MAX_CHARS = 12000
MAX_SECTIONS = 8

_PLACEHOLDER_RE = re.compile(
    r"(TODO|TBD|FIXME|待补充|待完善|待填写|此处省略|内容略|\[待填\])",
    re.IGNORECASE,
)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_contract(raw: Any) -> dict[str, Any]:
    """把模板/旧任务里的契约归一成稳定结构；缺失字段给安全默认值。

    旧任务没有 contract，不能突然按新模板标准判失败——默认 min_chars=0，
    只保留“必须非空”这一条通用底线。
    """
    data = raw if isinstance(raw, dict) else {}
    max_chars = _as_int(data.get("max_chars"), DEFAULT_MAX_CHARS)
    max_chars = max(100, min(max_chars, MAX_CONTRACT_CHARS))
    min_chars = _as_int(data.get("min_chars"), 0)
    min_chars = max(0, min(min_chars, max_chars))
    sections: list[str] = []
    raw_sections = data.get("required_sections")
    if isinstance(raw_sections, list):
        for item in raw_sections[:MAX_SECTIONS]:
            text = str(item or "").strip()[:24]
            if text and text not in sections:
                sections.append(text)
    route = str(data.get("route") or "").strip()
    if route not in ("", "market", "ledger"):
        # 未知路由不猜：留空走全量只读工具面，避免悄悄换成不相关工具集。
        route = ""
    return {
        "min_chars": min_chars,
        "max_chars": max_chars,
        "required_sections": sections,
        "forbid_placeholders": bool(data.get("forbid_placeholders", False)),
        "use_tools": bool(data.get("use_tools", False)),
        "route": route,
    }


def validate_artifact(text: str, raw_contract: Any) -> list[str]:
    """返回违反项；空列表表示通过。只做确定性文本检查。"""
    contract = normalize_contract(raw_contract)
    body = str(text or "").strip()
    errors: list[str] = []
    if not body:
        return ["产物为空"]
    chars = len(body)
    if chars < contract["min_chars"]:
        errors.append(f"字数不足：{chars} < {contract['min_chars']}")
    for section in contract["required_sections"]:
        if section not in body:
            errors.append(f"缺少必需小节：{section}")
    if contract["forbid_placeholders"]:
        hit = _PLACEHOLDER_RE.search(body)
        if hit:
            errors.append(f"含占位内容：{hit.group(0)}")
    return errors


def describe_contract(raw_contract: Any) -> str:
    """生成给模型看的契约说明；和校验逻辑同源，避免提示与判定脱节。"""
    contract = normalize_contract(raw_contract)
    parts: list[str] = []
    if contract["min_chars"]:
        parts.append(f"正文至少 {contract['min_chars']} 字")
    parts.append(f"正文不超过 {contract['max_chars']} 字")
    if contract["required_sections"]:
        parts.append("必须包含以下小节：" + "、".join(contract["required_sections"]))
    if contract["forbid_placeholders"]:
        parts.append("不得出现 TODO、待补充、此处省略等占位内容")
    if contract["use_tools"]:
        domain = {"market": "行情与持仓", "ledger": "账本与财务", "": "本地财务"}[
            contract["route"]
        ]
        parts.append(f"可调用{domain}只读工具核实数据；工具结果要落进正文，不得编造数字")
    return "；".join(parts)


def contract_errors_text(errors: list[str]) -> str:
    return "；".join(str(e) for e in errors if str(e).strip())[:300]
