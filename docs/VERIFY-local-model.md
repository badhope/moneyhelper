# 真模型逐工具验收记录（2026-11-21）

目标：不要"能跑就行"，而是逐个确认 40 个只读工具**模型会不会选、参数对不对、
实现是不是真返回数据**。云端凭证缺失，改用本机 MiniCPM5-2B（llama.cpp，
OpenAI 兼容端点，`--jinja -fa on -c 12288 -t 2`，关闭 think）。

复现：

```bash
# 1) 起本机模型（llama.cpp release + GGUF 放在 .models/）
llama-server -m .models/MiniCPM5-2B-Q4_K_M.gguf --jinja -fa on -c 12288 -t 2 --port 8090

# 2) 单工具模式：只暴露目标工具，看它会不会发出调用
PYTHONPATH=backend LLM_BASE_URL=http://127.0.0.1:8090/v1 LLM_API_KEY=sk-local \
LLM_MODEL=MiniCPM5-2B LLM_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":false}}' \
python3 scripts/probe_tool_matrix.py --mode solo

# 3) 生产裁剪模式：全量工具 + LLM_TOOL_LIMIT，看排序有没有留住目标
PYTHONPATH=backend LLM_TOOL_LIMIT=6 ... python3 scripts/probe_tool_matrix.py --mode ranked
```

判据只有三条：有没有发出工具调用、调的是不是目标工具、参数能不能过
`validate_tool_args`。**不看答案文本**——空库上模型照样能写得很像真的，
凭文本打分会把"编数字"误判成通过。

## 结果（solo，40/40）

| 域 | 工具 | 结果 |
| --- | --- | --- |
| 个人财务 | `get_market_view` / `get_ledger_view` / `get_risk_flags` / `get_budget` / `get_trend` / `get_health_check` / `get_goals` / `get_user_memory` / `get_lessons` | 9/9 调用成功，参数合法 |
| 行情与投研 | `search_symbol` / `get_quote` / `get_kline` / `get_watchlist` / `get_valuation` / `stock_profile` / `market_breadth` / `research_analyze` / `research_backtest` / `research_forecast` / `get_portfolio_risk` / `get_rebalance_plan` | 12/12 |
| 计划与扫描 | `get_dca_plans` / `get_fire_plan` / `debt_payoff_plan` / `cashflow_forecast` / `scan_subscriptions` / `scan_anomalies` / `pretrade_check` | 7/7 |
| 企业与账务 | `get_gl_summary` / `get_payables_summary` / `get_expense_queue` / `get_org_overview` / `list_longtasks` / `paper_overview` | 6/6 |
| 连接与工具 | `connect_catalog` / `connect_fund_nav` / `broker_status` / `invoice_vision_status` / `tax_calc` / `statements_analyze` | 6/6 |

耗时分布：`get_kline` 86s、`broker_status` 136s（要探本机 QMT/easytrader），
其余 9–100s；单题两轮（一次调用 + 一次成文）。`get_quote` 真拉到
`600519 1485.75(+1.75%)`，`search_symbol` 能解析"贵州茅台"到代码。

## 测出来的两个真问题

1. **工具裁剪把正确工具裁掉了**（`LLM_TOOL_LIMIT=6`）。
   "我的持仓现在值多少钱，亏了还是赚了" 保留的是
   `get_quote / get_dca_plans / stock_profile / budget / watchlist / payables`，
   `get_market_view` 不在前 6 —— 模型只能拿别的工具凑答案。
   原因：按字面二字重叠计数，"适合回答/查询/用户"人人都有，谁描述长谁占便宜；
   而用户问句是口语转述，"你还记得我家里什么情况吗"里没有"记忆""家庭"原词。
   修法：IDF 降权常见词 + 40 条口语别名 + 泛词过滤；23 条真实问句回归全绿。

2. **`statements_analyze` 入参结构说不清**。
   模型把"收入 1200 万、成本 700 万"按扁平键值传，实现层返回
   "财报数据无效：需要 periods 数组"。描述里补了 `payload` 嵌套字段示例后，
   同题产出毛利率 41.67% 等指标。

## 未完成

`ranked` 模式全量 40 题没有跑完：2B 在 6 个工具 + 空库场景下每題约
10 分钟（5 轮工具循环 + 每轮重新 prefill），40 题要 4 小时以上。
已完成的抽样（持仓 `get_market_view`）均命中目标工具，排序问题由上面的单测覆盖；
需要全量行为验证时，建议换云端模型或把 `MAX_TURNS` 调低再跑。
