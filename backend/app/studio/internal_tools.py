"""内置科研工具：确定性计算，不联网、不依赖第三方库。

这些是项目自研的「优势工具」，只在内部 Agent 工具面暴露，不通过 MCP Server 对外开放。
用户可在「设置 → 内置工具」逐个开关；关闭后对应工具从模型工具面移除。
"""

from __future__ import annotations

from typing import Any

from .internal_tools_common import _fail  # noqa: F401
from .internal_tools_data import (  # noqa: F401
    dataset_profile,
    experiment_design_check,
    sensitivity_analysis,
    stats_summary,
)
from .internal_tools_research import (  # noqa: F401
    citation_format,
    literature_search_plan,
    research_outline,
)
from .internal_tools_score import source_quality_score  # noqa: F401

INTERNAL_TOOL_SPECS: dict[str, dict[str, Any]] = {
    "research_outline": {
        "description": "科研大纲生成器：按论文类型（empirical/review/thesis/grant）输出结构化大纲与每节写作要点。",
        "impl": research_outline,
    },
    "citation_format": {
        "description": "引用格式化：把文献元数据批量格式化为 GB/T 7714、APA 7、MLA 9 或 Chicago。",
        "impl": citation_format,
    },
    "literature_search_plan": {
        "description": "检索式构造器：按研究问题生成 PICO 拆解、布尔检索式与纳排标准。",
        "impl": literature_search_plan,
    },
    "dataset_profile": {
        "description": "数据画像：对 CSV 文本输出行列数、类型、缺失率、数值分布与高频取值。",
        "impl": dataset_profile,
    },
    "stats_summary": {
        "description": "统计摘要：样本量、均值/中位数/标准差、分位数、95% 置信区间、异常值与偏度。",
        "impl": stats_summary,
    },
    "sensitivity_analysis": {
        "description": "敏感性分析：对基准值做 ±N% 网格，输出各档结果与变化量。",
        "impl": sensitivity_analysis,
    },
    "experiment_design_check": {
        "description": "实验设计核查：设计类型、随机化、盲法、样本量与偏倚风险清单。",
        "impl": experiment_design_check,
    },
    "source_quality_score": {
        "description": "来源可信度评分：按同行评议、期刊层级、方法透明度、时效与引用给出 0-100 分与理由。",
        "impl": source_quality_score,
    },
}

INTERNAL_TOOL_INPUTS: dict[str, dict[str, Any]] = {
    "research_outline": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "研究主题/论文标题"},
            "paper_type": {
                "type": "string",
                "enum": ["empirical", "review", "thesis", "grant"],
                "description": "论文类型，默认 empirical",
            },
        },
        "required": ["topic"],
        "additionalProperties": False,
    },
    "citation_format": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "文献数组，每项含 title/authors/year/journal/volume/issue/pages/doi",
                "items": {"type": "object"},
            },
            "style": {"type": "string", "description": "gbt7714/APA/MLA/Chicago，默认 gbt7714"},
        },
        "required": ["items"],
        "additionalProperties": False,
    },
    "literature_search_plan": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "研究问题"},
            "databases": {"type": "string", "description": "数据库，可省略"},
            "years": {"type": "string", "description": "时间范围，可省略"},
        },
        "required": ["question"],
        "additionalProperties": False,
    },
    "dataset_profile": {
        "type": "object",
        "properties": {
            "csv_text": {"type": "string", "description": "CSV 文本（含表头）"},
            "max_columns": {"type": "integer", "description": "最多分析列数，默认 20"},
        },
        "required": ["csv_text"],
        "additionalProperties": False,
    },
    "stats_summary": {
        "type": "object",
        "properties": {"values": {"type": "array", "items": {"type": "number"}, "description": "数值数组"}},
        "required": ["values"],
        "additionalProperties": False,
    },
    "sensitivity_analysis": {
        "type": "object",
        "properties": {
            "base_value": {"type": "number", "description": "基准值"},
            "variable": {"type": "string", "description": "变量名称"},
            "pct_range": {"type": "number", "description": "波动百分比，默认 20"},
            "steps": {"type": "integer", "description": "单侧档数，默认 4"},
        },
        "required": ["base_value"],
        "additionalProperties": False,
    },
    "experiment_design_check": {
        "type": "object",
        "properties": {
            "design": {"type": "string", "description": "rct/quasi/cohort/case-control/cross-section/ab-test/pre-post"},
            "sample_size": {"type": "integer", "description": "样本量"},
            "randomized": {"type": "boolean", "description": "是否随机化"},
            "blinding": {"type": "string", "description": "none/single/double"},
        },
        "required": ["design"],
        "additionalProperties": False,
    },
    "source_quality_score": {
        "type": "object",
        "properties": {
            "peer_reviewed": {"type": "boolean", "description": "是否同行评议"},
            "venue_tier": {"type": "string", "description": "top/q1/q2/q3/q4/unknown"},
            "methods_detail": {"type": "string", "description": "full/partial/none"},
            "year": {"type": "integer", "description": "发表年份"},
            "citations": {"type": "integer", "description": "被引次数"},
        },
        "required": [],
        "additionalProperties": False,
    },
}

INTERNAL_FUNCTION_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": spec["description"],
            "parameters": INTERNAL_TOOL_INPUTS[name],
        },
    }
    for name, spec in INTERNAL_TOOL_SPECS.items()
]


def run_internal_tool(name: str, args: dict[str, Any]) -> str | None:
    spec = INTERNAL_TOOL_SPECS.get(name)
    if spec is None:
        return None
    try:
        return spec["impl"](args or {})
    except Exception as exc:  # noqa: BLE001 — 工具失败回填错误串，不炸主循环
        return f"工具执行失败：{type(exc).__name__}: {exc}"

