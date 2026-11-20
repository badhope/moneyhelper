"""供应商推断与 LiteLLM 模型串拼装（纯函数）。"""

from __future__ import annotations


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
