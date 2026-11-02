"""定位文案纠偏（v4.6）：把「local-first 隐私」从卖点降级为部署选项。

依据 docs/ROADMAP-v3.md 第〇节：
> **弃用口号**："local-first 隐私"降级为部署选项之一，不再当核心卖点。
> **新定位**：**"能自主干活的财务部门"** —— 不只是一个记账工具，而是一个可编排、可复核、可接管的 AI 财务团队。

本脚本只改「对外定位」相关文案（README / docs/index / package description / frontend meta），
不改事实陈述（数据确实存本地 SQLite，这句话保留但降级为「部署形态」小节）。
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(".")

# 一句话定位（中英）：服务对象 + 核心能力 + 差异化，不堆形容词
POSITION_ZH = (
    "面向个人与小微公司的 AI 财务部门：一句话记账、持仓风控、股票投研、财报分析、税负测算、"
    "资金调度，从「看到问题」到「给出可执行动作」全链路闭环；每个数字由确定性引擎算出并可追溯，"
    "每次操作进审计链。"
)
POSITION_EN = (
    "An AI finance department for individuals and small businesses: one sentence to book an expense, "
    "then portfolio risk, equity research, statement analysis, tax estimates and cash scheduling — "
    "a full loop from spotting a problem to a checkable action. Every number comes from a deterministic "
    "engine and is traceable; every operation lands in an audit trail."
)


def _replace_section(text: str, anchor_start: str, anchor_end: str, new: str) -> str:
    """替换 [anchor_start, anchor_end) 之间的内容；找不到就原样返回。"""
    i = text.find(anchor_start)
    if i < 0:
        return text
    j = text.find(anchor_end, i + len(anchor_start))
    if j < 0:
        return text
    return text[:i] + new + text[j:]


def fix_readme_en() -> bool:
    p = ROOT / "README.md"
    if not p.exists():
        return False
    s = p.read_text(encoding="utf-8")
    orig = s
    # 1) 定义句：local-first workbench → 财务部门
    s = s.replace(
        'Moneyhelper is **not "a generic chat model + a bookkeeping plugin"** — it is a local-first **vertical finance intelligence workbench**:',
        'Moneyhelper is **not "a generic chat model + a bookkeeping plugin"** — it is an **AI finance department you can audit**:',
    )
    s = s.replace(
        "Moneyhelper is the helper for your money: a local-first workbench that turns every entry into a decision you can check,\nso saving and investing stay deliberate instead of hopeful.",
        "Moneyhelper is the finance team your money never had: it turns every entry into a decision you can check,\nfrom bookkeeping to tax estimates to execution hand-offs, so saving and investing stay deliberate instead of hopeful.",
    )
    # 2) 隐私行：从核心卖点表里降级（保留事实，改表述）
    s = s.replace(
        "| Privacy | Raw data goes to the model provider | Local-first: sensitive data stays in local SQLite, only sanitized structured data leaves the machine |",
        "| Data handling | Raw data goes to the model provider | Sensitive data stays in your own SQLite; only sanitized structured context is sent to the model. Local, self-hosted or cloud are all deployment options |",
    )
    # 3) topics 去掉 local-first 标签（保留 sqlite 这个事实标签）
    s = s.replace("`sqlite` `local-first` `mcp`", "`sqlite` `self-hosted` `mcp`")
    if s != orig:
        p.write_text(s, encoding="utf-8")
        return True
    return False


def fix_readme_zh() -> bool:
    p = ROOT / "README.zh.md"
    if not p.exists():
        return False
    s = p.read_text(encoding="utf-8")
    orig = s
    s = s.replace(
        "- **数据留在本机**：本地 SQLite，可选口令加密备份，财务数据不出本机。",
        "- **数据在你手里**：默认 SQLite 本地存储 + 可选口令加密备份；也可部署为自托管服务或云端实例，形态自选。",
    )
    s = s.replace(
        "**Moneyhelper 不是「会聊天的通用大模型 + 记账插件」，而是一个本地优先的垂直财务智能体工作台**：",
        "**Moneyhelper 不是「会聊天的通用大模型 + 记账插件」，而是一个能自主干活、且每一步都可审计的 AI 财务部门**：",
    )
    s = s.replace(
        "| 数据隐私 | 原始数据发往模型服务商 | 本地优先，敏感财务数据只存本机 SQLite，仅脱敏结构化数据出机 |",
        "| 数据归属 | 原始数据发往模型服务商 | 敏感数据存在你自己的 SQLite 里，只有脱敏的结构化上下文发给模型；本地 / 自托管 / 云端都是部署选项 |",
    )
    s = s.replace("`sqlite` `local-first` `mcp`", "`sqlite` `self-hosted` `mcp`")
    if s != orig:
        p.write_text(s, encoding="utf-8")
        return True
    return False


def fix_docs_index() -> bool:
    p = ROOT / "docs" / "index.md"
    if not p.exists():
        return False
    s = p.read_text(encoding="utf-8")
    orig = s
    s = s.replace(
        "> 算清每一笔，攒稳每一步 — 本地优先、数字可复核、全 MCP 开放的个人财务 Agent",
        f"> 算清每一笔，攒稳每一步 — {POSITION_ZH}",
    )
    if s != orig:
        p.write_text(s, encoding="utf-8")
        return True
    return False


def fix_pyproject() -> bool:
    p = ROOT / "pyproject.toml"
    if not p.exists():
        return False
    s = p.read_text(encoding="utf-8")
    orig = s
    s = s.replace(
        'description = "Moneyhelper —— 本地优先的垂直财务智能体工作台（数字可复核、投研/财报/策略全流程、MCP 开放）"',
        'description = "Moneyhelper —— 面向个人与小微公司的 AI 财务部门（记账/投研/财报/税负/资金调度，数字可复核、操作可审计、MCP 开放）"',
    )
    if s != orig:
        p.write_text(s, encoding="utf-8")
        return True
    return False


def fix_frontend_meta() -> bool:
    p = ROOT / "frontend" / "index.html"
    if not p.exists():
        return False
    s = p.read_text(encoding="utf-8")
    orig = s
    s = re.sub(
        r'<meta name="description" content="[^"]*" />',
        '<meta name="description" content="Moneyhelper —— 面向个人与小微公司的 AI 财务部门：一句话记账、持仓风控、股票投研、财报分析、税负测算、资金调度；数字由确定性引擎算出可追溯，操作进审计链。" />',
        s,
        count=1,
    )
    s = re.sub(
        r'<meta name="keywords" content="[^"]*" />',
        '<meta name="keywords" content="AI财务,财务部门,记账,理财,股票,基金,投研,财报分析,税务测算,现金流,FastAPI,React,LangGraph,personal finance,finance assistant,bookkeeping,portfolio,stock,open source,self-hosted" />',
        s,
        count=1,
    )
    s = re.sub(
        r'<meta property="og:description" content="[^"]*" />',
        '<meta property="og:description" content="记一笔，问一句。面向个人与小微公司的 AI 财务部门：记账 / 持仓 / 投研 / 财报 / 税负 / 资金调度，数字可复核。" />',
        s,
        count=1,
    )
    s = re.sub(
        r'"description": "[^"]*"',
        '"description": "An AI finance department for individuals and small businesses: bookkeeping, portfolio risk, research, statement analysis, tax estimates and cash scheduling — every number deterministic and traceable."',
        s,
        count=1,
    )
    if s != orig:
        p.write_text(s, encoding="utf-8")
        return True
    return False


def main() -> None:
    changed = []
    if fix_readme_en():
        changed.append("README.md")
    if fix_readme_zh():
        changed.append("README.zh.md")
    if fix_docs_index():
        changed.append("docs/index.md")
    if fix_pyproject():
        changed.append("pyproject.toml")
    if fix_frontend_meta():
        changed.append("frontend/index.html")
    print("positioning fixed:", ", ".join(changed) or "(no change)")


if __name__ == "__main__":
    main()
