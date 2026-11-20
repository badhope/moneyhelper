"""LiteLLM 兼容客户端：把 acompletion 包装成 openai SDK 形态，供 agent 复用。

从 llm.py 拆出。client 单例按「模型+端点+密钥哈希+超时」做指纹，
换 key 必须重建，否则表现为"改了 key 仍 401，重启才好"。
"""

from __future__ import annotations

import hashlib
from typing import Any

import litellm

from .llm_catalog import _PROVIDER_PREFIX
from .logging_utils import get_logger

_log = get_logger("llm")

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
