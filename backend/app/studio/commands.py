"""对话内配置：用自然语言在对话里增删改 Studio 资产。

设计约束：
- 只在「全面放开」权限模式下允许，且必须由用户显式动词触发（添加/新建/删除/关闭/开启）。
- 解析是规则式的：只处理结构清晰的短指令，复杂需求引导到「一键生成」或设置页，
  不做猜测式写入（写错配置比不写更糟）。
- 每个动作都给出可核查回执：改了什么、id 是什么、去哪里看。
"""

from __future__ import annotations

import re
from typing import Any

from . import installer, store

_VERBS = ("添加", "新增", "新建", "创建", "加一个", "加个", "add", "create")
_REMOVE_VERBS = ("删除", "删掉", "移除", "remove", "delete")
_ENABLE_VERBS = ("启用", "开启", "打开", "enable")
_DISABLE_VERBS = ("禁用", "关闭", "停用", "disable")

_KIND_WORDS = (
    ("技能", "skills"),
    ("skill", "skills"),
    ("角色", "roles"),
    ("role", "roles"),
    ("agent", "roles"),
    ("提示词", "prompts"),
    ("prompt", "prompts"),
    ("约束", "rules"),
    ("规则", "rules"),
    ("rule", "rules"),
    ("hook", "hooks"),
    ("钩子", "hooks"),
)

_QUOTED = re.compile(r"[「“\"']([^」”\"']{1,120})[」”\"']")
_SEP = re.compile(r"[：:，,；;。]\s*")
_INSTALL_VERBS = ("安装", "install", "装一下", "装个")
_WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_TIME_RE = re.compile(r"(上午|下午|晚上|晚|早上|早|中午)?\s*(\d{1,2})\s*[点:：]\s*(\d{1,2})?")


def detect_kind(text: str) -> str | None:
    low = text.lower()
    for word, kind in _KIND_WORDS:
        if word in low:
            return kind
    return None


def _starts_with_any(text: str, words: tuple[str, ...]) -> bool:
    return any(text.startswith(w) for w in words)


def _extract(text: str, kind: str) -> dict[str, Any] | None:
    """从「添加技能 名称：描述」这类短句里提取名称与描述。"""
    quoted = _QUOTED.findall(text)
    body = text
    # 去掉动词与类型词，剩余部分作为名称/描述
    for v in _VERBS + _REMOVE_VERBS + _ENABLE_VERBS + _DISABLE_VERBS:
        body = body.replace(v, " ")
    for word, k in _KIND_WORDS:
        if k == kind:
            body = body.replace(word, " ")
    body = body.strip(" ：:，,；;。的")
    if quoted:
        name = quoted[0].strip()
        desc = quoted[1].strip() if len(quoted) > 1 else body.replace(name, "").strip(" ：:，,；;。")
    else:
        parts = [p.strip() for p in _SEP.split(body) if p.strip()]
        if not parts:
            return None
        name = parts[0][:40]
        desc = parts[1] if len(parts) > 1 else ""
    if not name:
        return None
    return {"name": name, "description": desc[:200]}


def parse_schedule(text: str) -> dict[str, Any] | None:
    """从「每周日晚 8 点」这类短句解析定时动作参数（只解析时间，不生成 prompt）。"""
    weekdays: list[int] = []
    for m in re.finditer(r"(?:周|星期|礼拜)([一二三四五六日天])", text):
        d = _WEEKDAY_MAP.get(m.group(1))
        if d is not None and d not in weekdays:
            weekdays.append(d)
    if "每天" in text or "每日" in text:
        weekdays = []
    m = _TIME_RE.search(text)
    if not m:
        if not weekdays and "每天" not in text and "每日" not in text:
            return None
        return {"time": "20:00", "weekdays": sorted(weekdays)}
    prefix, hh, mm = m.groups()
    hour = int(hh)
    minute = int(mm or 0)
    if prefix in ("下午", "晚上", "晚") and hour < 12:
        hour += 12
    if prefix == "中午" and hour < 11:
        hour += 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return {"time": f"{hour:02d}:{minute:02d}", "weekdays": sorted(weekdays)}


