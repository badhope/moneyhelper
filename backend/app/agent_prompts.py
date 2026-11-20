"""Agent 说明书：通用内核提示词与 supervisor 指令文件加载（agents/<name>/instructions.md）。"""

from __future__ import annotations

import pathlib

GENERAL_SYSTEM = (
    "You are an autonomous general-purpose agent. Rules:\n"
    "1. Need a real fact, date, time, or the latest news? Call a tool to fetch it — never invent it.\n"
    "2. You may call several independent tools in one turn and continue after their results return.\n"
    "3. Give a one-line conclusion first, then the key points, in the user's language.\n"
    "4. If a tool fails or returns nothing, say so plainly rather than guessing.\n"
    "You have only general-purpose tools (web_search, get_now) and NO access to the user's financial "
    "data — for portfolio/ledger/finance questions say you don't have that data."
)


_AGENTS_DIR = pathlib.Path(__file__).parent / "agents"

def _load_instructions(agent_name: str) -> str:
    """从 agents/<name>/instructions.md 读系统提示词。"""
    p = _AGENTS_DIR / agent_name / "instructions.md"
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").strip()

AGENT_SYSTEM = _load_instructions("supervisor")
