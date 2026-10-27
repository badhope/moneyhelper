"""in-memory 滑动窗口限流的行为测：直接测 _rate_limit_check 纯函数（模块内 helper），
不依赖 HTTP 层，避免 conftest 全局禁用（MONEYHELPER_DISABLE_RATE_LIMIT=1）让限流行为失效。
"""

from __future__ import annotations

import time

import pytest
from app.middleware import _rate_limit_check


@pytest.fixture(autouse=True)
def _enable_and_fresh_bucket(monkeypatch):
    """conftest 为跑全量已置 MONEYHELPER_DISABLE_RATE_LIMIT=1 把本模块也关掉了。
    限流行为测上需要强制开 + 清空 _rate_buckets，保证单测独立可复现。"""
    from app import middleware as mw

    monkeypatch.setattr(mw, "_RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(mw, "_rate_buckets", {})


def test_under_limit_always_allows():
    """_RATE_LIMIT_MAX 内每次都放行。"""
    for _ in range(50):
        allowed, _ = _rate_limit_check("1.2.3.4")
        assert allowed is True


def test_over_limit_rejects():
    """连续打满配额后开始拒绝，retry_after 在窗口时间内。"""
    from app import middleware as mw

    now = time.time()
    mw._rate_buckets["9.9.9.9"] = [now - i * 0.01 for i in range(mw._RATE_LIMIT_MAX)]
    # 再来一条即触发上限
    allowed, retry = _rate_limit_check("9.9.9.9")
    assert allowed is False
    assert 0 < retry <= mw._RATE_LIMIT_WINDOW


def test_sliding_window_expires_old_entries():
    """窗口一过，旧记录被懒清理，重新放行。"""
    from app import middleware as mw

    now = time.time()
    # 全部超出 _RATE_LIMIT_WINDOW 的旧时间戳
    mw._rate_buckets["7.7.7.7"] = [now - (mw._RATE_LIMIT_WINDOW + 10)] * mw._RATE_LIMIT_MAX
    allowed, _ = _rate_limit_check("7.7.7.7")
    assert allowed is True


def test_different_ips_independent():
    """不同 IP 桶互不影响：A 打满不影响 B。"""
    from app import middleware as mw

    now = time.time()
    mw._rate_buckets["full.ip"] = [now - i * 0.01 for i in range(mw._RATE_LIMIT_MAX)]
    # full.ip 已被自己打满，再来一条应被拒
    assert _rate_limit_check("full.ip")[0] is False
    # 新 IP 仍放行
    assert _rate_limit_check("fresh.ip")[0] is True


def test_exactly_max_requests_are_allowed():
    """文档写 200 次/分钟：第 200 次必须放行，第 201 次才拒绝。

    旧实现用 `len(bucket) >= max`，实际配额只有 199，与响应头
    X-RateLimit-Limit: 200 自相矛盾。
    """
    from app import middleware as mw

    mw._rate_buckets.clear()
    for i in range(mw._RATE_LIMIT_MAX):
        allowed, _ = _rate_limit_check("5.5.5.5")
        assert allowed is True, f"第 {i + 1} 次请求被误拒（配额应等于 {mw._RATE_LIMIT_MAX}）"
    allowed, retry = _rate_limit_check("5.5.5.5")
    assert allowed is False and retry > 0
