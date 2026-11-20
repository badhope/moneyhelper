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
    importer,
    installer,
    store,
)
from ._responses import fail as _err

log = get_logger(__name__)

router = APIRouter()

KIND_LABELS = {
    "prompts": "提示词",
    "rules": "约束",
    "hooks": "Hook",
    "roles": "角色",
    "skills": "技能",
}




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
    # SSRF 防护：这是管理员接口，但管理员也不该被诱导去读取内网/云 metadata
    from ..netguard import SSRFBlocked, assert_public_http_url

    try:
        url = assert_public_http_url(url)
    except SSRFBlocked as exc:
        return _err(str(exc))
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


# 子路由按「市场 → 权限 → 设置 → 资产」顺序挂载，且资产放在最后：
# /api/studio/{kind} 会遮蔽同级静态路径，注册顺序不能变。
from .studio_assets import router as assets_router  # noqa: E402
from .studio_market import router as market_router  # noqa: E402
from .studio_permissions import router as perms_router  # noqa: E402
from .studio_settings import router as settings_router  # noqa: E402

router.include_router(market_router)
router.include_router(perms_router)
router.include_router(settings_router)
router.include_router(assets_router)
