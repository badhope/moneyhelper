"""设置路由：GET/PUT /api/settings（原 main.py 设置域，M1.4 拆出）。"""

from __future__ import annotations

import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import analysis, db, llm, scheduler, vault
from ..quotes import invalidate_quotes_cache


def _mask_secret(settings: dict[str, str]) -> dict[str, str]:
    """对外返回时脱敏 AI Key：只回传"是否已配置"，绝不回传明文（与备份/导出策略一致）。"""
    if settings.get("ai_api_key"):
        settings["ai_api_key"] = "********"
    return settings


router = APIRouter()


NUMERIC_KEYS = (
    "monthly_income",
    "emergency_target_months",
    "savings_goal",
    "auto_refresh_seconds",
    "agent_tool_turns",
)
QUOTE_MODES = ("auto", "snapshot", "eastmoney")
COLOR_SCHEMES = ("cn", "us")
DEFAULT_TABS = ("overview", "holdings", "market", "ledger", "chat", "features")
ONOFF_KEYS = (
    "voice_input",
    "show_export",
    "expand_process",
    "show_suggestions",
    "auto_refresh",
    "compact_numbers",
    "ai_enabled",
    "agent_plan",
    "agent_reflect",
    "knowledge_enabled",
    "high_contrast",
)
# 适老化字号档位：只允许三档，避免任意值把布局撑坏
TEXT_SCALES = ("normal", "large", "xlarge")
# AI 配置：文本直存（key 仅存本机数据库）。
# 灵活化：base_url 允许留空走 OpenAI 默认；model 允许留空走模型默认；api_key 可含前缀（sk- 等）。
AI_TEXT_KEYS = ("ai_base_url", "ai_api_key", "ai_model")
# 付费/自由文本设置：直存（长度截断），如晨报关注要点（可 AI 生成）
FREE_TEXT_KEYS = ("report_focus", "custom_system_prompt")
# 模型点亮：逗号分隔的模型名白名单（P0 模型点亮），列表直存但做目录校验
MODEL_LIST_KEYS = ("enabled_models",)
AI_KEY_MAX_LEN = 2000
NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "monthly_income": (0, 1e12),
    "emergency_target_months": (0, 120),
    "savings_goal": (0, 100),
    "auto_refresh_seconds": (30, 86400),
    "agent_tool_turns": (1, 30),
}


@router.get("/api/settings")
async def get_settings() -> dict:
    settings = await db.get_settings()
    _mask_secret(settings)
    return {"settings": settings, "scheduler": scheduler.status()}


