"""Agent 配置系统：角色 / skills / 工具开关。

默认配置在 agents/default_config.json，启动时写入 settings 表。
用户可以在设置页自定义修改。
"""

from __future__ import annotations

import json
import pathlib
import re
import uuid
from typing import Any

from . import db
from .logging_utils import get_logger

log = get_logger(__name__)

_CONFIG_FILE = pathlib.Path(__file__).parent / "agents" / "default_config.json"
_SETTINGS_KEY = "agent_config"


def _load_default() -> dict[str, Any]:
    """从 default_config.json 读默认配置。"""
    if not _CONFIG_FILE.exists():
        return {}
    return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))


def _merge_defaults(cfg: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """把默认包里的角色/技能补进已有配置（不覆盖用户改过的同名项）。

    为什么需要：老库的 agent_config 是历史默认值的快照，新增内置角色与技能
    不会自动出现，用户会看到「设置里是空的」。只补缺失项，不覆盖用户配置。
    """
    default = _load_default()
    if not default:
        return cfg, False
    changed = False
    for bucket_name in ("agents", "skills"):
        bucket = cfg.setdefault(bucket_name, {})
        for aid, asset in (default.get(bucket_name) or {}).items():
            if aid not in bucket:
                bucket[aid] = json.loads(json.dumps(asset, ensure_ascii=False))
                changed = True
    defaults = cfg.setdefault("defaults", {})
    for k, v in (default.get("defaults") or {}).items():
        if k not in defaults:
            defaults[k] = v
            changed = True
    if "version" not in cfg:
        cfg["version"] = default.get("version", "3.0")
        changed = True
    return cfg, changed


async def init_default_config() -> None:
    """启动时调用：没有配置就写默认值；已有配置则补齐新增内置项。"""
    existing = (await db.get_settings()).get(_SETTINGS_KEY)
    if existing:
        try:
            cfg = json.loads(existing)
        except Exception:  # noqa: BLE001 — 损坏配置回落默认包
            cfg = {}
        merged, changed = _merge_defaults(cfg)
        if changed:
            await db.set_setting(_SETTINGS_KEY, json.dumps(merged, ensure_ascii=False))
            log.info("agent.config.merged_new_builtins")
        else:
            log.info("agent.config.loaded from_db=true")
        return
    default = _load_default()
    if not default:
        return
    await db.set_setting(_SETTINGS_KEY, json.dumps(default, ensure_ascii=False))
    log.info("agent.config.init_default version=%s", default.get("version", "?"))


async def get_config() -> dict[str, Any]:
    """读当前 agent 配置（数据库里的；缺失的内置项按默认包补齐）。"""
    raw = (await db.get_settings()).get(_SETTINGS_KEY)
    cfg: dict[str, Any] = {}
    if raw:
        try:
            cfg = json.loads(raw)
        except Exception:
            cfg = {}
    merged, _ = _merge_defaults(cfg)
    return merged


async def update_config(new_config: dict[str, Any]) -> None:
    """保存用户修改后的配置。"""
    await db.set_setting(_SETTINGS_KEY, json.dumps(new_config, ensure_ascii=False))
    log.info("agent.config.updated")


async def get_agent_tools(agent_name: str) -> list[str] | str:
    """获取某个 agent 启用的工具列表。返回 'all' 表示全部工具。"""
    cfg = await get_config()
    agent_cfg = cfg.get("agents", {}).get(agent_name, {})
    return agent_cfg.get("tools", "all")


async def is_skill_enabled(skill_name: str) -> bool:
    """检查某个 skill 是否启用。"""
    cfg = await get_config()
    skill_cfg = cfg.get("skills", {}).get(skill_name, {})
    return skill_cfg.get("enabled", True)


# 内置技能（default_config.json 预置）；其余为用户/AI 生成的「自定义技能」。
BUILTIN_SKILLS = frozenset((_load_default().get("skills") or {}).keys()) or frozenset(
    {"risk_analysis", "goals_tracking", "morning_report", "long_memory"}
)

# 纯提示型内置技能 → 注入的指令块（没有对应工具开关的技能走这里）
_SKILL_PROMPTS: dict[str, str] = {
    "research_writing": "科研写作：论文结构按 IMRaD；引用格式统一；投稿前检查图表编号、字数限制与匿名要求。",
    "literature_review": "文献综述：先定检索式与纳排标准；按主题组织证据；标注证据强度与冲突。",
    "data_analysis": "数据分析：先做缺失率与分布检查；异常值单独说明；图表标注单位与样本量。",
}

# 内置技能 → 运行时能力映射（技能开关真正生效的落点）：
# 关闭某技能 → 对应工具从 agent 工具面移除（agent / react 两条路径都过滤）。
_SKILL_TOOLS: dict[str, set[str]] = {
    "risk_analysis": {"get_risk_flags", "get_health_check"},
    "goals_tracking": {"get_goals"},
    "long_memory": {"get_user_memory"},
}


async def disabled_tool_names() -> set[str]:
    """按已关闭的内置技能，返回应从 agent 工具面移除的工具名集合。"""
    cfg = await get_config()
    skills = cfg.get("skills", {})
    out: set[str] = set()
    for skill, tool_names in _SKILL_TOOLS.items():
        if not skills.get(skill, {}).get("enabled", True):
            out |= tool_names
    return out


async def custom_skill_prompt() -> str:
    """启用中的「自定义技能」（非内置）→ 注入 agent 的个性化指令块。

    这一块让「设置 → Agent → AI 生成技能」真正生效：生成的技能以
    「名称：描述」形式进入系统提示，模型会在相关场景遵循。
    """
    cfg = await get_config()
    lines: list[str] = []
    for sid, s in (cfg.get("skills") or {}).items():
        if sid in BUILTIN_SKILLS or not s.get("enabled", True):
            continue
        name = str(s.get("name") or sid).strip()
        desc = str(s.get("description") or "").strip()
        if name:
            lines.append(f"- {name}：{desc}" if desc else f"- {name}")
    if not lines:
        return ""
    return "用户自定义技能（用户主动启用，请在相关场景遵循）：\n" + "\n".join(lines[:10])


# 定时动作的星期编号：0=周一 … 6=周日（与 Python date.weekday() 一致）。
# 时间一律按 Asia/Shanghai 解释（与晨报/订阅巡检同一时区口径）。
_SKILL_ACTION_TIME_RE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


def normalize_skill_action(action: Any) -> dict[str, Any] | None:
    """校验并规范化技能动作；非法返回 None（fail-closed，调用方决定剔除或报错）。

    合法形状：{"prompt": "≤200 字", "time": "HH:MM", "weekdays": [0..6]}
    weekdays 缺省或空数组 = 每天；未知/越界值一律判非法（不静默篡改）。
    """
    if not isinstance(action, dict):
        return None
    prompt = str(action.get("prompt") or "").strip()
    if not prompt or len(prompt) > 200:
        return None
    time_raw = str(action.get("time") or "").strip()
    if not _SKILL_ACTION_TIME_RE.fullmatch(time_raw):
        return None
    days_raw = action.get("weekdays") or []
    if not isinstance(days_raw, list):
        return None
    days: set[int] = set()
    for d in days_raw:
        if isinstance(d, bool) or not isinstance(d, int) or d < 0 or d > 6:
            return None
        days.add(d)
    return {"prompt": prompt, "time": time_raw, "weekdays": sorted(days)}


def clean_config(cfg: Any) -> tuple[dict[str, Any], list[str]]:
    """保存前清洗配置：动作非法则剔除并回报 warning（不静默、不阻断其余保存）。

    返回 (清洗后的配置, warnings)；深拷贝，不修改调用方对象。
    """
    warnings: list[str] = []
    out: dict[str, Any] = json.loads(json.dumps(cfg or {}))
    skills = out.get("skills")
    if not isinstance(skills, dict):
        return out, warnings
    for sid, s in skills.items():
        if not isinstance(s, dict) or "action" not in s:
            continue
        if s.get("action") is None:
            s.pop("action")  # 显式清空
            continue
        a = normalize_skill_action(s.get("action"))
        if a is None:
            name = str(s.get("name") or sid)
            warnings.append(
                f"技能「{name}」的定时动作配置无效（需 prompt + HH:MM 时间 + 0-6 星期），已忽略"
            )
            s.pop("action", None)
        else:
            s["action"] = a
    return out, warnings


async def generate_suggestion(kind: str, prompt: str, agent_name: str = "") -> dict[str, Any] | None:
    """按自然语言描述生成配置建议（skill 或某 agent 的名称/描述）。

    只产出建议、不落库——由用户在设置页确认后随既有保存流程写入。
    模型不可用 / 输出非法一律返回 None（fail-closed，调用方给出友好错误）。
    """
    from . import llm

    if kind == "skill":
        system = (
            "你是财务助手的功能技能设计器。根据用户描述生成一个 JSON："
            '{"id": "snake_case_ascii 唯一短 id", "name": "4-6 字中文名", '
            '"description": "一句话说明这个技能做什么（中文，40 字以内）", '
            '"action": {"prompt": "到点让助手做的事（自然语言，可含数字，如：检查我的持仓集中度并给一句风险提示）", '
            '"time": "HH:MM", "weekdays": [0-6 的整数数组]}}。'
            "action 规则：仅当用户描述里包含定时意图（如「每周日晚」「每天早上」「周五 9 点」）时才给出；"
            "weekdays 0=周一 … 6=周日，每天都提醒则给空数组 []；时间用 24 小时制。"
            "没有定时意图时省略 action 字段。只输出 JSON，不要多余文字。"
        )
    elif kind == "agent":
        system = (
            f"你是财务助手中 {agent_name or '某个'} 角色的设计器。根据用户描述生成 JSON："
            '{"name": "4-8 字中文角色名", "description": "一句话职责说明（中文，40 字以内）"}。只输出 JSON。'
        )
    else:
        return None

    out = await llm.json_complete(system, prompt, timeout=20.0)
    if not isinstance(out, dict):
        return None
    name = str(out.get("name") or "").strip()[:20]
    desc = str(out.get("description") or "").strip()[:80]
    if not name or not desc:
        return None
    if kind == "skill":
        raw_id = str(out.get("id") or "").strip().lower()
        sid = re.sub(r"[^a-z0-9_]+", "_", raw_id).strip("_") or f"skill_{uuid.uuid4().hex[:8]}"
        suggestion: dict[str, Any] = {"id": sid, "name": name, "description": desc, "enabled": True}
        # 定时动作：模型给了就校验，非法直接丢弃（技能本身仍可用，不因动作不合法整体失败）
        action = normalize_skill_action(out.get("action"))
        if action:
            suggestion["action"] = action
        return suggestion
    return {"name": name, "description": desc}
