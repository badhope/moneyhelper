"""Agent 共享异常：模型未配置或工具循环失败时抛出，调用方降级到确定性路径。"""

from __future__ import annotations


class AgentUnavailable(Exception):
    """模型未配置或工具循环失败：调用方应降级到确定性路径。"""
