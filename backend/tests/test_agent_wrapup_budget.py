"""收尾成文预算随 LLM_TIMEOUT 缩放。

本机 2B 模型把 LLM_TIMEOUT 调到了 240s，但收尾请求仍写死 20s——
模型连一段话都生成不完，于是"工具轮次用尽"直接变成"模型未产出回答"。
云端默认 60s 必须保持原来的 20s，不能被这个改动拖慢。
"""

from __future__ import annotations

import pytest
from app.agent_turn import _wrapup_budget


@pytest.fixture(autouse=True)
def _restore_env(monkeypatch):
    yield


def test_default_cloud_timeout_keeps_20s(monkeypatch):
    monkeypatch.delenv("LLM_TIMEOUT", raising=False)
    assert _wrapup_budget() == 20.0


def test_local_slow_model_scales_up(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "240")
    assert _wrapup_budget() == 80.0


def test_budget_is_capped(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "600")
    assert _wrapup_budget() == 90.0