@router.put("/api/settings")
async def put_settings(payload: dict) -> dict:
    updates = (payload or {}).get("settings")
    if not isinstance(updates, dict) or not updates:
        return JSONResponse({"error": "settings 对象必填"}, status_code=400)

    applied: dict[str, str] = {}
    errors: list[str] = []
    for key, raw in updates.items():
        if key in NUMERIC_KEYS:
            try:
                v = float(raw)
                lo, hi = NUMERIC_RANGES[key]
                if v < lo or v > hi:
                    errors.append(f"{key} 需在 {lo:g}–{hi:g} 之间")
                    continue
                applied[key] = str(int(v)) if float(v).is_integer() else str(v)
            except (TypeError, ValueError):
                errors.append(f"{key} 的值不合法：{raw!r}")
        elif key in ONOFF_KEYS:
            if raw not in ("on", "off"):
                errors.append(f"{key} 只能是 on/off")
                continue
            applied[key] = raw
        elif key == "quote_source_mode":
            if raw not in QUOTE_MODES:
                errors.append(f"行情源只能是 {'/'.join(QUOTE_MODES)}")
                continue
            applied[key] = raw
        elif key == "color_scheme":
            if raw not in COLOR_SCHEMES:
                errors.append(f"涨跌颜色只能是 {'/'.join(COLOR_SCHEMES)}")
                continue
            applied[key] = raw
        elif key == "default_tab":
            if raw not in DEFAULT_TABS:
                errors.append(f"默认首页只能是 {'/'.join(DEFAULT_TABS)}")
                continue
            applied[key] = raw
        elif key == "text_scale":
            if raw not in TEXT_SCALES:
                errors.append(f"字号只能是 {'/'.join(TEXT_SCALES)}")
                continue
            applied[key] = raw
        elif key == "report_time":
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(raw).strip()):
                errors.append("晨报时间需为 HH:MM（24 小时制）")
                continue
            applied[key] = str(raw).strip()
        elif key == "essential_categories":
            cats = [c.strip() for c in str(raw).split(",") if c.strip()]
            if not cats:
                errors.append("必要支出类别不能为空")
                continue
            applied[key] = ",".join(cats)
        elif key == "custom_system_prompt":
            # 系统提示词通常几百字，单独给 4000 字上限（其他自由文本仍 200）
            applied[key] = str(raw).strip()[:4000]
        elif key in FREE_TEXT_KEYS:
            # 自由文本设置：去空白 + 长度截断（200 字），允许清空
            applied[key] = str(raw).strip()[:200]
        elif key in AI_TEXT_KEYS:
            v = str(raw).strip()
            # base_url：可留空（走 OpenAI 默认端点）；填了则必须 http(s)://
            if key == "ai_base_url" and v and not v.startswith(("http://", "https://")):
                errors.append(
                    "AI 接口地址需以 http:// 或 https:// 开头，或留空走默认端点"
                )
                continue
            # api_key：允许任意长度（不同供应商 key 长度差异大，最长 2000 字防误存）
            if key == "ai_api_key" and len(v) > AI_KEY_MAX_LEN:
                errors.append("API Key 过长（最多 2000 字）")
                continue
            # model：可留空（走模型默认）；不限制具体模型名
            # api_key：值为占位符（"********"，即前端未改动）或空串时跳过，保留已存原值
            if key == "ai_api_key":
                if v and v != "********":
                    # vault 加密后再落库；vault 未激活 → 拒绝加密存储
                    if vault.is_active():
                        try:
                            applied[key] = await vault.encrypt_secret(
                                v[:AI_KEY_MAX_LEN]
                            )
                        except Exception as e:
                            errors.append(f"API Key 加密失败：{e}")
                    else:
                        errors.append(
                            "VAULT_NOT_INITIALIZED：请先设置 VAULT_PASSPHRASE 环境变量再保存 API Key"
                        )
                # 空串/占位符 → 不写入 applied，保留原 key
            else:
                applied[key] = v
        elif key in MODEL_LIST_KEYS:
            # 模型点亮清单：只收目录内合法模型，非法项忽略（不报错、不写入）
            catalog = {m["model"] for m in llm.model_catalog()}
            if isinstance(raw, str) and raw.strip():
                items = [x.strip() for x in raw.split(",") if x.strip()]
                valid = [x for x in items if x in catalog]
                # 校验不过且一个都没写：报错让用户知道是模型名不合法
                if valid:
                    applied[key] = ",".join(valid)
                else:
                    errors.append(f"模型点亮清单里没有可用的模型：{raw!r}")
            elif isinstance(raw, list):
                valid = [x for x in raw if str(x).strip() in catalog]
                if valid:
                    applied[key] = ",".join(str(x).strip() for x in valid)
                else:
                    errors.append("模型点亮清单为空")
            else:
                applied[key] = ""
        else:
            errors.append(f"未知配置项：{key}")

    for k, v in applied.items():
        await db.set_setting(k, v)
    # 设置会进入仪表盘（月度收入/必要支出分类/字号等），必须让缓存立即失效
    analysis.invalidate_dashboard_cache()
    # AI 配置变化后使 llm 重新读取
    if any(
        k in applied for k in ("ai_enabled", "ai_base_url", "ai_api_key", "ai_model")
    ):
        llm.invalidate()
    if "quote_source_mode" in applied:
        await invalidate_quotes_cache()
    if "report_time" in applied:
        await scheduler.notify_settings_changed()
    return {
        "ok": True,
        "applied": applied,
        "errors": errors,
        "settings": _mask_secret(await db.get_settings()),
    }