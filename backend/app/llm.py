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

import hashlib
import json
import os
import re
from collections.abc import AsyncIterator
from typing import Any

import litellm
from dotenv import load_dotenv

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

_cfg: dict[str, Any] | None = None

# 供应商 prefix 映射（LiteLLM 用 "provider/model" 格式）
_PROVIDER_PREFIX: dict[str, str] = {
    "openai": "openai",
    "deepseek": "deepseek",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "qwen": "openai",  # 通义千问 OpenAI 兼容 → 用 openai provider + 自定义 base_url
    "doubao": "openai",  # 豆包 OpenAI 兼容 → 用 openai provider + 自定义 base_url
}


async def _config() -> dict[str, Any] | None:
    """读取模型配置：DB 优先，环境变量兜底。返回 None 表示未接入。"""
    global _cfg
    if _cfg is not None:
        return _cfg or None

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
            _cfg = {
                "key": key,
                "model": model,
                "provider": provider,
                "base": base,
                "litellm_model": _to_litellm_model(model, provider, base),
            }
            return _cfg
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
        _cfg = {
            "key": key,
            "model": model,
            "provider": provider,
            "base": base,
            "litellm_model": _to_litellm_model(model, provider, base),
        }
        return _cfg

    _cfg = {}
    return None


def _detect_provider(model: str, base: str) -> str:
    """根据模型名 + base_url 推断供应商。"""
    m = model.lower()
    b = base.lower()
    if "deepseek" in m or "deepseek" in b:
        return "deepseek"
    if "claude" in m or "anthropic" in b:
        return "anthropic"
    if "gemini" in m or "google" in b or "generativelanguage" in b:
        return "gemini"
    if "qwen" in m or "dashscope" in b or "aliyun" in b:
        return "qwen"
    if "doubao" in m or "ark" in b or "volces" in b:
        return "doubao"
    return "openai"


def _to_litellm_model(model: str, provider: str, base: str) -> str:
    """构建设备 LiteLLM 的 model 字符串。
    - OpenAI 兼容端点（通义/豆包/DeepSeek）：用 "provider/model" 格式 + api_base
    - 官方端点：直接用 "provider/model"
    """
    if provider in ("qwen", "doubao"):
        # 这些走 OpenAI 兼容接口，但用自定义 base
        return f"openai/{model}"
    if provider == "deepseek":
        return f"deepseek/{model}"
    if provider == "anthropic":
        return f"anthropic/{model}"
    if provider == "gemini":
        return f"gemini/{model}"
    return f"openai/{model}"


def invalidate() -> None:
    """设置中心修改 AI 配置后调用，使下次读取重新读取 DB。"""
    global _cfg
    _cfg = None


async def llm_available() -> bool:
    return await _config() is not None


# ---------------------------------------------------------------------------
# 兼容接口（调用方 agent_graph / service / agent 零改动）
# ---------------------------------------------------------------------------


