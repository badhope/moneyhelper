"""模型目录：设置页展示的精选清单与默认点亮项（纯数据，无外部依赖）。

只保留国内可直连的 OpenAI 兼容聚合端点：国外平台（OpenAI / Anthropic /
Gemini）已从目录移除——用户在国内，跨境外网端点既慢又常被风控拦截。
"""

from __future__ import annotations

# 内置聚合端点：一个 base + 一个 key 就能列出全部可用模型
QSAI_BASE = "https://api.qs.al/v1"


def model_catalog() -> list[dict[str, str]]:
    """返回模型目录（OpenAI 兼容端点精选子集）。"""
    return [
        {
            "id": "glm-5.3-flash",
            "name": "GLM-5.3 Flash（内置·最省）",
            "provider": "QSAI 内置",
            "base": QSAI_BASE,
            "model": "glm-5.3-flash",
        },
        {
            "id": "deepseek-v4.1-flash",
            "name": "DeepSeek V4.1 Flash（内置）",
            "provider": "QSAI 内置",
            "base": QSAI_BASE,
            "model": "deepseek-v4.1-flash",
        },
        {
            "id": "kimi-k3",
            "name": "Kimi K3（内置）",
            "provider": "QSAI 内置",
            "base": QSAI_BASE,
            "model": "kimi-k3",
        },
        {
            "id": "glm-5.3",
            "name": "GLM-5.3（内置·旗舰）",
            "provider": "QSAI 内置",
            "base": QSAI_BASE,
            "model": "glm-5.3",
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
    """默认点亮模型清单：内置最省的一档，开箱即用不烧钱。"""
    return ["glm-5.3-flash", "deepseek-v4.1-flash"]


# LiteLLM 的 provider/model 前缀映射（通义/豆包/聚合端点走 openai 兼容通道）
_PROVIDER_PREFIX: dict[str, str] = {
    "openai": "openai",
    "deepseek": "deepseek",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "qwen": "openai",  # 通义千问 OpenAI 兼容 → 用 openai provider + 自定义 base_url
    "doubao": "openai",  # 豆包 OpenAI 兼容 → 用 openai provider + 自定义 base_url
    "qsai": "openai",  # 内置聚合端点 OpenAI 兼容
}
