"""LiteLLM 统一模型接入——替掉自研 openai SDK 直连 + 手写路由 + 手动重试。

相比原 llm.py 自研方案：
- 统一接口：所有供应商（OpenAI / Anthropic / DeepSeek / Gemini / 豆包 / 通义）通过一个 completion() 调用
- 自动故障转移：主模型超时/报错 → 自动切备选模型（fallback_models）
- 内置重试：429/5xx/超时自动指数退避，无需手动配置
- 成本追踪：每次调用自动记 token 用量与费用（response._hidden_params["response_cost"]）
- DeepSeek thinking 流：自动解析 reasoning_content（thinking token 流）

原 llm.py 的 PROVIDERS / _sdk / stream_narrate / json_complete / stream_text_short
全部由本模块替代；对外保留 stream_narrate / json_complete / stream_text_short /
llm_available / invalidate 接口形态，调用方（agent_graph/service/agent）零改动。
"""

from __future__ import annotations

import os
from typing import Any

import litellm
from dotenv import load_dotenv

from .llm_routing import _detect_provider, _to_litellm_model
from .logging_utils import get_logger

_log = get_logger("llm")


# 提供给 lifespan 关闭时调用的清理函数（关闭持久 HTTP 连接、恢复全局状态）。
# LiteLLM 会用 aiohttp 维护连接池；不关会让进程退出时挂住（实测：脚本跑完后
# 卡在解释器退出，必须 kill）。这里显式关闭并清掉单例，下次启动重新建。
async def aclose() -> None:
    global _client_singleton, _client_singleton_cfg_key
    _client_singleton = None
    _client_singleton_cfg_key = None
    closer = getattr(litellm, "close_litellm_async_clients", None)
    if closer is None:
        return
    try:
        await closer()
    except Exception as exc:  # noqa: BLE001 — 关闭失败不该影响停机流程
        _log.debug("llm.aclose_failed: %s", exc)


load_dotenv()

# LiteLLM 日志噪声大（每次请求都打 INFO），压到 WARNING 以上
litellm.suppress_debug_info = True
litellm.set_verbose = False

# ---------------------------------------------------------------------------
# 配置源：设置中心（数据库）优先；环境变量兜底。
# 与旧 llm.py 的 _config() 同形态：返回 {key, base, model} 或 None。
# ---------------------------------------------------------------------------

# 按租户缓存模型配置：此前是进程级单例，多用户实例里第一个配置模型的人
# 会把自己的 Key/端点"借"给所有用户——费用算他的，用户 B 的财务问题被发往
# A 配置的第三方服务。缓存键 = current_user_id()，设置变更仍走 invalidate()。
_cfg_by_tenant: dict[int, dict[str, Any] | None] = {}

# 兼容别名：旧代码/测试直接读写 `llm._cfg`。它始终镜像「默认租户(0)」的槽，
# 因此 `llm._cfg = {...}` 等价于给默认租户注入配置——既保留旧语义，
# 又不会让多租户共享同一份 Key（真正的隔离在 _cfg_by_tenant）。
_cfg: dict[str, Any] | None = None


def _tenant_key() -> int:
    try:
        from .db.tenant import current_user_id

        return int(current_user_id() or 0)
    except Exception:  # noqa: BLE001 — 无租户上下文（CLI/测试）归默认租户
        return 0


# 供应商 prefix 映射（LiteLLM 用 "provider/model" 格式）


