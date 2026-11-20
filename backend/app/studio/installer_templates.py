"""按资产类型取空白模板（新建提示词/约束/Hook/工具时的初始内容）。"""

from __future__ import annotations

import json
from typing import Any


def template_for(kind: str) -> dict[str, Any]:
    templates: dict[str, dict[str, Any]] = {
        "prompts": {
            "name": "我的提示词",
            "description": "一句话说明用途",
            "category": "custom",
            "priority": 50,
            "enabled": True,
            "content": "在这里写提示词正文。建议：先写目标，再写约束，最后写输出格式。",
        },
        "rules": {
            "name": "我的约束",
            "description": "一句话说明约束目的",
            "severity": "should",
            "scope": "all",
            "enabled": True,
            "content": "约束正文。must 级约束违反时回答不合格；should 级为默认建议。",
        },
        "hooks": {
            "name": "我的 Hook",
            "description": "一句话说明触发场景",
            "event": "pre_tool",
            "action": "warn",
            "match": "tool_name_pattern",
            "payload": "提示文案或注入内容",
            "priority": 50,
            "enabled": True,
        },
        "roles": {
            "name": "我的角色",
            "description": "一句话职责",
            "instructions": "你是……。职责：……。输出：……。边界：……。",
            "tools": "all",
            "temperature": 0.2,
            "enabled": True,
        },
        "skills": {
            "name": "我的技能",
            "description": "一句话描述技能",
            "content": "技能指令正文：何时使用、步骤、验收标准。",
            "enabled": True,
        },
    }
    if kind not in templates:
        raise ValueError(f"未知资产类型：{kind}")
    return json.loads(json.dumps(templates[kind], ensure_ascii=False))
