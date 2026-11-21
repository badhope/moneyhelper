"""工具面裁剪（LLM_TOOL_LIMIT）的纯函数测试。

裁剪只在小模型自托管场景启用，但一旦裁错（例如把用户明说的工具裁掉），
模型就会"有工具不用"——表现和模型能力不足一模一样，很难现场分辨。
所以这里守两件事：数量上限、点名必留。
"""

from __future__ import annotations

from app.agent_tool_rank import rank_tools


def _schema(name: str, desc: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc}}


SCHEMAS = [
    _schema("get_quote", "查询股票实时报价"),
    _schema("get_ledger_view", "查看本月账本流水与收支合计"),
    _schema("get_trend", "查看支出趋势与月度变化"),
    _schema("get_weather", "查询天气，与财务无关"),
    _schema("get_goals", "查看储蓄目标进度"),
]


def test_limit_zero_keeps_all():
    assert rank_tools("本月支出多少", SCHEMAS, 0) == SCHEMAS


def test_limit_never_exceeds_and_keeps_relevant():
    kept = rank_tools("本月支出多少", SCHEMAS, 2)
    assert len(kept) == 2
    names = {s["function"]["name"] for s in kept}
    # 「支出/本月/账本」都指向这两个工具
    assert "get_ledger_view" in names or "get_trend" in names
    assert "get_weather" not in names


def test_explicit_tool_name_is_never_dropped():
    kept = rank_tools("用 get_weather 看看明天下雨吗", SCHEMAS, 1)
    assert [s["function"]["name"] for s in kept] == ["get_weather"]


def test_stable_order_on_tie():
    # 问题与任何工具都不重叠时，按原有顺序取前 N，结果可重复
    first = rank_tools("随便聊聊", SCHEMAS, 3)
    second = rank_tools("随便聊聊", SCHEMAS, 3)
    assert [s["function"]["name"] for s in first] == [
        s["function"]["name"] for s in second
    ]
    assert len(first) == 3


def test_returns_all_when_fewer_than_limit():
    assert rank_tools("本月支出", SCHEMAS, 10) == SCHEMAS