async def stream_narrate(
    system: str, user: str, fallback: str, usage_out: dict[str, int] | None = None
) -> AsyncIterator[tuple[str, str]]:
    """流式调用；失败或空流时整体退回模板。产出 (文本增量, 来源)。

    usage_out 传入一个可变 dict 时，成功路径把最后一次响应的
    prompt/completion tokens 写回（{"prompt": int, "completion": int}），
    供调用方按轮落库；失败/模板路径不写，调用方据此区分。
    """
    cfg = await _config()
    if cfg is None:
        yield fallback, "template"
        return

    # 主模型 + 备选模型（同 provider 的不同模型名；或不同 provider 的廉价模型）
    models = [cfg["litellm_model"]]
    # 自动追加 fallback：如果现有模型不是最廉价的，加一个廉价备选
    primary = cfg["model"].lower()
    if "gpt-4" in primary and "mini" not in primary:
        models.append("openai/gpt-4o-mini")
    elif "claude" in primary and "haiku" not in primary:
        models.append("anthropic/claude-3-5-haiku-latest")
    elif "deepseek" in primary:
        # DeepSeek 同 provider 无更廉价的，不加 fallback
        pass

    got_any = False
    last_err: Exception | None = None

    for model in models:
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "stream": True,
                "max_tokens": 2048,
                "num_retries": 2,  # LiteLLM 内置重试（429/5xx）
                # 单次请求超时用 timeout（秒）。旧代码写 retry_policy={"retry_timeout": 30}，
                # 而 litellm 的 RetryPolicy 实际字段是 XxxErrorRetries（次数），
                # retry_timeout 不是合法字段会被静默忽略 —— 等价于从未设置超时。
                "timeout": 30,
            }
            # api_base + api_key 对所有提供商统一传入（OpenAI 兼容端点都需要）
            kwargs["api_base"] = cfg.get("base") or None
            if cfg.get("key"):
                kwargs["api_key"] = cfg["key"]
            if cfg["provider"] == "doubao":
                kwargs["stream_timeout"] = 60

            response = await litellm.acompletion(**kwargs)

            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                # DeepSeek thinking 流：思考过程走 reasoning_content，
                # 正文走 content。思考内容以「思考」来源单列，供调用方决定是否展示，
                # 避免把它混进正文导致答案里出现推理草稿。
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    got_any = True
                    yield reasoning, "reasoning"
                text = getattr(delta, "content", None)
                if text:
                    got_any = True
                    yield text, "llm"

            # 读成本并回传给调用方（harness：按轮 token 计量的数据来源）
            try:
                usage = getattr(response, "usage", None)
                if usage is not None and usage_out is not None:
                    usage_out["prompt"] = int(getattr(usage, "prompt_tokens", 0) or 0)
                    usage_out["completion"] = int(getattr(usage, "completion_tokens", 0) or 0)
                cost = getattr(response, "_hidden_params", {}).get("response_cost")
                if cost is not None or usage is not None:
                    prompt_tk = getattr(usage, "prompt_tokens", 0) if usage else 0
                    compl_tk = getattr(usage, "completion_tokens", 0) if usage else 0
                    _log.info(
                        "litellm stream_narrate: model=%s prompt=%d compl=%d cost=$%.4f",
                        model,
                        prompt_tk,
                        compl_tk,
                        cost or 0.0,
                    )
            except Exception:
                pass

            return  # 成功了，不继续 fallback

        except Exception as e:
            last_err = e
            _log.warning("litellm stream_narrate failed (%s): %s", model, e)
            if not got_any:
                continue  # 还没拿到内容，试备选模型
            break  # 已经有内容了，不切备选

    # 全部失败
    if not got_any:
        if last_err:
            _log.warning("stream_narrate all models failed: %s", last_err)
        yield fallback, "template"