def _clean_schedule_tail(text: str) -> str:
    """去掉句子里的时间描述，避免把「每周日晚八点」写进技能名称/描述。"""
    out = re.sub(r"(?:每|逢)?(?:周|星期|礼拜)[一二三四五六日天]+", " ", text)
    out = re.sub(r"(?:每天|每日)", " ", out)
    out = re.sub(r"(上午|下午|晚上|晚|早上|早|中午)?\s*\d{1,2}\s*[点:：]\s*\d{0,2}\s*(?:分)?", " ", out)
    out = re.sub(r"(上午|下午|晚上|晚|早上|早|中午)", " ", out)
    return re.sub(r"\s{2,}", " ", out).strip(" ，,。；;：:")


def _common_substring(a: str, b: str) -> int:
    """最长公共子串长度（用于中文名称模糊匹配；空串或单字不算）。"""
    best = 0
    for i in range(len(a)):
        for j in range(i + 2, len(a) + 1):
            piece = a[i:j]
            if piece in b and j - i > best:
                best = j - i
    return best


def parse_market_intent(text: str) -> dict[str, Any] | None:
    """识别「安装 MCP 记忆」「安装技能 PDF 工具链」这类市场安装指令。"""
    low = text.lower()
    if not any(v in low for v in _INSTALL_VERBS):
        return None
    from . import market

    best: tuple[int, dict[str, Any]] | None = None
    wants_mcp = "mcp" in low or "插件" in text
    stripped = re.sub(r"(?i)mcp|插件|工具链|服务|安装|一下|一个", " ", text)
    for item in market.catalog():
        if wants_mcp and item["kind"] != "mcp":
            continue
        score = 0
        if item["id"].lower() in low:
            score = 100
        elif item["name"] in text:
            score = 90
        else:
            alias_hit = [a for a in (item.get("aliases") or []) if a.lower() in low]
            if alias_hit:
                score = 70 + max(len(a) for a in alias_hit)
            else:
                bare = re.sub(r"[（(].*?[）)]", "", item["name"])
                bare = re.sub(r"(?i)mcp|MCP|工具链|服务", "", bare).strip()
                common = _common_substring(bare, stripped) if bare else 0
                if common >= 2:
                    score = 40 + common * 5
        if score and (best is None or score > best[0]):
            best = (score, item)
    if best is None:
        return None
    return {"op": "market_install", "item_id": best[1]["id"], "item_name": best[1]["name"]}


def parse_intent(text: str) -> dict[str, Any] | None:
    """识别对话内配置意图。返回 None 表示不是配置指令。"""
    q = (text or "").strip()
    if len(q) > 300:
        return None
    low = q.lower()
    market_intent = parse_market_intent(q)
    if market_intent is not None:
        return market_intent
    kind = detect_kind(q)
    if kind is None:
        return None
    if _starts_with_any(q, _REMOVE_VERBS) or _starts_with_any(low, _REMOVE_VERBS):
        target = _QUOTED.findall(q)
        return {"op": "delete", "kind": kind, "target": target[0] if target else None}
    if _starts_with_any(q, _DISABLE_VERBS) or _starts_with_any(low, _DISABLE_VERBS):
        target = _QUOTED.findall(q)
        return {"op": "disable", "kind": kind, "target": target[0] if target else None}
    if _starts_with_any(q, _ENABLE_VERBS) or _starts_with_any(low, _ENABLE_VERBS):
        target = _QUOTED.findall(q)
        return {"op": "enable", "kind": kind, "target": target[0] if target else None}
    if _starts_with_any(q, _VERBS) or _starts_with_any(low, _VERBS):
        schedule = parse_schedule(q)
        cleaned = _clean_schedule_tail(q) if schedule else q
        fields = _extract(cleaned, kind)
        if not fields:
            return None
        intent = {"op": "create", "kind": kind, **fields}
        if schedule and kind == "skills":
            intent["action"] = {
                "prompt": fields.get("description") or fields.get("name") or "",
                **schedule,
            }
        return intent
    return None


def _template(kind: str, name: str, description: str) -> dict[str, Any]:
    base = installer.template_for(kind)
    base["name"] = name
    if description:
        base["description"] = description
    if kind == "prompts":
        base["content"] = description or base["content"]
    elif kind == "rules":
        base["content"] = description or base["content"]
    elif kind == "skills":
        base["content"] = description or base["content"]
    elif kind == "roles":
        base["instructions"] = description or base["instructions"]
    elif kind == "hooks":
        base["payload"] = description or base["payload"]
    return base


