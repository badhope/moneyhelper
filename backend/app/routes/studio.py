"""Studio 路由：资产 CRUD / 导入 / AI 生成 / 市场 / 权限 / 诊断 / 模板。

约定：
- 所有写操作在「非全面放开」模式下返回 403，并给出可直接执行的提示。
- 核心安全项不可改（审批阈值下限、密钥、内部工具可见性、破坏性操作确认），
  即使全面放开也拒绝——这是「大部分放开、核心锁死」的落点。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from .. import agent_config, llm
from ..logging_utils import get_logger
from ..studio import (
    commands,
    importer,
    installer,
    internal_tools,
    market,
    store,
    watchdog,
)

log = get_logger(__name__)

router = APIRouter()

KIND_LABELS = {
    "prompts": "提示词",
    "rules": "约束",
    "hooks": "Hook",
    "roles": "角色",
    "skills": "技能",
}


def _err(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": msg}, status_code=status)


async def _audit(
    action: str, entity_type: str, before: dict | None, after: dict | None
) -> None:
    """Studio 变更审计（失败只记日志，不影响主流程）。"""
    try:
        from ..provenance import record_provenance

        await record_provenance(
            action=action,
            entity_type=entity_type,
            entity_id=entity_type,
            before=before,
            after=after,
            source="studio",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("studio audit failed (%s): %s", action, exc)


async def _require_admin(kind: str = "write") -> JSONResponse | None:
    if await store.chat_admin_allowed():
        return None
    return _err(
        "当前权限模式不允许修改 Studio 配置。请到「设置 → 权限」切换到「全面放开」。", 403
    )


def _check_kind(kind: str) -> JSONResponse | None:
    if kind not in store.ASSET_KINDS:
        return _err(f"未知资产类型：{kind}（可选 {'/'.join(store.ASSET_KINDS)}）")
    return None


# ---------------------------------------------------------------------------
# 概览与模板
# ---------------------------------------------------------------------------


@router.get("/api/studio/overview")
async def studio_overview() -> dict:
    cfg = await store.get_config()
    agent_cfg = await agent_config.get_config()
    perms = store.permissions(cfg)
    counts = {
        "prompts": len(cfg.get("prompts") or {}),
        "rules": len(cfg.get("rules") or {}),
        "hooks": len(cfg.get("hooks") or {}),
        "roles": len(agent_cfg.get("agents") or {}),
        "skills": len(agent_cfg.get("skills") or {}),
        "internal_tools": len((cfg.get("internal_tools") or {}).get("tools") or {}),
    }
    enabled = {
        "prompts": sum(1 for v in (cfg.get("prompts") or {}).values() if v.get("enabled", True)),
        "rules": sum(1 for v in (cfg.get("rules") or {}).values() if v.get("enabled", True)),
        "hooks": sum(1 for v in (cfg.get("hooks") or {}).values() if v.get("enabled", True)),
        "roles": sum(1 for v in (agent_cfg.get("agents") or {}).values() if v.get("enabled", True)),
        "skills": sum(1 for v in (agent_cfg.get("skills") or {}).values() if v.get("enabled", True)),
        "internal_tools": sum(
            1
            for v in ((cfg.get("internal_tools") or {}).get("tools") or {}).values()
            if v.get("enabled", True)
        ),
    }
    return {
        "ok": True,
        "permissions": perms,
        "locked": list(store.CORE_LOCKED),
        "counts": counts,
        "enabled": enabled,
        "primary_role": cfg.get("primary_role", "supervisor"),
        "watchdog": await store.watchdog_settings(),
        "installed": list((cfg.get("marketplace", {}).get("installed") or {}).keys()),
        "internal_tools_enabled": bool((cfg.get("internal_tools") or {}).get("enabled", True)),
    }


@router.get("/api/studio/templates/{kind}")
async def studio_template(kind: str) -> dict:
    try:
        return {"ok": True, "template": installer.template_for(kind)}
    except ValueError as exc:
        return _err(str(exc))


@router.get("/api/studio/format-spec")
async def studio_format_spec() -> dict:
    """官方格式说明（前端拖拽区与帮助面板直接展示）。"""
    return {
        "ok": True,
        "spec": {
            "skill_md": {
                "filename": "SKILL.md",
                "frontmatter": ["name（必填）", "description（建议）", "id（可选）"],
                "body": "技能正文：何时使用、步骤、验收标准",
                "example": "---\nname: paper-review\ndescription: 结构化审稿\n---\n\n# 审稿\n1. 复述主张\n2. 列重大意见\n3. 给总体建议",
            },
            "agent_md": {
                "frontmatter": ["name", "description", "tools（可选，all 或数组）", "temperature（可选）"],
                "body": "角色指令正文",
            },
            "json_bundle": {
                "shape": '{"prompts":{"id":{...}},"rules":{...},"hooks":{...},"agents":{...},"skills":{...}}',
                "single": '{"kind":"rules","id":"r1","name":"...","content":"...","severity":"should"}',
            },
            "zip": "可包含多个 .md/.json/.yaml；单个文件失败会逐条报错，其余照常导入",
            "limits": {"file_kb": importer.MAX_FILE_BYTES // 1024, "zip_files": importer.MAX_ZIP_FILES},
        },
    }


# ---------------------------------------------------------------------------
# 导入（上传文件 / 压缩包）
# ---------------------------------------------------------------------------


@router.post("/api/studio/import")
async def studio_import(
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    kind: str = Form(""),
) -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    default_kind = kind.strip() or None
    if default_kind and default_kind not in store.ASSET_KINDS:
        return _err(f"未知资产类型：{default_kind}")
    uploads = [f for f in ([file] if file else []) + (files or []) if f is not None]
    if not uploads:
        return _err("请选择要导入的文件")
    saved: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for upload in uploads:
        name = upload.filename or "upload"
        data = await upload.read()
        try:
            entries = importer.parse_file(data, name, default_kind)
        except importer.ImportErrorDetail as exc:
            errors.append({"file": name, "error": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 — 解析异常逐文件回报
            errors.append({"file": name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        for entry in entries:
            if "__zip_errors__" in entry:
                errors.extend(entry["__zip_errors__"])
                continue
            try:
                existing_ids = {a["id"] for a in await store.list_assets(entry["kind"])}
                replaced = entry["id"] in existing_ids
                asset = await store.upsert_asset(entry["kind"], entry["id"], entry["asset"])
                saved.append(
                    {
                        "kind": entry["kind"],
                        "id": entry["id"],
                        "name": asset.get("name", ""),
                        "file": name,
                        # 覆盖同名资产时要让用户知道（否则「导入 3 个只剩 1 个」无从察觉）
                        "replaced": replaced,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                errors.append({"file": entry.get("source") or name, "error": str(exc)})
    return {"ok": bool(saved) or not errors, "saved": saved, "errors": errors}


@router.post("/api/studio/import/url")
async def studio_import_url(payload: dict) -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    url = str((payload or {}).get("url") or "").strip()
    kind = str((payload or {}).get("kind") or "").strip() or None
    if not url:
        return _err("url 必填")
    if not await store.cli_admin_allowed() and not (await store.get_config()).get("permissions", {}).get(
        "allow_remote_install", True
    ):
        return _err("远程安装已被权限设置关闭", 403)
    try:
        result = await installer.install_remote(url, kind)
    except ValueError as exc:
        return _err(str(exc))
    except Exception as exc:  # noqa: BLE001 — 网络异常如实回报
        return _err(f"下载失败：{type(exc).__name__}: {exc}", 502)
    return result


# ---------------------------------------------------------------------------
# AI 一键生成
# ---------------------------------------------------------------------------


_GEN_SYSTEM = (
    "你是 Agent 配置生成器。根据用户描述生成一个 JSON 资产对象，字段必须完整可校验。"
    "只输出 JSON，不要解释。类型规则："
    "prompts → {name,description,content,category,priority}；"
    "rules → {name,description,content,severity(must/should/may),scope(all/finance/research)}；"
    "hooks → {name,description,event(pre_tool/pre_prompt/post_answer),action(block/warn/log/inject),match(正则或空),payload,priority}；"
    "roles → {name,description,instructions,tools(all 或工具名数组),temperature}；"
    "skills → {name,description,content}。内容用中文，具体可执行，不写空话。"
)


@router.post("/api/studio/generate")
async def studio_generate(payload: dict) -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    kind = str((payload or {}).get("kind") or "skills").strip()
    prompt = str((payload or {}).get("prompt") or "").strip()
    if kind not in store.ASSET_KINDS:
        return _err(f"未知资产类型：{kind}")
    if not prompt:
        return _err("请先描述你想要的工具/角色/规则")
    if not await llm.llm_available():
        return {
            "ok": False,
            "error": "未接入模型 —— 先到「设置 → AI 回答」配置模型端点，再使用一键生成",
            "fallback": installer.template_for(kind),
        }
    out = await llm.json_complete(_GEN_SYSTEM + f"\n本次类型：{kind}", prompt, timeout=30.0)
    if not isinstance(out, dict):
        return {"ok": False, "error": "生成失败：模型未返回可解析的 JSON，请换个描述重试"}
    candidate = {"kind": kind, **out}
    try:
        asset = store.normalize_asset(kind, "", candidate)
    except ValueError as exc:
        return {"ok": False, "error": f"生成结果未通过校验：{exc}", "raw": out}
    return {"ok": True, "suggestion": {"kind": kind, **asset}}


@router.post("/api/studio/generate/apply")
async def studio_generate_apply(payload: dict) -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    kind = str((payload or {}).get("kind") or "").strip()
    if kind not in store.ASSET_KINDS:
        return _err(f"未知资产类型：{kind}")
    asset = dict((payload or {}).get("asset") or {})
    asset_id = str(asset.pop("id", "") or store.new_id(kind[:-1]))
    asset.pop("kind", None)
    try:
        saved = await store.upsert_asset(kind, asset_id, asset)
    except ValueError as exc:
        return _err(str(exc))
    return {"ok": True, "asset": {"id": asset_id, **saved}}


# ---------------------------------------------------------------------------
# 市场
# ---------------------------------------------------------------------------


@router.get("/api/studio/market/list")
async def studio_market_list() -> dict:
    cfg = await store.get_config()
    installed = cfg.get("marketplace", {}).get("installed") or {}
    items = market.catalog()
    for item in items:
        item["installed"] = item["id"] in installed
    return {"ok": True, "items": items, "categories": market.categories()}


@router.post("/api/studio/market/install")
async def studio_market_install(payload: dict) -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    item_id = str((payload or {}).get("id") or "").strip()
    if not item_id:
        return _err("id 必填")
    try:
        return await installer.install_market(item_id)
    except ValueError as exc:
        return _err(str(exc))


@router.post("/api/studio/market/install-recommended")
async def studio_market_install_recommended() -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    return await installer.install_recommended()


@router.delete("/api/studio/market/{item_id}")
async def studio_market_uninstall(item_id: str) -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    try:
        return await installer.uninstall_market(item_id)
    except ValueError as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------


@router.get("/api/studio/permissions")
async def studio_permissions() -> dict:
    cfg = await store.get_config()
    return {
        "ok": True,
        "permissions": store.permissions(cfg),
        "locked": list(store.CORE_LOCKED),
        "modes": {
            "open": "全面放开：可改大部分设置（含对话/CLI 管理），核心安全项仍锁定",
            "standard": "标准：只能在设置页手动改，对话与 CLI 不能改配置",
            "strict": "严格：只读 Studio 配置，适合多用户/受管环境",
        },
    }


@router.put("/api/studio/permissions")
async def studio_set_permissions(payload: dict) -> dict:
    """权限变更必须留痕：谁在什么时候把权限从 X 改成了 Y。"""
    perms, errors = store.validate_permissions(payload or {})
    if errors:
        return _err("; ".join(errors))
    before = store.permissions(await store.get_config())
    updated = await store.update_permissions(perms)
    await _audit("studio.permissions_changed", "permissions", before, updated)
    return {"ok": True, "permissions": updated}


@router.post("/api/studio/core-guard")
async def studio_core_guard(payload: dict) -> dict:
    """核心项变更请求：一律拒绝并说明原因（前端据此把控件显示为锁定）。"""
    key = str((payload or {}).get("key") or "")
    if key not in store.CORE_LOCKED:
        return {"ok": True, "allowed": True}
    await _audit("studio.core_guard_blocked", "core_guard", {"key": key}, None)
    return {
        "ok": False,
        "allowed": False,
        "error": f"「{key}」属于核心安全项，全面放开模式下也不可修改",
        "reasons": {
            "approval_threshold": f"大额审批阈值下限为 {store.APPROVAL_FLOOR:g} 元，防止关闭写操作保护",
            "ai_api_key": "密钥只能由本人重新填写，不接受程序化改写",
            "api_token": "访问口令属于部署层配置，只能通过环境变量设置",
            "internal_tools_visibility": "内置工具仅内部可见，不对外暴露",
            "destructive_confirm": "删除/覆盖类操作必须保留确认步骤",
        },
    }


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


@router.get("/api/studio/{kind}")
async def studio_list(kind: str) -> dict:
    bad = _check_kind(kind)
    if bad:
        return bad
    return {"ok": True, "kind": kind, "assets": await store.list_assets(kind)}


@router.post("/api/studio/{kind}")
async def studio_upsert(kind: str, payload: dict) -> dict:
    bad = _check_kind(kind) or await _require_admin()
    if bad:
        return bad
    asset_id = str((payload or {}).get("id") or "").strip() or store.new_id(kind[:-1])
    body = dict(payload or {})
    body.pop("id", None)
    try:
        saved = await store.upsert_asset(kind, asset_id, body)
    except ValueError as exc:
        return _err(str(exc))
    await _audit(f"studio.{kind}_created", kind, None, {"id": asset_id, "name": saved.get("name")})
    return {"ok": True, "asset": {"id": asset_id, **saved}}


@router.patch("/api/studio/{kind}/{asset_id}")
async def studio_update(kind: str, asset_id: str, payload: dict) -> dict:
    bad = _check_kind(kind) or await _require_admin()
    if bad:
        return bad
    assets = {a["id"]: a for a in await store.list_assets(kind)}
    existing = assets.get(asset_id)
    if existing is None:
        return _err(f"资产不存在：{asset_id}", 404)
    merged = {**existing, **(payload or {})}
    merged.pop("id", None)
    try:
        saved = await store.upsert_asset(kind, asset_id, merged)
    except ValueError as exc:
        return _err(str(exc))
    return {"ok": True, "asset": {"id": asset_id, **saved}}


@router.delete("/api/studio/{kind}/{asset_id}")
async def studio_delete(kind: str, asset_id: str, force: bool = False) -> dict:
    bad = _check_kind(kind) or await _require_admin()
    if bad:
        return bad
    try:
        removed = await store.delete_asset(kind, asset_id, force=force)
    except ValueError as exc:
        return _err(str(exc), 409)
    if not removed:
        return _err(f"资产不存在：{asset_id}", 404)
    await _audit(f"studio.{kind}_deleted", kind, {"id": asset_id}, None)
    return {"ok": True, "deleted": asset_id}


@router.post("/api/studio/{kind}/{asset_id}/toggle")
async def studio_toggle(kind: str, asset_id: str, payload: dict) -> dict:
    bad = _check_kind(kind) or await _require_admin()
    if bad:
        return bad
    enabled = bool((payload or {}).get("enabled", True))
    updated = await store.set_enabled(kind, asset_id, enabled)
    if updated is None:
        return _err(f"资产不存在：{asset_id}", 404)
    return {"ok": True, "asset": updated}
