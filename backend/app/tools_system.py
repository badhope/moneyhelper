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


def _so_search(q: str, max_results: int = 5) -> list[dict[str, str]]:
    """360 搜索兜底：Bing 对「人工智能 今日新闻」会切词成「人工」，返回百科词条，
    此时换 360 取新闻/资讯结果。返回 title/snippet/url，失败抛异常由调用方兜底。"""
    import html
    import re
    import urllib.parse
    import urllib.request

    url = "https://www.so.com/s?q=" + urllib.parse.quote(q)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310 — 固定 https 域名
        html_text = resp.read().decode("utf-8", "ignore")
    out: list[dict[str, str]] = []
    starts = [m.start() for m in re.finditer(r'<li class="res-list', html_text)]
    for i, start in enumerate(starts):
        block = html_text[start : starts[i + 1] if i + 1 < len(starts) else start + 3000]
        m = re.search(r'<h3[^>]*>.*?<a[^>]+href="([^"]+)"(.*?)>(.*?)</a>', block, flags=re.S)
        if not m:
            continue
        link, attrs, raw_title = m.group(1), m.group(2), m.group(3)
        md = re.search(r'data-mdurl="([^"]+)"', attrs)
        if md:
            link = md.group(1)
        title = html.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
        sn = re.search(r'<p class="res-desc"[^>]*>(.*?)</p>', block, flags=re.S)
        snippet = (
            html.unescape(re.sub(r"<[^>]+>", "", sn.group(1)))
            .replace("\xa0", " ")
            .strip(" ：")
            if sn
            else ""
        )
        if title and link.startswith("http"):
            out.append(
                {"title": title, "snippet": snippet, "url": html.unescape(link)}
            )
        if len(out) >= max_results:
            break
    return out


def _bing_search(q: str, max_results: int = 5) -> list[dict[str, str]]:
    """Bing 网页搜索兜底（cn.bing.com 国内可达）。返回 title/snippet/url，失败抛异常由调用方兜底。"""
    import html
    import re
    import urllib.parse
    import urllib.request

    url = "https://cn.bing.com/search?" + urllib.parse.urlencode(
        {"q": q, "setlang": "zh-Hans", "count": max_results}
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310 — 固定 https 域名
        html_text = resp.read().decode("utf-8", "ignore")
    out: list[dict[str, str]] = []
    for block in re.findall(r'<li class="b_algo".*?</li>', html_text, flags=re.S):
        m = re.search(r'<h2[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.S)
        if not m:
            continue
        link = html.unescape(m.group(1))
        title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        sn = re.search(r'<p[^>]*>(.*?)</p>', block, flags=re.S)
        snippet = (
            html.unescape(re.sub(r"<[^>]+>", "", sn.group(1)))
            .replace("\u2002", " ")
            .replace("阅读更多", "")
            .strip(" ：")
            if sn
            else ""
        )
        if title:
            out.append({"title": title, "snippet": snippet, "url": link})
        if len(out) >= max_results:
            break
    return out


async def tool_web_search(args: dict[str, Any]) -> str:
    """联网搜索（免 key，DuckDuckGo 即时答案 API）；失败返回明确提示，绝不抛错。

    供 general（非财务）分支使用：让「通用 agent」能回答最新新闻/时事等需要外部信息的问题。
    用 DuckDuckGo（而非旧版 Bing HTML 抓取）是因为其结构化 JSON 接口更稳定、不被反爬策略影响。
    """
    q = str((args or {}).get("q") or "").strip()
    if not q:
        return "缺少搜索关键词（q）。"
    # 国内环境优先 Bing（cn.bing.com 直连可达，通常 <2s）；DuckDuckGo 仅作兜底，
    # 因为它在国内经常 20s 超时或 BuilderError，先试它会把首字拖到 40s 以上。
    loop = asyncio.get_running_loop()
    results: list[dict[str, str]] = []
    try:
        results = await loop.run_in_executor(None, _bing_search, q)
    except Exception:  # noqa: BLE001 — 回退到免 key 的 DuckDuckGo
        results = []
    # Bing 的中文切词对「人工智能 今日新闻」会退化成「人工」，返回汉语词典词条；
    # 有新闻/时效意图且结果明显是辞书时，换 360 再取一次。
    news_intent = any(w in q for w in ("新闻", "最新", "今日", "消息", "动态", "热点"))
    junk = sum(1 for r in results if ("百科" in r["title"] or "汉典" in r["title"]))
    if news_intent and (not results or junk >= max(2, len(results) // 2)):
        # 「人工智能 今日新闻」在 Bing 会被切成「人工」；换成更稳的短词再试一次。
        alt_q = q.replace("人工智能", "AI").replace("今日", "").strip()
        if alt_q and alt_q != q:
            try:
                alt = await loop.run_in_executor(None, _bing_search, alt_q)
                if alt:
                    results = alt
            except Exception:  # noqa: BLE001 — 变体失败就继续用 360
                pass
    junk = sum(1 for r in results if ("百科" in r["title"] or "汉典" in r["title"]))
    if news_intent and (not results or junk >= max(2, len(results) // 2)):
        try:
            alt = await loop.run_in_executor(None, _so_search, q)
            if alt:
                results = alt
        except Exception:  # noqa: BLE001 — 360 不可用就保留已有结果
            pass
    if not results:
        try:
            DDGS = _load_ddgs().DDGS

            def _search() -> list[dict[str, str]]:
                with DDGS() as ddgs:
                    return [
                        {
                            "title": r.get("title", ""),
                            "snippet": r.get("body", ""),
                            "url": r.get("href", ""),
                        }
                        for r in ddgs.text(q, region="wt-wt", safesearch="moderate", max_results=5)
                        if r.get("title")
                    ]

            # DDGS 的同步实现没有统一 timeout，网络受限时可能挂很久；
            # 深研模式强制联网，必须给它封顶，否则整轮问答会一直停在“思考中”。
            results = await asyncio.wait_for(
                loop.run_in_executor(None, _search), timeout=10.0
            )
        except asyncio.TimeoutError:
            return "联网搜索超时（10 秒）。请稍后再试，或关闭深度研究先回答资料内的问题。"
        except Exception as exc:  # noqa: BLE001 — 联网失败必须兜底，绝不拖垮对话
            return f"联网搜索暂时不可用：{type(exc).__name__}。请稍后再试。"
    if not results:
        return f"未找到「{q}」的相关结果，换个说法再试试。"
    lines = [
        f"- {r['title']}"
        + (f"：{r['snippet']}" if r.get("snippet") else "")
        + (f"（{r['url']}）" if r.get("url") else "")
        for r in results
    ]
    return "搜索结果（请在回答中用这些链接标注来源）：\n" + "\n".join(lines)
