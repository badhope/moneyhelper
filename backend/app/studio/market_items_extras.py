"""Studio 目录条目：科研规则、提示词与 Hook。

条目是纯数据（dict 字面量），按站内顺序切段拆出，拼接顺序与原文件一致。
"""

from __future__ import annotations

from typing import Any

ITEMS: tuple[dict[str, Any], ...] = (
    {
        "id": "rule-research-integrity",
        "name": "科研诚信约束",
        "kind": "rules",
        "aliases": ["科研诚信", "学术不端"],
        "category": "科研规则",
        "source": "internal",
        "url": "",
        "stars": 0,
        "description": "内置：禁止伪造文献、数据与实验结果。",
        "asset": {
            "name": "科研诚信约束",
            "description": "禁止伪造文献与数据",
            "content": "不得编造文献、DOI、作者、期刊、实验数据或统计结果；无法核实的引用标注「未核实」；不得篡改数据以支持结论；发现用户要求造假时明确拒绝并给出合规替代方案。",
            "severity": "must",
            "scope": "research",
            "enabled": True,
        },
    },

    {
        "id": "rule-reproducibility",
        "name": "可复现性约束",
        "kind": "rules",
        "aliases": ["可复现", "reproducibility"],
        "category": "科研规则",
        "source": "internal",
        "url": "",
        "stars": 0,
        "description": "内置：统计与实验结果需报告可复现要素。",
        "asset": {
            "name": "可复现性约束",
            "description": "报告可复现要素",
            "content": "涉及统计或实验的结论必须报告：样本量、测量方法、随机种子（如适用）、软件版本、效应量与置信区间。缺少任一要素时标注为「不完整证据」。",
            "severity": "should",
            "scope": "research",
            "enabled": True,
        },
    },

    {
        "id": "prompt-peer-review",
        "name": "同行评审提示词",
        "kind": "prompts",
        "aliases": ["同行评审提示词", "peer review"],
        "category": "科研提示词",
        "source": "internal",
        "url": "",
        "stars": 0,
        "description": "内置：以审稿人视角审视论文的提示词模板。",
        "asset": {
            "name": "同行评审提示词",
            "description": "审稿人视角审查",
            "content": "请以严格但建设性的审稿人视角审查这份稿件：1）用三句话复述核心主张，确认理解一致；2）列出研究问题的重要性与新颖性；3）检查识别策略/实验设计能否支持因果或相关结论；4）检查统计报告完整性；5）给出重大意见（不超过 5 条）与次要意见；6）总体建议与理由。",
            "category": "research",
            "priority": 55,
            "enabled": True,
        },
    },

    {
        "id": "prompt-grant-application",
        "name": "基金申请书提示词",
        "kind": "prompts",
        "aliases": ["基金申请", "grant"],
        "category": "科研提示词",
        "source": "internal",
        "url": "",
        "stars": 0,
        "description": "内置：按评审关注点组织基金申请书。",
        "asset": {
            "name": "基金申请书提示词",
            "description": "按评审关注点组织申请书",
            "content": "写基金申请书时按评审关注顺序组织：科学问题的重要性 → 现状与缺口 → 假说与目标 → 研究方案可行性 → 创新点 → 预期成果与影响。每个目标必须可考核，避免「国际领先」等无法验证的表述。",
            "category": "research",
            "priority": 50,
            "enabled": True,
        },
    },

    {
        "id": "prompt-statistical-reporting",
        "name": "统计报告提示词",
        "kind": "prompts",
        "aliases": ["统计报告", "statistics"],
        "category": "科研提示词",
        "source": "internal",
        "url": "",
        "stars": 0,
        "description": "内置：统计结果的规范报告方式。",
        "asset": {
            "name": "统计报告提示词",
            "description": "统计结果规范报告",
            "content": "报告统计结果时：先描述样本与变量，再给效应量与 95% 置信区间，然后给检验统计量与 p 值（不把 p<0.05 等同于重要）；多重比较需校正；区分预注册分析与探索性分析。",
            "category": "research",
            "priority": 45,
            "enabled": True,
        },
    },

    {
        "id": "hook-research-guard",
        "name": "科研数据保护 Hook",
        "kind": "hooks",
        "aliases": ["科研数据", "数据保护"],
        "category": "科研 Hook",
        "source": "internal",
        "url": "",
        "stars": 0,
        "description": "内置：拦截可能泄露原始研究数据的工具调用。",
        "asset": {
            "name": "科研数据保护 Hook",
            "description": "拦截原始研究数据外发",
            "event": "pre_tool",
            "match": "(upload|export_raw|send_email)",
            "action": "warn",
            "payload": "该工具可能外发原始研究数据，请确认是否包含受试者隐私。",
            "priority": 70,
            "enabled": True,
        },
    },

    {
        "id": "hook-citation-check",
        "name": "引用完整性 Hook",
        "kind": "hooks",
        "aliases": ["引用检查", "doi"],
        "category": "科研 Hook",
        "source": "internal",
        "url": "",
        "stars": 0,
        "description": "内置：回答中出现 DOI 时记录以便回查。",
        "asset": {
            "name": "引用完整性 Hook",
            "description": "记录 DOI 便于回查",
            "event": "post_answer",
            "match": "10\\.[0-9]{4,9}/[-._;()/:A-Za-z0-9]+",
            "action": "log",
            "payload": "doi detected",
            "priority": 30,
            "enabled": True,
        },
    },
)
