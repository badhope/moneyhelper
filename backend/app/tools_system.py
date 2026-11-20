"""系统域工具（从 tools.py 拆出）：体检、备份、设置、时间、联网搜索。

都是不写账的业务工具：体检只读、备份只落数据目录、设置只改白名单键、
联网搜索失败兜底为一句提示。拆出来是为了让 tools.py 只剩编排与注册。
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
from typing import Any

from . import analysis, backup, db, scheduler
from .db._core import data_dir
from .quotes import invalidate_quotes_cache

# 备份包与数据库同目录（默认 backend/data，Docker 卷 moneyhelper-data），
# 容器重建不丢；路径本身不落库。
BACKUP_DIR = data_dir() / "backups"

# tool_set_setting 可写的键白名单：防止模型/动作带任意 key 往 settings 表写脏键。
# 值与枚举校验仍在各分支内完成；列表以外的 key 一律拒绝。
SETTING_KEYS_ALLOWED = frozenset({
    "monthly_income", "emergency_target_months", "essential_categories",
    "quote_source_mode", "report_time", "voice_input", "show_export",
    "expand_process", "show_suggestions", "auto_refresh", "auto_refresh_seconds",
    "compact_numbers", "color_scheme", "default_tab", "savings_goal",
    "report_focus", "lang",
    "ai_base_url", "ai_api_key", "ai_model",  # 这三个在下方被显式拒绝
})


async def tool_get_health_check(_args: dict[str, Any]) -> str:
    """跑一次结构化财务体检：资产配置 / 现金流 / 负债 / 应急金 / 目标进度 五维评分与建议。无参数。"""
    positions = await db.list_positions()
    from .quotes import live_quotes

    live = await live_quotes(positions)
    settings = await db.get_settings()
    m = analysis.market_view(positions, live)
    led = analysis.ledger_view(
        await db.list_transactions(),
        await db.list_subscriptions(),
        await db.list_debts(),
        settings,
        positions,
        live,
    )
    flags = analysis.risk_checks(m, led)
    report = analysis.health_check(m, led, flags, await db.list_goals())
    return json.dumps(report, ensure_ascii=False)


async def tool_backup_now(_args: dict[str, Any], lang: str = "zh") -> dict[str, str]:
    """生成一份本地加密备份包（PBKDF2+Fernet）。

    返回 {"answer":..., "passphrase":...}：answer 不含明文口令（防 SSE 帧截获）；
    passphrase 单独返回，仅由前端从 final 事件取出单独展示（口令绝不写入问答历史/日志）。
    """
    data = await db.export_data()
    passphrase = secrets.token_urlsafe(16)  # ~128 bit 熵，匹配 PBKDF2 600k 迭代离线防护
    payload = backup.encrypt_export(data, passphrase)
    import datetime as _dt

    path = BACKUP_DIR / f"moneyhelper-backup-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # 纵深防御：备份只允许落在数据目录内，不能因为路径常量被改就写到别处
    from .pathguard import assert_within

    assert_within(path, BACKUP_DIR.parent, operation="写备份到")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    if lang != "zh":
        answer = (
            f"Local encrypted backup created: {path.name}\n"
            "Restoring: Settings → Data & state → Restore backup.\n"
            "The decryption passphrase will be shown separately — please save it now."
        )
    else:
        answer = (
            f"已生成本地加密备份：{path.name}\n"
            "恢复方法：设置 → 数据与状态 → 恢复备份。\n"
            "解密口令将单独展示——请现在妥善保存。"
        )
    return {"answer": answer, "passphrase": passphrase}


async def tool_set_setting(args: dict[str, Any], lang: str = "zh") -> str:
    """修改应用设置（涨跌颜色/默认首页/语言/数字格式/快捷建议/晨报时间）。"""
    en = lang != "zh"
    key = str(args.get("key") or "").strip()
    value = args.get("value")
    if not key or value is None:
        if en:
            return "Please provide a key and a value, e.g. set default home to Holdings, or set the color scheme to green-up."
        return "需要提供 key 与 value，例如：改默认首页为持仓页、涨跌颜色改成绿涨红跌"
    raw = str(value)
    if len(raw) > 2000:
        return "Value too long (max 2000 characters)" if en else "设置值过长（最多 2000 字符）"
    if key not in SETTING_KEYS_ALLOWED:
        return (f"Unsupported config key: {key}" if en else f"不支持修改配置项：{key}（仅支持设置页存在的配置）")
    # AI 接入配置含密钥/端点，只允许在设置页（/api/settings）修改，工具层一律拒绝，
    # 防止把模型调用重定向到攻击者端点造成数据外带。
    if key in ("ai_base_url", "ai_api_key", "ai_model"):
        return (f"{key} is AI-connection config — edit it in Settings → AI answers" if en else f"{key} 属于 AI 接入配置，请到「设置 → AI 回答」中修改")
    if key == "color_scheme" and raw not in ("cn", "us"):
        return "color_scheme must be cn (red-up/green-down) or us (green-up/red-down)" if en else "涨跌颜色只能是 cn（红涨绿跌）或 us（绿涨红跌）"
    if key == "default_tab" and raw not in ("overview", "holdings", "market", "ledger", "chat", "features"):
        return "default_tab must be overview/holdings/market/ledger/chat/features" if en else "默认首页只能是 总览/持仓/行情/记账/问AI/功能"
    if key == "lang" and raw not in ("zh", "en"):
        return "lang must be zh or en" if en else "语言只能是 zh 或 en"
    if key in ("compact_numbers", "show_suggestions") and raw not in ("on", "off"):
        return f"{key} must be on or off" if en else f"{key} 只能是 on 或 off"
    if key in ("morning_report_time", "report_time"):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw):
            return "Morning report time must be HH:MM (24-hour)" if en else "晨报时间需为 HH:MM（24 小时制）"
        key = "report_time"  # 模型常用 morning_report_time 说法，统一落到真实键名
    try:
        await db.set_setting(key, raw)
    except Exception as exc:  # noqa: BLE001
        return f"Setting failed: {exc}" if en else f"设置失败：{exc}"
    await invalidate_quotes_cache()
    if key == "report_time":
        try:
            await scheduler.notify_settings_changed()
        except Exception:  # noqa: BLE001 — 重排失败不影响设置已保存
            pass
    if en:
        return f"Updated setting: {key} = {raw} (changes that need a restart were applied immediately)."
    return f"已更新设置：{key} = {raw}（下次启动生效的部分已即时应用）。"


async def tool_get_now(_args: dict[str, Any]) -> str:
    """返回当前日期与时间（服务器本地时区）。领域无关的通用工具。"""
    import datetime as _dt

    now = _dt.datetime.now()
    return f"现在是 {now.strftime('%Y-%m-%d %H:%M:%S')}（服务器本地时间）。"


def _load_ddgs() -> Any:
    """导入 duckduckgo_search 模块并立即恢复被其 import 副作用替换的事件循环策略。

    该包在 Windows 上 import 时执行 set_event_loop_policy(WindowsSelectorEventLoopPolicy)
    （见其 __init__.py），会把宿主（uvicorn / pytest-asyncio）正在用的 Proactor 循环变成
    孤儿（"unclosed event loop"）。我们只用它的同步 DDGS，不需要换策略。
    """
    prev_policy = asyncio.get_event_loop_policy()
    try:
        import duckduckgo_search
    finally:
        asyncio.set_event_loop_policy(prev_policy)
    return duckduckgo_search


async def tool_web_search(args: dict[str, Any]) -> str:
    """联网搜索（免 key，DuckDuckGo 即时答案 API）；失败返回明确提示，绝不抛错。

    供 general（非财务）分支使用：让「通用 agent」能回答最新新闻/时事等需要外部信息的问题。
    用 DuckDuckGo（而非旧版 Bing HTML 抓取）是因为其结构化 JSON 接口更稳定、不被反爬策略影响。
    """
    q = str((args or {}).get("q") or "").strip()
    if not q:
        return "缺少搜索关键词（q）。"
    # duckduckgo_search 同步调用在异步上下文：run_in_executor 避免阻塞事件循环
    try:
        DDGS = _load_ddgs().DDGS

        loop = asyncio.get_running_loop()

        def _search() -> list[dict[str, str]]:
            with DDGS() as ddgs:
                return [
                    {"title": r.get("title", ""), "snippet": r.get("body", "")}
                    for r in ddgs.text(q, region="wt-wt", safesearch="moderate", max_results=5)
                    if r.get("title")
                ]

        results = await loop.run_in_executor(None, _search)
    except Exception as exc:  # noqa: BLE001 — 联网失败必须兜底，绝不拖垮对话
        return f"联网搜索暂时不可用：{type(exc).__name__}。请稍后再试。"
    if not results:
        return f"未找到「{q}」的相关结果，换个说法再试试。"
    lines = [f"- {r['title']}" + (f"：{r['snippet']}" if r.get("snippet") else "") for r in results]
    return "搜索结果：\n" + "\n".join(lines)
