"""HTML 报告：自包含、可打印、不注入。

断言重点不是排版好不好看，而是三个硬约束：
  1. 零外部依赖（断网可看）——不得出现 http(s) 资源引用；
  2. 用户数据必须转义——项目名里带 <script> 也不能执行；
  3. 数字口径直接来自输入结构，不重算。
"""

import re

from app.report import build_report

DASH = {
    "totals": {"total_market_value": 275000, "total_pnl": -28000, "total_pnl_pct": -9.39},
    "cashflow": {"net": 3535, "savings_rate": 14.3,
                 "by_category": [{"category": "餐饮", "amount": 1234.5}]},
    "positions": [
        {"symbol": "600519", "name": "贵州茅台", "kind": "股票",
         "market_value": 143910, "pnl": -24000, "pnl_pct": -14.34},
        {"symbol": "510300", "name": "沪深300ETF", "kind": "ETF",
         "market_value": 32680, "pnl": 1880, "pnl_pct": 6.10},
    ],
    "flags": [{"level": "warn", "code": "CONCENTRATION", "text": "茅台 65.5%"}],
}


class TestSelfContained:
    def test_no_external_resources(self):
        html = build_report(dashboard=DASH, title="报告", lang="zh")
        # 不得引用任何外部脚本/样式/图片（离线可用是硬约束）
        assert not re.search(r'(src|href)=["\']https?://', html)
        assert "<script" not in html.lower()

    def test_inline_svg_charts_present(self):
        html = build_report(dashboard=DASH, title="报告", lang="zh")
        assert html.count("<svg") >= 1
        assert "rect" in html

    def test_allocation_is_share_bar_not_fake_timeline(self):
        """持仓之间没有时间顺序，不能连成折线（那是伪信息）。"""
        html = build_report(dashboard=DASH, title="报告", lang="zh")
        assert "资产占比" in html
        assert "polyline" not in html, "不应把持仓市值连成折线"

    def test_print_stylesheet_present(self):
        html = build_report(dashboard=DASH)
        assert "@media print" in html


class TestEscaping:
    def test_script_in_position_name_is_escaped(self):
        dash = dict(DASH)
        dash["positions"] = [{"symbol": "X", "name": "<script>alert(1)</script>",
                              "kind": "股票", "market_value": 1, "pnl": 0, "pnl_pct": 0}]
        html = build_report(dashboard=dash, title="<script>bad()</script>")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_quote_in_title_is_escaped(self):
        # 标题同时进入 <title> 与 <h1>，引号必须转义，否则可闭合标签注入属性
        html = build_report(dashboard=DASH, title='He said "hi" & <b>x</b>')
        assert "&quot;hi&quot;" in html
        assert "&lt;b&gt;" in html
        assert "<b>x</b>" not in html


class TestContent:
    def test_kpis_use_input_numbers(self):
        html = build_report(dashboard=DASH)
        assert "275,000" in html
        assert "-28,000" in html

    def test_actions_section_only_when_provided(self):
        without = build_report(dashboard=DASH)
        with_actions = build_report(
            dashboard=DASH,
            actions={"items": [{"domain_label": "风险", "title": "集中", "detail": "65%"}]},
        )
        assert "现在该做什么" not in without
        assert "现在该做什么" in with_actions

    def test_accounts_sources_table(self):
        html = build_report(
            dashboard=DASH,
            accounts={
                "total_net_worth": 300000,
                "sources": [
                    {"name": "本地账本", "net_worth": 220000, "counted": True, "detail": "x"},
                    {"name": "美股", "net_worth": 50000, "counted": False, "detail": "未折算"},
                ],
                "caveats": ["外币未折算"],
            },
        )
        assert "300,000" in html
        assert "美元" not in html  # 不应臆造币种
        assert "外币未折算" in html

    def test_english_language(self):
        html = build_report(dashboard=DASH, lang="en", title="Report")
        assert "Market value" in html
        assert "Holdings" in html

    def test_empty_dashboard_does_not_crash(self):
        html = build_report(dashboard={})
        assert html.startswith("<!doctype html>")
        assert "无数据" in html or "数据点不足" in html


class TestDeterminism:
    def test_same_input_same_output(self):
        a = build_report(dashboard=DASH, lang="zh", generated_at="2026-11-03")
        b = build_report(dashboard=DASH, lang="zh", generated_at="2026-11-03")
        assert a == b
