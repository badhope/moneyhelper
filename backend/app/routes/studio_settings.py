"""Studio 设置：看门狗、内置工具、诊断、主角色与命令。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .. import agent_config, llm
from ..logging_utils import get_logger
from ..studio import (
    commands,
    internal_tools,
    store,
    watchdog,
)
from ._responses import fail as _err
from .studio import _require_admin

log = get_logger(__name__)

router = APIRouter()

@router.post("/api/studio/watchdog")
async def studio_watchdog_config(payload: dict) -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    enabled = (payload or {}).get("enabled")
    interval = (payload or {}).get("interval_minutes")
    out = await store.set_watchdog(
        enabled=enabled if isinstance(enabled, bool) else None,
        interval_minutes=int(interval) if interval is not None else None,
    )
    if out.get("enabled") and not watchdog.status()["running"]:
        await watchdog.start()
    elif not out.get("enabled"):
        await watchdog.stop()
    return {"ok": True, "watchdog": out, "status": watchdog.status()}


@router.get("/api/studio/watchdog")
async def studio_watchdog_status() -> dict:
    return {"ok": True, "status": watchdog.status(), "settings": await store.watchdog_settings()}


@router.post("/api/studio/watchdog/run")
async def studio_watchdog_run() -> dict:
    return await watchdog.run_check()


# ---------------------------------------------------------------------------
# 内置工具 / 主角色 / 诊断
# ---------------------------------------------------------------------------


@router.get("/api/studio/internal-tools")
async def studio_internal_tools() -> dict:
    cfg = await store.get_config()
    tools = (cfg.get("internal_tools") or {}).get("tools") or {}
    spec = internal_tools.INTERNAL_TOOL_SPECS
    return {
        "ok": True,
        "enabled": bool((cfg.get("internal_tools") or {}).get("enabled", True)),
        "tools": [
            {
                "id": tid,
                "name": (tools.get(tid) or {}).get("name") or tid,
                "description": (tools.get(tid) or {}).get("description")
                or (spec.get(tid) or {}).get("description", ""),
                "enabled": bool((tools.get(tid) or {}).get("enabled", True)),
                "builtin": True,
            }
            for tid in spec
        ],
        "visibility": "internal",
        "note": "内置工具只在应用内部工具面可用，不会出现在 MCP Server 的对外工具清单中。",
    }


@router.post("/api/studio/internal-tools/toggle")
async def studio_internal_toggle(payload: dict) -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    tid = str((payload or {}).get("id") or "").strip()
    if tid == "__all__":
        out = await store.set_internal_tools_enabled(bool((payload or {}).get("enabled", True)))
        return {"ok": True, **out}
    if tid not in internal_tools.INTERNAL_TOOL_SPECS:
        return _err(f"内置工具不存在：{tid}", 404)
    updated = await store.set_internal_tool(tid, bool((payload or {}).get("enabled", True)))
    return {"ok": True, "tool": updated}


@router.get("/api/studio/diagnostics")
async def studio_diagnostics() -> dict:
    """一键自检：逐项给出真实结果（不返回"应该没问题"）。"""
    checks: list[dict[str, Any]] = []
    cfg = await store.get_config()
    agent_cfg = await agent_config.get_config()
    prompts_on = sum(1 for v in (cfg.get("prompts") or {}).values() if v.get("enabled", True))
    checks.append(
        {
            "id": "default_pack",
            "label": "默认配置非空",
            "ok": prompts_on > 0 and bool(agent_cfg.get("agents")) and bool(agent_cfg.get("skills")),
            "detail": f"提示词启用 {prompts_on} / 角色 {len(agent_cfg.get('agents') or {})} / 技能 {len(agent_cfg.get('skills') or {})}",
        }
    )
    checks.append(
        {
            "id": "permission_mode",
            "label": "权限模式",
            "ok": store.permissions(cfg).get("mode") in store.PERMISSION_MODES,
            "detail": f"当前：{store.permissions(cfg).get('mode')}，核心锁定项 {len(store.CORE_LOCKED)} 个",
        }
    )
    from .. import mcp_client

    mcp_servers = mcp_client.list_servers()
    checks.append(
        {
            "id": "mcp_config",
            "label": "MCP 配置可解析",
            "ok": True,
            "detail": f"已配置 {len(mcp_servers)} 台，启用 {sum(1 for s in mcp_servers if s.get('enabled', True))} 台",
        }
    )
    checks.append(
        {
            "id": "llm",
            "label": "模型端点",
            "ok": await llm.llm_available(),
            "detail": "已配置可用端点" if await llm.llm_available() else "未接入模型：AI 生成与自定义技能注入将降级",
        }
    )
    wd = await watchdog.run_check(advance_state=False)
    checks.append(
        {
            "id": "runtime",
            "label": "运行时检查",
            "ok": not any(f["level"] == "error" for f in wd["findings"]),
            "detail": "；".join(f["message"] for f in wd["findings"]) or "未发现异常",
        }
    )
    checks.append(
        {
            "id": "studio_assets",
            "label": "资产可读写",
            "ok": True,
            "detail": f"约束 {len(cfg.get('rules') or {})} / Hook {len(cfg.get('hooks') or {})} / 市场安装 {len(cfg.get('marketplace', {}).get('installed') or {})}",
        }
    )
    return {"ok": all(c["ok"] for c in checks if c["id"] != "llm"), "checks": checks}


# ---------------------------------------------------------------------------
# 主角色 / 对话内配置说明
# ---------------------------------------------------------------------------


@router.post("/api/studio/primary-role")
async def studio_primary_role(payload: dict) -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    role_id = str((payload or {}).get("role_id") or "").strip()
    try:
        return {"ok": True, **await store.set_primary_role(role_id)}
    except ValueError as exc:
        return _err(str(exc))


@router.get("/api/studio/commands")
async def studio_commands() -> dict:
    return {
        "ok": True,
        "examples": [
            "添加技能 定投提醒：每周日检查定投计划",
            "添加约束 不推荐个股：只描述风险，不给买卖建议",
            "添加提示词 简洁模式：回答不超过三句话",
            "添加 Hook 拦截删除：阻止 delete 类工具",
            "停用技能「长期记忆」",
            "删除约束「不推荐个股」",
        ],
        "note": "以上指令需要「全面放开」权限模式；也可在设置页用模板 / 拖拽 / AI 生成。",
    }


@router.post("/api/studio/chat-command")
async def studio_chat_command(payload: dict) -> dict:
    """给前端/CLI 直接调用对话式配置（与聊天内解析同一实现）。"""
    text = str((payload or {}).get("text") or "").strip()
    lang = str((payload or {}).get("lang") or "zh")
    if not text:
        return _err("text 必填")
    result = await commands.handle_question(text, lang)
    if result is None:
        return {"ok": False, "matched": False, "error": "不是可识别的配置指令"}
    result["matched"] = True
    return result


# ---------------------------------------------------------------------------
# 资产 CRUD（注册顺序必须在所有静态路径之后：/api/studio/{kind} 会吃掉
# /api/studio/diagnostics、/api/studio/import 等同级静态路由）
# ---------------------------------------------------------------------------

