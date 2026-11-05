"""端到端契约测试：**每个策略都必须能从 HTTP 接口真正拿到结果**。

这组测试的存在原因：上一轮新增 5 个策略时，单元测试全绿，但接口返回 500——
因为路由文件里漏了 import（`NameError: backtest_grid is not defined`），
且 `backtest_text` 只认旧策略、对新策略格式化 None 字段而崩溃。

单元测试测的是"函数对不对"，这组测的是"用户能不能用"。
两者缺一不可。
"""

import pytest

import httpx

from app import main


@pytest.fixture
async def client(temp_db):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


# 所有对外声称支持的策略
ALL_STRATEGIES = ["ma_cross", "dca", "grid", "trend", "vol_target"]


class TestBacktestContract:
    @pytest.mark.parametrize("strategy", ALL_STRATEGIES)
    @pytest.mark.asyncio
    async def test_strategy_never_500(self, client, strategy):
        """任何策略都不得返回 5xx——500 表示代码有未捕获异常。

        行情不可达时允许 available=false（这是业务降级），但不能崩。
        """
        r = await client.get(f"/api/research/backtest?symbol=600519&strategy={strategy}")
        assert r.status_code < 500, f"{strategy} 返回 {r.status_code}: {r.text[:300]}"

    @pytest.mark.parametrize("strategy", ALL_STRATEGIES)
    @pytest.mark.asyncio
    async def test_strategy_response_shape(self, client, strategy):
        """成功时必须有 result + text；失败时必须有 reason。"""
        r = await client.get(f"/api/research/backtest?symbol=600519&strategy={strategy}")
        assert r.status_code == 200
        data = r.json()
        if data.get("available"):
            assert data.get("result"), f"{strategy} 缺 result"
            assert data.get("text"), f"{strategy} 缺 text"
            # text 不能是空串或纯空白
            assert data["text"].strip()
        else:
            assert data.get("reason"), f"{strategy} 降级时没给 reason"

    @pytest.mark.asyncio
    async def test_unknown_strategy_rejected(self, client):
        r = await client.get("/api/research/backtest?symbol=600519&strategy=nonexistent")
        assert r.status_code == 400
        assert "strategy" in r.json()["detail"].lower()


class TestBacktestTextRobustness:
    """文字结论必须能处理任意策略（缺字段不能崩）。"""

    def test_all_strategies_produce_text(self):
        from app.calculations.backtest import (
            backtest_dca,
            backtest_ma_cross,
            backtest_text,
        )
        from app.calculations.strategies import (
            backtest_grid,
            backtest_trend,
            backtest_vol_target,
        )

        osc = [100 + 8 * ((i % 40) - 20) / 20 for i in range(200)]
        trend = [100 * (1.003**i) for i in range(200)]
        results = {
            "ma_cross": backtest_ma_cross(trend),
            "dca": backtest_dca(trend, invest_amount=1000, freq_days=5),
            "grid": backtest_grid(osc),
            "trend": backtest_trend(trend),
            "vol_target": backtest_vol_target(trend),
        }
        for name, res in results.items():
            assert res is not None, f"{name} 回测返回 None"
            for lang in ("zh", "en"):
                text = backtest_text(res, lang)
                assert text and text.strip(), f"{name}/{lang} 文字结论为空"
                assert "None" not in text, f"{name}/{lang} 文本里出现 None：{text[:200]}"

    def test_empty_result_gives_message(self):
        from app.calculations.backtest import backtest_text

        assert backtest_text(None, "zh")
        assert "不足" in backtest_text(None, "zh")


class TestNegativeZero:
    """-0.0 会被界面渲染成「-0.0%」，看起来像 bug。"""

    def test_flat_strategy_has_no_negative_zero(self):
        from app.calculations.strategies import backtest_grid

        flat = [100.0] * 200
        r = backtest_grid(flat)
        if r is not None:
            for key in ("total_return_pct", "max_drawdown_pct"):
                v = r.get(key)
                if v is not None:
                    assert not str(v).startswith("-0.0"), f"{key} 出现 -0.0"


class TestMomentumContract:
    @pytest.mark.asyncio
    async def test_never_500(self, client):
        r = await client.get("/api/research/momentum?symbols=600519,000001")
        assert r.status_code < 500

    @pytest.mark.asyncio
    async def test_rejects_one_symbol(self, client):
        assert (await client.get("/api/research/momentum?symbols=600519")).status_code == 400
