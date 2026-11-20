"""Studio 路由 · 只读域：总览、模板、格式规范。"""

from __future__ import annotations

from fastapi import APIRouter

from .. import agent_config
from ..studio import importer, installer, store
from ._responses import fail as _err

router = APIRouter()


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
