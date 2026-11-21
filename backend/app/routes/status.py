"""健康检查与指标：/api/health、/api/metrics、/api/bootstrap、模型目录。

从 routes/system.py 拆出（M1.4 收尾）：原文件把 9 个互不相关的域塞在一起，
任何一个域的改动都要在 500+ 行里定位。
"""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import db, llm, scheduler
from ..auth_guard import require_instance_admin
from ..middleware import metrics_body
from .settings import _mask_secret

router = APIRouter()


# ---------------------------------------------------------------------------
# 健康 / 指标
# ---------------------------------------------------------------------------


async def _llm_model() -> str:
    try:
        s = await db.get_settings()
        return (s.get("ai_model") or "").strip() or os.getenv("LLM_MODEL", "")
    except Exception:  # noqa: BLE001
        return os.getenv("LLM_MODEL", "")


@router.get("/api/health")
async def health() -> dict:
    # auth_mode 让前端能明确告诉用户"这个实例到底要不要口令"。
    # 此前设置页只能写"后端同时设置 API_TOKEN 才生效"，用户无从判断是否已生效。
    import os

    from .. import db

    token_required = bool(os.getenv("API_TOKEN", "").strip())
    try:
        has_users = await db.user_count() > 0
    except Exception:  # noqa: BLE001 — 健康检查不因统计失败而失败
        has_users = False
    return {
        "ok": True,
        "llm_configured": await llm.llm_available(),
        "model": await _llm_model(),
        "auth_mode": "token" if token_required else ("accounts" if has_users else "local"),
    }


@router.get("/api/metrics")
async def metrics():
    return metrics_body()


# ---------------------------------------------------------------------------
# 引导（bootstrap）与模型目录
# ---------------------------------------------------------------------------


def _enabled_model_list(settings: dict[str, str]) -> list[str]:
    """把设置里的逗号分隔模型串解析成列表（只留目录内合法项，供前端用）。"""
    raw = str(settings.get("enabled_models") or "").strip()
    if not raw:
        return llm.default_enabled_models()
    catalog = {m["model"] for m in llm.model_catalog()}
    return [x for x in (s.strip() for s in raw.split(",")) if x and x in catalog]


@router.get("/api/bootstrap")
async def bootstrap() -> dict:
    settings = await db.get_settings()
    _mask_secret(settings)
    return {
        "settings": settings,
        "scheduler": scheduler.status(),
        "health": {
            "llm_configured": await llm.llm_available(),
            "model": await _llm_model(),
        },
        # 模型点亮（P0）：目录 + 已点亮清单，前端据此渲染输入区快捷切换与设置页勾选
        "model_catalog": llm.model_catalog(),
        "enabled_models": _enabled_model_list(settings),
    }



class _ModelProbeReq(BaseModel):
    base_url: str
    api_key: str = ""


@router.post("/api/models/probe")
async def probe_models(
    req: _ModelProbeReq,
    _admin: dict = Depends(require_instance_admin),
) -> dict:
    """按用户填的 base_url + key 现场拉一次 /models，供设置页下拉选择。

    只返回模型 id 与归属方，不回显 key、不落日志。key 为空时回落到
    进程环境里的 LLM_API_KEY（部署者已配好的场景）。
    """
    base = (req.base_url or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        return {"ok": False, "error": "base_url 必须以 http:// 或 https:// 开头", "models": []}
    key = (req.api_key or "").strip() or os.getenv("LLM_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{base}/models", headers=headers)
    except Exception as exc:  # noqa: BLE001 — 网络错误统一回报，不抛 5xx
        return {"ok": False, "error": f"连接失败：{type(exc).__name__}", "models": []}
    if r.status_code != 200:
        return {"ok": False, "error": f"端点返回 HTTP {r.status_code}", "models": []}
    try:
        payload = r.json()
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "返回内容不是 JSON", "models": []}
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {"ok": False, "error": "返回结构里没有 data 数组", "models": []}
    models = [
        {
            "id": str(m.get("id") or "").strip(),
            "owned_by": str(m.get("owned_by") or "").strip(),
        }
        for m in rows
        if isinstance(m, dict) and str(m.get("id") or "").strip()
    ]
    return {"ok": True, "count": len(models), "models": models}
