"""LiteLLM 调用层：流式叙述、短文本流、JSON 补全与一次性 chat。

配置与路由一律通过门面动态取（`_facade._config()`），这样测试 patch
`llm._config` / `llm._detect_provider` 仍然生效，不会被 import 时快照绑死。
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import litellm

from . import llm as _facade
from .logging_utils import get_logger

_log = get_logger("llm")


async def stream_narrate(
    system: str, user: str, fallback: str, usage_out: dict[str, int] | None = None
) -> AsyncIterator[tuple[str, str]]:
    """流式调用；失败或空流时整体退回模板。产出 (文本增量, 来源)。

    usage_out 传入一个可变 dict 时，成功路径把最后一次响应的
    prompt/completion tokens 写回（{"prompt": int, "completion": int}），
    供调用方按轮落库；失败/模板路径不写，调用方据此区分。
    """
    cfg = await _facade._config()
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
    cfg = await _facade._config()
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
    cfg = await _facade._config()
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


async def litellm_chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    timeout: float = 60.0,
) -> str | None:
    """走 LiteLLM 的 chat completion。失败返回 None，由调用方降级。"""
    cfg = await _facade._config()
    if not cfg:
        return None
    try:
        import litellm  # type: ignore

        litellm.suppress_debug_info = True
        m = model or cfg.get("model", "gpt-4o-mini")
        provider = _facade._detect_provider(m, cfg.get("base", ""))
        litellm_model = _facade._to_litellm_model(m, provider, cfg.get("base", ""))
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