async def _config() -> dict[str, Any] | None:
    """读取模型配置：DB 优先，环境变量兜底。返回 None 表示未接入。"""
    tk = _tenant_key()
    cached = _cfg_by_tenant.get(tk)
    if tk == 0 and _cfg is not None:
        # 外部直接设置了 _cfg（测试/扩展）：视为默认租户的显式配置，优先采用
        return _cfg or None
    if cached is not None:
        return cached or None

    # 1) 设置中心（数据库）
    try:
        from . import db, vault

        s = await db.get_settings()
        base = (s.get("ai_base_url") or "").strip().rstrip("/")
        model = (s.get("ai_model") or "").strip()
        raw_key = (s.get("ai_api_key") or "").strip()
        key = ""
        if raw_key:
            if vault.is_active():
                try:
                    key = await vault.decrypt_secret(raw_key)
                except Exception as e:
                    _log.warning("vault decrypt failed: %s", e)
                    raise RuntimeError(
                        "API Key 解密失败 — 请检查 VAULT_PASSPHRASE 是否与加密时一致"
                    ) from e
            else:
                key = raw_key
        if s.get("ai_enabled") == "on" and key and model:
            provider = _detect_provider(model, base)
            _cfg_by_tenant[tk] = {
                "key": key,
                "model": model,
                "provider": provider,
                "base": base,
                "litellm_model": _to_litellm_model(model, provider, base),
            }
            return _cfg_by_tenant[tk]
    except Exception as e:
        # DB 读取失败（schema 损坏 / 磁盘满 / 加密字段不可解析）不应静默吞掉——
        # 区分"未接入模型"和"配置损坏无法定位"对排查至关重要
        _log.warning("llm._config() DB 读取失败（将尝试环境变量兜底）: %s", e)

    # 2) 环境变量兜底
    base = os.getenv("LLM_BASE_URL", "").strip().rstrip("/")
    key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    if key and model:
        provider = _detect_provider(model, base)
        _cfg_by_tenant[tk] = {
            "key": key,
            "model": model,
            "provider": provider,
            "base": base,
            "litellm_model": _to_litellm_model(model, provider, base),
        }
        return _cfg_by_tenant[tk]

    _cfg_by_tenant[tk] = {}  # 明确记录「本租户无配置」，避免反复查 DB
    return None




def invalidate() -> None:
    """设置中心修改 AI 配置后调用，使下次读取重新读取 DB（清空全部租户缓存）。"""
    global _cfg
    _cfg_by_tenant.clear()
    _cfg = None


async def llm_available() -> bool:
    return await _config() is not None


async def configured_model_name() -> str:
    """当前租户配置的模型名（未配置时返回空串）。用于评测/审计展示真实来源。"""
    cfg = await _config()
    return str((cfg or {}).get("model") or "").strip()


# ---------------------------------------------------------------------------
# 兼容接口（调用方 agent_graph / service / agent 零改动）
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# OpenAI 兼容客户端（供 agent.py / agent_graph.py 使用）
# 内部走 LiteLLM acompletion()：保留 OpenAI SDK 形态（.chat.completions.create），
# 但实际执行由 LiteLLM 承担（多模型路由 + 自动重试 + 故障转移）。
# ---------------------------------------------------------------------------










# 单例：配置不变时复用同一个 client 实例




# ---------------------------------------------------------------------------
# 新增：多模型路由信息（供设置页模型目录使用）
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# LiteLLM 薄封装（v2.0 新增路径）
# ---------------------------------------------------------------------------
# 旧路径（stream_narrate / json_complete / stream_text_short）继续走自写 OpenAI SDK 直连，
# 现有测试依赖它，本轮不动。Agent 与工具循环走 _CompatClient（LiteLLM 后端，
# 见本文件顶部 _CompatCompletions），由 LiteLLM 统一接 100+ 模型，故障转移/重试/
# 成本统计全是 LiteLLM 自带，不再自己写国产端点预设。




# 兼容客户端与模型目录已拆出；门面保持 llm._get_client / llm.model_catalog 可用
from .llm_catalog import (  # noqa: F401,E402
    _PROVIDER_PREFIX,
    default_enabled_models,
    model_catalog,
)
from .llm_client import (  # noqa: F401,E402
    _client_singleton,
    _client_singleton_cfg_key,
    _CompatChat,
    _CompatClient,
    _CompatCompletions,
    _get_client,
    _sdk,
    llm_timeout,
    llm_tool_limit,
)
from .llm_stream import (  # noqa: F401,E402 — 对外同名导出
    json_complete,
    litellm_chat,
    stream_narrate,
    stream_text_short,
)
