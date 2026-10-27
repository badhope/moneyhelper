"""Agent 配置：角色 / skills / 工具开关；技能立即触发；AI 一键生成。

从 routes/system.py 拆出（M1.4 收尾）：原文件把 9 个互不相关的域塞在一起，
任何一个域的改动都要在 500+ 行里定位。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..logging_utils import get_logger as _get_logger

log = _get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Agent 配置：角色 / skills / 工具开关
# ---------------------------------------------------------------------------


@router.get("/api/agent-config")
async def get_agent_config() -> dict:
    """读当前 agent 配置（角色/skills/工具）。"""
    from .. import agent_config

    cfg = await agent_config.get_config()
    return {"ok": True, "config": cfg}


@router.post("/api/agent-config")
async def update_agent_config(payload: dict) -> dict:
    """更新 agent 配置。

    保存时：非法定时动作剔除并回报 warnings；随后同步技能调度任务
    （同步失败不影响保存本身——保存是数据、排程是运行时，各自独立可恢复）。
    """
    from .. import agent_config
    from .. import scheduler as sched_mod

    new_cfg = payload.get("config", payload)
    clean, warnings = agent_config.clean_config(new_cfg)
    # 审批阈值下限：核心安全项不能被配置层绕过（与 approval.threshold() 的钳制同口径）
    defaults = clean.setdefault("defaults", {})
    try:
        raw_threshold = float(defaults.get("approval_threshold", 5000))
    except (TypeError, ValueError):
        raw_threshold = 5000.0
    if raw_threshold < 100:
        defaults["approval_threshold"] = 100
        warnings.append("大额审批阈值不能低于 100 元（核心安全项），已按 100 元保存")
    await agent_config.update_config(clean)
    try:
        await sched_mod.sync_skill_jobs()
    except Exception as exc:  # noqa: BLE001 — 排程失败只告警：下次保存/重启会重试
        log.warning("skill jobs sync failed after save: %s", exc)
    return {"ok": True, "warnings": warnings}


@router.post("/api/skills/{skill_id}/run")
async def run_skill_now(skill_id: str) -> dict:
    """立即触发一次技能动作（与定时触发同一实现）：走问答管线并归档，不进会话列表。"""
    from .. import scheduler as sched_mod

    try:
        return await sched_mod.run_skill_action(skill_id)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001 — 管线异常如实回报，不冒充成功
        log.exception("skill run failed: %s", exc)
        return JSONResponse({"ok": False, "error": f"执行失败：{exc}"}, status_code=500)


@router.post("/api/agent-config/generate")
async def generate_agent_config(payload: dict) -> dict:
    """AI 一键生成：按自然语言描述生成 skill / 角色描述（设置页「AI 生成」按钮）。

    只产出建议不落库，由用户在设置页确认后随既有保存流程写入。
    未接入模型或模型输出不可用 → 200 + {"ok": false, "error": ...}（fail-closed）。
    """
    from .. import agent_config
    from .. import llm as llm_mod

    kind = str((payload or {}).get("kind") or "skill").strip()
    prompt = str((payload or {}).get("prompt") or "").strip()
    agent_name = str((payload or {}).get("agent") or "").strip()
    if not prompt:
        return {"ok": False, "error": "请先描述你想要的效果"}
    if not await llm_mod.llm_available():
        return {
            "ok": False,
            "error": "未接入模型 —— 先到「设置 → AI 回答」配置模型端点",
        }
    suggestion = await agent_config.generate_suggestion(kind, prompt, agent_name)
    if suggestion is None:
        return {"ok": False, "error": "生成失败，请换个描述再试"}
    return {"ok": True, "suggestion": suggestion}


# ---------------------------------------------------------------------------
# MCP 服务器（外部插件）管理
# ---------------------------------------------------------------------------


@router.get("/api/mcp/servers")
async def list_mcp_servers() -> dict:
    """当前配置的 MCP 服务器 + 已发现工具数。

    凭据打码：URL 里的 user:token 会替换成 ***，避免在设置页明文回显。
    """
    from .. import mcp_client

    return {
        "servers": mcp_client.list_servers(),
        "discovery_failures": mcp_client.failure_status(),
    }


@router.put("/api/mcp/servers")
async def put_mcp_servers(payload: dict) -> dict:
    """保存 MCP 服务器列表。保存后立即尝试发现工具，失败只回报不阻断。"""
    from .. import mcp_client

    servers = payload.get("servers")
    if not isinstance(servers, list):
        return JSONResponse({"error": "servers 必须是数组"}, status_code=400)
    try:
        mcp_client.save_servers(servers)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    try:
        tools = await mcp_client.refresh(force=True)
    except Exception:  # noqa: BLE001 — 发现失败不影响保存
        tools = []
    return {"ok": True, "servers": mcp_client.list_servers(), "tool_count": len(tools)}


@router.post("/api/mcp/test")
async def test_mcp_server(payload: dict) -> dict:
    """测试单台服务器连通性：握手 + list_tools，返回工具名列表。

    http：传 url；stdio：传 command + args（本地拉起进程后握手）。
    """
    from .. import mcp_client

    url = str(payload.get("url") or "").strip()
    command = str(payload.get("command") or "").strip()
    args = payload.get("args") or []
    if not url and not command:
        return JSONResponse({"error": "请提供 url（http）或 command（stdio）"}, status_code=400)
    if url and not url.lower().startswith(("http://", "https://")):
        return JSONResponse({"error": "地址必须以 http:// 或 https:// 开头"}, status_code=400)
    if command and not isinstance(args, list):
        return JSONResponse({"error": "args 必须是数组"}, status_code=400)
    try:
        tools = await mcp_client.probe(url, command, [str(a) for a in args])
    except Exception as exc:  # noqa: BLE001 — 测试失败是预期结果，透出原因
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=400)
    return {"ok": True, "tools": tools}


@router.post("/api/mcp/servers/bulk-toggle")
async def bulk_toggle_mcp(payload: dict) -> dict:
    """批量启用/停用（「一键启用全部」/「全部停用」）。"""
    from .. import mcp_client

    enabled = bool((payload or {}).get("enabled", True))
    servers = mcp_client.raw_servers()
    if not servers:
        return {"ok": True, "servers": []}
    for s in servers:
        s["enabled"] = enabled
    try:
        cleaned = mcp_client.save_servers(servers)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"ok": True, "servers": mcp_client.list_servers(), "count": len(cleaned)}


@router.post("/api/mcp/servers/{name}/toggle")
async def toggle_mcp_server(name: str, payload: dict) -> dict:
    """启用/停用某台 MCP 服务器（保留配置，不参与发现）。"""
    from .. import mcp_client

    enabled = bool((payload or {}).get("enabled", True))
    try:
        servers = mcp_client.set_server_enabled(name, enabled)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return {"ok": True, "servers": servers}
