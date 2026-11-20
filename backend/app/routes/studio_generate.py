"""Studio 路由 · AI 生成域：按描述生成资产与落库应用。"""

from __future__ import annotations

from fastapi import APIRouter

from .. import llm
from ..studio import installer, store
from ._responses import fail as _err
from .studio_common import _require_admin

router = APIRouter()


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
