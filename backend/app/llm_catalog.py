"""模型目录：设置页展示的精选清单与默认点亮项（纯数据，无外部依赖）。"""

from __future__ import annotations


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

# LiteLLM 的 provider/model 前缀映射（通义/豆包走 openai 兼容端点）
_PROVIDER_PREFIX: dict[str, str] = {
    "openai": "openai",
    "deepseek": "deepseek",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "qwen": "openai",  # 通义千问 OpenAI 兼容 → 用 openai provider + 自定义 base_url
    "doubao": "openai",  # 豆包 OpenAI 兼容 → 用 openai provider + 自定义 base_url
}

