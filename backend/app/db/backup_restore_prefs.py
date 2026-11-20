"""备份恢复·偏好与会话域：MCP 服务器、用户偏好白名单、会话与问答历史。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import aiosqlite

from ._core import _ensure_defaults, _mark_user_data

# 备份恢复允许写回的 settings 键（用户偏好白名单）。
# 显式枚举而不是「排除 key」：新增的敏感键默认不会被旧备份意外写回。
_RESTORABLE_SETTING_KEYS = frozenset({
    "monthly_income",
    "emergency_target_months",
    "essential_categories",
    "quote_source_mode",
    "report_time",
    "report_focus",
    "voice_input",
    "voice_output",
    "text_scale",
    "high_contrast",
    "show_export",
    "expand_process",
    "show_suggestions",
    "auto_refresh",
    "auto_refresh_seconds",
    "compact_numbers",
    "color_scheme",
    "default_tab",
    "savings_goal",
    "enabled_models",
    "agent_tool_turns",
    "agent_plan",
    "agent_reflect",
    "knowledge_enabled",
    "ai_enabled",
    "data_note",
})


async def _restore_mcp_servers(data: dict[str, Any], counts: dict[str, int]) -> None:
    mcp_servers = data.get("mcp_servers")
    if isinstance(mcp_servers, list):
        try:
            from .. import mcp_client

            def _keep(entry: dict[str, Any]) -> dict[str, Any]:
                out = {
                    k: v
                    for k, v in entry.items()
                    if k in ("name", "url", "command", "args", "enabled")
                }
                env = entry.get("env")
                if isinstance(env, dict):
                    # 备份里的 *** 是打码占位，不能当真实密钥写回配置
                    real = {k: v for k, v in env.items() if v and v != "***"}
                    if real:
                        out["env"] = real
                # 恢复的 URL 同样要走 SSRF 校验：备份文件是可外部传入的输入，
                # 不能成为写入内网地址（169.254.x / 10.x）的通道。
                # 用 resolve=False：只做语法与字面 IP 检查，不依赖 DNS
                # （离线恢复不该因为解析失败丢掉整条配置）。
                if out.get("url"):
                    from urllib.parse import urlsplit, urlunsplit

                    from ..netguard import assert_public_http_url

                    raw_url = str(out["url"])
                    parts = urlsplit(raw_url)
                    if parts.username or parts.password:
                        # 备份里的是打码凭据 ***，本来也不能用；
                        # 去掉 userinfo 后由用户重新填写。
                        host = parts.hostname or ""
                        netloc = host + (f":{parts.port}" if parts.port else "")
                        raw_url = urlunsplit(
                            (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
                        )
                    try:
                        out["url"] = assert_public_http_url(raw_url, resolve=False)
                    except Exception as exc:  # noqa: BLE001 — 单条非法即跳过
                        raise ValueError(f"备份里的 MCP 地址不可用：{exc}") from exc
                return out

            kept: list[dict[str, Any]] = []
            for s in mcp_servers:
                if not isinstance(s, dict):
                    continue
                try:
                    kept.append(_keep(s))
                except ValueError:
                    continue
            clean = kept
            # stdio 配置等于本地命令执行；备份文件不应成为绕过 API 限制的入口。
            # 默认丢弃，只有部署者显式允许时才恢复。
            if not mcp_client.stdio_config_allowed():
                clean = [
                    s for s in clean if not str(s.get("command") or "").strip()
                ]
            mcp_client.save_servers(clean)
            counts["mcp_servers"] = len(clean)
        except Exception:  # noqa: BLE001 — MCP 恢复失败不阻断其余数据
            counts["mcp_servers"] = 0



async def _restore_settings(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    counts: dict[str, int],
    uid: str,
) -> None:
    settings = data.get("settings") or {}
    if isinstance(settings, dict):
        # 只覆盖「用户偏好」类键。行为配置（studio_config / agent_config /
        # custom_system_prompt / ai_base_url / ai_model）不能由备份文件写入：
        # 否则一个来源不明的备份就能把权限模式改回 open、注入提示词、
        # 把模型端点指向别处（历史漏洞 M-3）。
        # 注意不能整表 DELETE：那样会把未列入白名单的行为配置一并清空，
        # 反而把权限模式重置成默认值。只删/写白名单键。
        restorable = {
            k: v
            for k, v in settings.items()
            if k in _RESTORABLE_SETTING_KEYS
        }
        if restorable:
            placeholders = ",".join("?" for _ in restorable)
            await conn.execute(
                f"DELETE FROM settings WHERE user_id=? AND key IN ({placeholders})",
                (uid, *restorable.keys()),
            )
        # 密钥永不从备份恢复，且恢复动作清空本机已存密钥：
        # 备份可能来自另一台机器，保留旧 key 会让"恢复"带着来源不明的凭据运行。
        await conn.execute(
            "DELETE FROM settings WHERE user_id=? AND key='ai_api_key'", (uid,)
        )
        await conn.executemany(
            "INSERT OR IGNORE INTO settings(user_id,key,value) VALUES(?,?,?)",
            [(uid, k, str(v)) for k, v in restorable.items()],
        )
        await _ensure_defaults()
        await _mark_user_data(conn)
        counts["settings"] = len(restorable)
        skipped = len(settings) - len(restorable)
        if skipped:
            counts["settings_skipped"] = skipped



async def _restore_sessions_runs(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    counts: dict[str, int],
    uid: str,
) -> None:
    sessions = data.get("sessions") or []
    for s in sessions:
        if not isinstance(s, dict) or not s.get("thread_id"):
            continue
        await conn.execute(
            "INSERT OR IGNORE INTO sessions(user_id,thread_id,title,created_at,updated_at)"
            " VALUES(?,?,?,?,?)",
            (
                uid,
                s["thread_id"],
                str(s.get("title") or "新会话")[:40],
                s.get("created_at") or "",
                s.get("updated_at") or "",
            ),
        )
    counts["sessions"] = len(sessions)
    runs = data.get("runs") or []
    for r in runs:
        if not isinstance(r, dict) or not r.get("question"):
            continue
        await conn.execute(
            "INSERT INTO runs(user_id,thread_id,question,answer,level,flags_json,created_at,route,llm,route_reason,tools,actions)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uid,
                r.get("thread_id") or "default",
                str(r.get("question") or "")[:500],
                str(r.get("answer") or ""),
                str(r.get("level") or ""),
                json.dumps(r.get("flags") or [], ensure_ascii=False),
                r.get("created_at")
                or datetime.now().astimezone().isoformat(timespec="seconds"),
                str(r.get("route") or ""),
                str(r.get("llm") or ""),
                str(r.get("route_reason") or ""),
                json.dumps(r.get("tools") or [], ensure_ascii=False),
                json.dumps(r.get("actions") or [], ensure_ascii=False),
            ),
        )
    counts["runs"] = len(runs)
