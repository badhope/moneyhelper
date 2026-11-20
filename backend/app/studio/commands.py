"""对话内配置：用自然语言在对话里增删改 Studio 资产。

解析在 `commands_parse.py`（`detect_kind` / `parse_intent` / 日程与行情意图），
本文件保留空白模板、执行与问答入口。设计约束：只在「全面放开」权限模式下允许，
且必须由用户显式动词触发；每个动作都给出可核查回执。
"""

from __future__ import annotations

from typing import Any

from . import installer, store
from .commands_parse import (  # noqa: F401 — 对外同名导出
    _KIND_WORDS,
    _REMOVE_VERBS,
    _VERBS,
    detect_kind,
    parse_intent,
    parse_market_intent,
    parse_schedule,
)


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
    try:
        updated = await store.set_enabled(kind, str(hit["id"]), enabled)
    except PermissionError as exc:
        return {"ok": False, "answer": str(exc)}
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