async def stream_text_short(user: str, timeout: float = 20.0) -> str | None:
    """非流式单次完成，返回纯文本。用于长会话摘要等场景。"""
    cfg = await _config()
    if cfg is None:
        return None
    try:
        kwargs: dict[str, Any] = {
            "model": cfg["litellm_model"],
            "messages": [
                {
                    "role": "system",
                    "content": "你是长会话压缩器，只输出一段简洁的中文摘要。",
                },
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "stream": False,
            "max_tokens": 512,
            "timeout": timeout,
            "num_retries": 2,
        }
        # api_base + api_key 对所有提供商统一传入
        kwargs["api_base"] = cfg.get("base") or None
        if cfg.get("key"):
            kwargs["api_key"] = cfg["key"]

        response = await litellm.acompletion(**kwargs)
        content = (response.choices[0].message.content or "").strip()
        return content or None
    except Exception as e:
        _log.warning("stream_text_short failed: %s", e)
        return None


async def json_complete(system: str, user: str, timeout: float = 20.0) -> dict | None:
    """非流式单次完成，期望返回 JSON 对象（结构化解析）。"""
    cfg = await _config()
    if cfg is None:
        return None
    try:
        kwargs: dict[str, Any] = {
            "model": cfg["litellm_model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "stream": False,
            "max_tokens": 1024,
            "timeout": timeout,
            "num_retries": 2,
        }
        # api_base + api_key 对所有提供商统一传入
        kwargs["api_base"] = cfg.get("base") or None
        if cfg.get("key"):
            kwargs["api_key"] = cfg["key"]

        response = await litellm.acompletion(**kwargs)
        content = response.choices[0].message.content or ""
    except Exception as e:
        _log.warning("json_complete failed: %s", e)
        return None

    m = re.search(r"\{[\s\S]*\}", content)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# OpenAI 兼容客户端（供 agent.py / agent_graph.py 使用）
# 内部走 LiteLLM acompletion()：保留 OpenAI SDK 形态（.chat.completions.create），
# 但实际执行由 LiteLLM 承担（多模型路由 + 自动重试 + 故障转移）。
# ---------------------------------------------------------------------------


class _CompatClient:
    """形态上兼容 openai.AsyncOpenAI，内部委托 LiteLLM。
    agent.py 的 run_agent() 直接 `await client.chat.completions.create(...)` 即可。

    注意：LiteLLM acompletion() 不是 100% 兼容 OpenAI SDK 的响应对象，
    但 agent.py 只用到了 resp.choices[0].message.tool_calls / .content，这两个字段
    LiteLLM 返回的对象都有（choices[0].message 是 ChatCompletionMessage 形态）。
    """

    def __init__(self, cfg: dict[str, Any], timeout: float = 60.0) -> None:
        self._cfg = cfg
        self._timeout = timeout
        self.chat = _CompatChat(cfg, timeout)


class _CompatChat:
    def __init__(self, cfg: dict[str, Any], timeout: float) -> None:
        self._cfg = cfg
        self._timeout = timeout
        self.completions = _CompatCompletions(cfg, timeout)


class _CompatCompletions:
    def __init__(self, cfg: dict[str, Any], timeout: float) -> None:
        self._cfg = cfg
        self._timeout = timeout

    async def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        """透传到 litellm.acompletion()，保持 OpenAI SDK 调用形态。"""
        cfg = self._cfg
        call_model = cfg["litellm_model"]
        call_model_arg = model or call_model
        if "/" not in call_model_arg:
            call_model_arg = (
                f"{_PROVIDER_PREFIX.get(cfg['provider'], 'openai')}/{call_model_arg}"
            )

        litellm_kwargs: dict[str, Any] = {
            "model": call_model_arg,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
            "timeout": self._timeout,
            "num_retries": 2,
        }
        if tools:
            litellm_kwargs["tools"] = tools
            litellm_kwargs["tool_choice"] = tool_choice
            # LiteLLM 1.106 在"带 tools"时会无条件导入它自己的 MCP 网关
            # （litellm.proxy._experimental.mcp_server），该模块引用 mcp>=2 才有的
            # CacheableResult；而本项目必须锁 mcp 1.30（fastmcp 2.x 要求 <2.0，
            # mcp 2.x 又会把 starlette 拉到 1.x 顶掉 fastapi 0.115）。
            # 两条依赖无法同时满足，因此显式跳过这条我们根本不用的分支——
            # 否则任何 function calling 调用都会 ImportError，工具链路整体失效。
            litellm_kwargs["_skip_mcp_handler"] = True
        if max_tokens:
            litellm_kwargs["max_tokens"] = max_tokens

        # api_base / api_key 对所有提供商统一传入（OpenAI 兼容端点都需要）
        litellm_kwargs["api_base"] = cfg.get("base") or None
        if cfg.get("key"):
            litellm_kwargs["api_key"] = cfg["key"]

        if stream:
            # 流式：返回 LiteLLM 的异步 chunk 迭代器
            # 每次迭代产出 OpenAI-compatible chunk: chunk.choices[0].delta.content
            return await litellm.acompletion(**litellm_kwargs)

        response = await litellm.acompletion(**litellm_kwargs)
        return response


def _sdk(cfg: dict[str, Any], timeout: float = 60.0) -> _CompatClient:
    """构造兼容客户端（供 agent.py 使用：保持 client.chat.completions.create(...) 调用形态）。"""
    return _CompatClient(cfg, timeout)


# 单例：配置不变时复用同一个 client 实例
_client_singleton: _CompatClient | None = None
_client_singleton_cfg_key: str | None = None


def _get_client(cfg: dict[str, Any], timeout: float = 60.0) -> _CompatClient:
    """获取/重建兼容 client（配置变更时重建）。

    指纹必须包含 api_key：用户在设置页换了密钥但模型名与端点没变时，
    旧逻辑会复用带旧 key 的客户端，表现为"改了 key 仍 401，重启才好"。
    只取 key 的哈希前 8 位参与指纹，避免把明文密钥留在内存字符串里到处传。
    """
    global _client_singleton, _client_singleton_cfg_key
    key_hash = hashlib.sha256(str(cfg.get("key") or "").encode()).hexdigest()[:8]
    key = f"{cfg['litellm_model']}:{cfg.get('base', '')}:{key_hash}:{timeout}"
    if _client_singleton is None or _client_singleton_cfg_key != key:
        _client_singleton = _sdk(cfg, timeout)
        _client_singleton_cfg_key = key
    return _client_singleton


# ---------------------------------------------------------------------------
# 新增：多模型路由信息（供设置页模型目录使用）
# ---------------------------------------------------------------------------


def model_catalog() -> list[dict[str, str]]:
    """返回模型目录（LiteLLM 支持的模型清单的精选子集）。
    含 OpenAI / Anthropic / DeepSeek / Google / 通义 五大供应商。
    """
    return [
        {
            "id": "gpt-4o-mini",
            "name": "GPT-4o mini",
            "provider": "OpenAI",
            "base": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        },
        {
            "id": "gpt-4o",
            "name": "GPT-4o",
            "provider": "OpenAI",
            "base": "https://api.openai.com/v1",
            "model": "gpt-4o",
        },
        {
            "id": "claude-3-5-sonnet-latest",
            "name": "Claude 3.5 Sonnet",
            "provider": "Anthropic",
            "base": "https://api.anthropic.com/v1",
            "model": "claude-3-5-sonnet-latest",
        },
        {
            "id": "claude-3-5-haiku-latest",
            "name": "Claude 3.5 Haiku（快速廉价）",
            "provider": "Anthropic",
            "base": "https://api.anthropic.com/v1",
            "model": "claude-3-5-haiku-latest",
        },
        {
            "id": "deepseek-chat",
            "name": "DeepSeek Chat",
            "provider": "DeepSeek",
            "base": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
        },
        {
            "id": "deepseek-reasoner",
            "name": "DeepSeek Reasoner（thinking）",
            "provider": "DeepSeek",
            "base": "https://api.deepseek.com/v1",
            "model": "deepseek-reasoner",
        },
        {
            "id": "gemini-2.0-flash",
            "name": "Gemini 2.0 Flash",
            "provider": "Google",
            "base": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model": "gemini-2.0-flash",
        },
        {
            "id": "qwen-plus",
            "name": "通义千问 Plus",
            "provider": "通义",
            "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-plus",
        },
        {
            "id": "qwen-max",
            "name": "通义千问 Max",
            "provider": "通义",
            "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-max",
        },
    ]


def default_enabled_models() -> list[str]:
    """默认点亮模型清单。"""
    return ["gpt-4o-mini", "deepseek-chat"]


def provider_presets() -> dict[str, dict[str, str]]:
    """供应商预设（供设置页使用）。"""
    return {
        "deepseek": {
            "name": "DeepSeek",
            "base": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
        },
        "doubao": {
            "name": "豆包",
            "base": "https://ark.cn-beijing.volces.com/api/v3",
            "model": "",
        },
        "qwen": {
            "name": "通义千问",
            "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-plus",
        },
        "openai": {
            "name": "OpenAI",
            "base": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        },
        "anthropic": {
            "name": "Anthropic",
            "base": "https://api.anthropic.com/v1",
            "model": "claude-3-5-sonnet-latest",
        },
        "gemini": {
            "name": "Google",
            "base": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model": "gemini-2.0-flash",
        },
    }


# ---------------------------------------------------------------------------
# LiteLLM 薄封装（v2.0 新增路径）
# ---------------------------------------------------------------------------
# 旧路径（stream_narrate / json_complete / stream_text_short）继续走自写 OpenAI SDK 直连，
# 现有测试依赖它，本轮不动。Agent 与工具循环走 _CompatClient（LiteLLM 后端，
# 见本文件顶部 _CompatCompletions），由 LiteLLM 统一接 100+ 模型，故障转移/重试/
# 成本统计全是 LiteLLM 自带，不再自己写国产端点预设。


async def litellm_chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    timeout: float = 60.0,
) -> str | None:
    """走 LiteLLM 的 chat completion。失败返回 None，由调用方降级。"""
    cfg = await _config()
    if not cfg:
        return None
    try:
        import litellm  # type: ignore

        litellm.suppress_debug_info = True
        m = model or cfg.get("model", "gpt-4o-mini")
        provider = _detect_provider(m, cfg.get("base", ""))
        litellm_model = _to_litellm_model(m, provider, cfg.get("base", ""))
        resp = await litellm.acompletion(
            model=litellm_model,
            messages=messages,
            temperature=temperature,
            timeout=timeout,
            api_base=cfg.get("base") or None,
            api_key=cfg.get("key") or None,
        )
        return resp.choices[0].message.content
    except Exception as e:  # pragma: no cover - 降级路径
        from .logging_utils import get_logger

        get_logger(__name__).warning("litellm.chat_failed", error=str(e))
        return None
