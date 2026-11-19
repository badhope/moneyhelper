"""时间戳格式策略守卫。

背景：项目里有两个时间写入函数——
`timeutil.now_str()`（无时区，`2026-01-01T00:00:00`）与 `timeutil.now_iso()`（带偏移，
`2026-01-01T00:00:00+08:00`）。M1 拆分时它们被各自复制进模块，于是同一张表的
时间语义取决于「谁在写」。

实测结论（2026-11-19 扫描全部 INSERT 语句）：**目前没有任何一张表被两种格式同时写入**，
所以不存在需要迁移的历史数据。真正的风险是未来漂移——新模块给老表写另一种格式，
排序/比较就开始出错（字符串比较下 `...+08:00` 与无偏移串不同构）。

因此这里不做数据迁移，而是把「谁用哪个函数」钉成一张表：任一模块改签名或换函数，
本用例立刻失败，逼着改动者显式说明理由，而不是悄悄混写。
"""

from __future__ import annotations

import importlib

import pytest

# 模块 -> 该模块 `_now` 必须解析到的函数名
NAIVE = "now_str"        # 无时区：payments / expense_claims / gl_entries / org / procurement
AWARE = "now_iso"        # 带 +08:00：凭据 / 连接 / 调动 / 行情缓存 / 长任务 / 模拟盘 / 部门报表

POLICY: dict[str, str] = {
    # --- 无时区（历史数据量大，改成带偏移会让新旧行不同构，只能整表迁移）---
    "app.db.banking": NAIVE,
    "app.db.expenses": NAIVE,
    "app.db.gl": NAIVE,
    "app.db.org": NAIVE,
    "app.db.procurement": NAIVE,
    "app.longtask": NAIVE,
    # --- 带偏移 ---
    "app.db.broker_credentials": AWARE,
    "app.db.connect_deep": AWARE,
    "app.db.motions": AWARE,
    "app.connect.marketdata": AWARE,
    "app.connect.quote_tencent": AWARE,
    "app.connect.store": AWARE,
}


@pytest.mark.parametrize(("module_name", "expected"), sorted(POLICY.items()))
def test_module_uses_declared_clock(module_name: str, expected: str) -> None:
    module = importlib.import_module(module_name)
    clock = getattr(module, "_now", None)
    assert clock is not None, f"{module_name} 不再暴露 _now，请更新本策略表"
    assert clock.__name__ == expected, (
        f"{module_name}._now 解析到了 {clock.__name__}，策略要求 {expected}。"
        "若要改格式，必须先确认该模块写的表没有被另一种格式写过，"
        "并连同数据迁移一起提交。"
    )


def test_two_clocks_are_distinguishable() -> None:
    """两个函数的输出必须可区分，否则上面那张表守不住任何东西。"""
    from app import timeutil

    naive, aware = timeutil.now_str(), timeutil.now_iso()
    assert "T" in naive and "+" not in naive and naive.count(":") == 2
    assert "T" in aware and ("+" in aware or aware.endswith("Z"))
    # 同一时刻、同一精度：都到秒
    assert len(naive) == 19 and len(aware) >= 25


def test_shared_clock_is_single_source() -> None:
    """`_now` 必须来自 timeutil，不允许模块内再定义一份。"""
    import inspect

    from app import timeutil

    for name in POLICY:
        module = importlib.import_module(name)
        clock = module._now
        assert inspect.getmodule(clock) is timeutil, f"{name}._now 不是 timeutil 里的函数"
