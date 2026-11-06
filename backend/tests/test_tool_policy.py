"""工具权限策略：默认最严、最后匹配优先、高危不可降级。

这些断言保护的是「模型不能凭幻觉改用户资产」这条底线：
宁可多问一次，也不能让未知工具默认自动执行。
"""

import pytest
from app.tool_policy import (
    ASK,
    DENY,
    HARD_ASK,
    READ,
    filter_allowed,
    load_rules,
    resolve,
    summarize,
)


class TestDefaults:
    @pytest.mark.parametrize("name", [
        "get_market_view", "get_ledger_view", "research_backtest",
        "statements_analyze", "connect_fund_nav",
    ])
    def test_readonly_tools_are_read(self, name):
        assert resolve(name) == READ

    @pytest.mark.parametrize("name", [
        "record_transaction", "record_position", "sell_position",
        "backup_now", "trigger_morning_report", "paper_trade",
    ])
    def test_write_tools_require_ask(self, name):
        assert resolve(name) == ASK

    def test_unknown_tool_fails_closed(self):
        """新工具默认必须是 ASK——绝不能因为「忘了加规则」就自动执行。"""
        assert resolve("some_future_tool") == ASK

    def test_empty_name_is_denied(self):
        assert resolve("") == DENY
        assert resolve("   ") == DENY

    def test_delete_pattern_is_denied(self):
        assert resolve("delete_everything") == DENY


class TestRuleOrder:
    def test_last_match_wins(self):
        rules = [("get_*", ASK), ("get_market_view", READ)]
        assert resolve("get_market_view", rules) == READ
        assert resolve("get_ledger_view", rules) == ASK

    def test_narrow_rule_can_tighten(self):
        rules = [("record_*", READ), ("record_position", ASK)]
        assert resolve("record_position", rules) == ASK

    def test_hard_ask_cannot_be_downgraded(self):
        """高危工具即使被配置成 read，也必须回到 ASK——安全底线不可配。"""
        rules = [("backup_now", READ), ("connect_order", READ), ("sell_position", READ)]
        for name in ("backup_now", "connect_order", "sell_position"):
            assert name in HARD_ASK
            assert resolve(name, rules) == ASK


class TestLoadRules:
    def test_valid_rules(self):
        assert load_rules([{"pattern": "get_*", "policy": "read"}]) == [("get_*", READ)]

    @pytest.mark.parametrize("bad", [
        None, "notalist", [{"pattern": "", "policy": "read"}],
        [{"pattern": "x", "policy": "whatever"}], [{"policy": "read"}], ["string"],
    ])
    def test_invalid_rules_reject_whole_table(self, bad):
        """半可信的策略表比没有更危险：任何一条非法即整体拒绝。"""
        assert load_rules(bad) is None


class TestFiltering:
    def test_filter_allowed_returns_only_read(self):
        names = ["get_market_view", "record_transaction", "delete_all", "unknown_tool"]
        assert filter_allowed(names) == ["get_market_view"]

    def test_summarize_groups_all(self):
        out = summarize(["get_market_view", "record_transaction", "delete_x"])
        assert "get_market_view" in out[READ]
        assert "record_transaction" in out[ASK]
        assert "delete_x" in out[DENY]

    def test_counts_add_up(self):
        names = ["get_a", "record_b", "delete_c", "mystery"]
        out = summarize(names)
        assert sum(len(v) for v in out.values()) == len(names)
