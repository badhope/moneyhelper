"""LiteLLM 兼容客户端：把 acompletion 包装成 openai SDK 形态，供 agent 复用。

从 llm.py 拆出。client 单例按「模型+端点+密钥哈希+超时」做指纹，
换 key 必须重建，否则表现为"改了 key 仍 401，重启才好"。
"""

from __future__ import annotations

import hashlib
import json
import os
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

    def __init__(self, cfg: dict[str, Any], timeout: float | None = None) -> None:
        self._cfg = cfg
        self._timeout = llm_timeout(timeout)
        self.chat = _CompatChat(cfg, self._timeout)

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

        # 可选透传体（LLM_EXTRA_BODY，JSON）：本地/国产端点的采样与模板开关差异很大，
        # 例如 MiniCPM5 默认 Think 会把 token 全花在推理里、一个工具都不调，
        # 需要 {"chat_template_kwargs":{"enable_thinking":false}} 才走 No-Think。
        # 放在环境变量而不是写死：不同端点（vLLM/SGLang/llama.cpp）支持的字段不同，
        # 写死一个就等于把某家的私有字段塞进通用请求。
        extra = _extra_body()
        if extra:
            litellm_kwargs["extra_body"] = extra

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

def _extra_body() -> dict[str, Any] | None:
    """解析 LLM_EXTRA_BODY（JSON 对象）；非法时只告警、不影响主流程。"""
    raw = os.getenv("LLM_EXTRA_BODY", "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        _log.warning("LLM_EXTRA_BODY 不是合法 JSON，已忽略")
        return None
    return parsed if isinstance(parsed, dict) and parsed else None


def llm_timeout(explicit: float | None = None) -> float:
    """单次模型调用超时（秒）。

    为什么必须可配：本地 CPU 跑 2B 模型时，7k token 的 prefill 就要 3 分钟，
    写死 60s 会让每一轮都超时、整轮降级成模板——看起来像"模型不会调工具"，
    实际是请求根本没跑完。云端小模型不需要改；自托管大 prompt 才需要调大。
    LLM_TIMEOUT 取值范围夹到 [5, 600]，防手滑写成 0 或 10^6。
    """
    if explicit is not None:
        return max(5.0, min(float(explicit), 600.0))
    raw = os.getenv("LLM_TIMEOUT", "").strip()
    try:
        return max(5.0, min(float(raw), 600.0)) if raw else 60.0
    except ValueError:
        _log.warning("LLM_TIMEOUT 不是数字，已按默认 60s 处理")
        return 60.0


def llm_tool_limit() -> int:
    """单轮暴露给模型的工具数上限（0 = 不限制，保持历史行为）。

    小模型（2B 级）在 40 个工具的 schema 下会放弃选择、直接凭上下文作答；
    压到个位数后能稳定命中正确工具。云端大模型不需要这个开关。
    上限夹到 [0, 40]，避免手滑写成巨大值等于关闭。
    """
    raw = os.getenv("LLM_TOOL_LIMIT", "").strip()
    if not raw:
        return 0
    try:
        return max(0, min(int(raw), 40))
    except ValueError:
        _log.warning("LLM_TOOL_LIMIT 不是整数，已按 0（不限制）处理")
        return 0


def _sdk(cfg: dict[str, Any], timeout: float | None = None) -> _CompatClient:
    """构造兼容客户端（供 agent.py 使用：保持 client.chat.completions.create(...) 调用形态）。"""
    return _CompatClient(cfg, timeout)

_client_singleton: _CompatClient | None = None

_client_singleton_cfg_key: str | None = None

def _get_client(cfg: dict[str, Any], timeout: float | None = None) -> _CompatClient:
    """获取/重建兼容 client（配置变更时重建）。

    指纹必须包含 api_key：用户在设置页换了密钥但模型名与端点没变时，
    旧逻辑会复用带旧 key 的客户端，表现为"改了 key 仍 401，重启才好"。
    只取 key 的哈希前 8 位参与指纹，避免把明文密钥留在内存字符串里到处传。
    """
    global _client_singleton, _client_singleton_cfg_key
    key_hash = hashlib.sha256(str(cfg.get("key") or "").encode()).hexdigest()[:8]
    resolved = llm_timeout(timeout)
    key = f"{cfg['litellm_model']}:{cfg.get('base', '')}:{key_hash}:{resolved}"
    if _client_singleton is None or _client_singleton_cfg_key != key:
        _client_singleton = _sdk(cfg, resolved)
        _client_singleton_cfg_key = key
    return _client_singleton