async def execute(intent: dict[str, Any], lang: str = "zh") -> dict[str, Any]:
    """执行配置意图，返回 {"ok", "answer", "asset"}。"""
    en = lang == "en"
    op = intent["op"]
    if op == "market_install":
        from . import installer as studio_installer

        try:
            result = await studio_installer.install_market(str(intent.get("item_id")))
        except ValueError as exc:
            return {"ok": False, "answer": f"安装失败：{exc}"}
        if intent.get("item_id", "").startswith("mcp-"):
            return {
                "ok": True,
                "answer": f"已安装 {intent.get('item_name')}（MCP 配置已写入，默认停用；请在「设置 → 插件（MCP）」启用后使用）。",
            }
        return {
            "ok": True,
            "answer": f"已安装市场条目「{intent.get('item_name')}」，可在「设置」对应分区查看。",
            "asset": result,
        }
    kind = intent["kind"]
    kind_label = {
        "skills": "技能",
        "roles": "角色",
        "prompts": "提示词",
        "rules": "约束",
        "hooks": "Hook",
    }[kind]
    if op == "create":
        asset = _template(kind, intent["name"], intent.get("description", ""))
        if kind == "skills" and intent.get("action"):
            asset["action"] = intent["action"]
        aid = store.new_id(kind[:-1])
        try:
            saved = await store.upsert_asset(kind, aid, asset)
        except Exception as exc:  # noqa: BLE001 — 写入失败如实回报
            return {
                "ok": False,
                "answer": f"创建失败：{exc}" if not en else f"Create failed: {exc}",
            }
        answer = (
            f"已创建{kind_label}「{saved.get('name')}」（id: {aid}），已默认启用。"
            f"可在「设置 → {kind_label}」中查看、编辑或删除；如需更完整的内容，点「一键生成」用一句话生成。"
        )
        return {"ok": True, "answer": answer, "asset": {"kind": kind, "id": aid, **saved}}
    target = intent.get("target")
    if not target:
        return {
            "ok": False,
            "answer": f"请用「」标出要操作的{kind_label}名称，例如：删除技能「定投提醒」",
        }
    assets = await store.list_assets(kind)
    hit = None
    for a in assets:
        if target in (str(a.get("name") or ""), str(a.get("id") or "")):
            hit = a
            break
    if hit is None:
        return {"ok": False, "answer": f"没有找到{kind_label}「{target}」，请先在设置页确认名称。"}
    if op == "delete":
        try:
            await store.delete_asset(kind, str(hit["id"]), force=False)
        except ValueError as exc:
            return {"ok": False, "answer": str(exc)}
        return {"ok": True, "answer": f"已删除{kind_label}「{hit.get('name')}」。"}
    enabled = op == "enable"
    updated = await store.set_enabled(kind, str(hit["id"]), enabled)
    if updated is None:
        return {"ok": False, "answer": f"{kind_label}「{target}」更新失败。"}
    return {
        "ok": True,
        "answer": f"已{'启用' if enabled else '停用'}{kind_label}「{hit.get('name')}」。",
        "asset": updated,
    }


async def handle_question(
    question: str, lang: str = "zh", channel: str = "chat"
) -> dict[str, Any] | None:
    """配置指令入口：命中意图且权限允许时执行；否则返回 None 走正常问答。

    channel="cli" 时按 CLI 权限判定（两个开关独立，避免 CLI 被 chat 开关误伤）。
    """
    intent = parse_intent(question)
    if intent is None:
        return None
    allowed = (
        await store.cli_admin_allowed() if channel == "cli" else await store.chat_admin_allowed()
    )
    if not allowed:
        return {
            "ok": False,
            "disabled": True,
            "answer": (
                "对话内修改配置需要「全面放开」权限模式，且「允许对话管理」为开。"
                "请到「设置 → 权限」调整后重试。"
            ),
            "route": "studio_admin",
        }
    result = await execute(intent, lang)
    result["route"] = "studio_admin"
    return result
