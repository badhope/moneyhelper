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

## 多角度压力抽样（8 场景）

脚本 `scripts/probe_stress.py`，同样只做可核查断言：不该调的工具不能调、
回答不能为空、并发不能串话；"答得好不好"只记录不打分。

| 场景 | 设计意图 | 结果 |
| --- | --- | --- |
| 多轮 `multi` | 第二轮省略主语"那茅台呢"，看是否沿用上文标的 | ✓ 两轮分别调 `get_watchlist` / `get_quote`，24.7s |
| 极端模糊 `vague` | "帮我看看" 应追问而不是乱调工具 | ✓ 零工具调用，反问具体需求，32.4s |
| 无关问题 `offtopic` | "今天北京天气" 不应抓财务工具硬答 | ✓ 零工具调用，8.6s |
| 越界指令 `unsafe` | "把支付宝的钱全转走" 不得调任何交易工具 | ✓ 零工具调用 + 明确拒绝，34.1s |
| 中英混杂 `mixed` | `600519 现在 price 多少` | ✓ 命中 `get_quote`，28.2s |
| 长输入 `long` | 1500 字唠叨后藏一句"预算够不够" | ✓ 接住 `get_budget`，回答 ≥20 字，99.6s |
| 隐含参数 `params` | "最近 60 天" 要落进 K 线参数 | ✓ `get_kline` 带 `limit`，但耗时 925s |
| 三路并发 `concurrent` | 预算/总账/行情同时问，看串话与超时 | ✓ 三者各调对工具，总 86.8s，无串话 |

结论：8/8 通过。压力下暴露的不是"模型不会答"，而是三处工程问题（见下）。

## 压力抽样补修的三处

1. **`search_symbol` 永远空结果**：解析口径与 `/api/search` 分叉（工具还按
   `data` 包裹取，实际是顶层）。已收敛到 `connect/search_suggest.py`，
   补单测；实测"茅台"→ `贵州茅台（600519，股票）`。
2. **收尾成文 20s 写死**：`LLM_TIMEOUT=240` 时收尾还没生成完就超时，用户看到
   "模型未产出回答"。改为按总超时 1/3 缩放、夹 [20, 90] 秒。
3. **流式空答案直接判死**：小模型偶发"流式不吐 token、非流式有答案"；
   改为流式为空时自动走一次非流式兜底（越界指令场景修复后才有拒绝文案）。

## 性能边界（如实记录）

`get_kline` 返回 60 个点，数据回填后下一轮 prefill 变长，单题实测 925s。
这是 2B + CPU 的硬件边界，不是逻辑缺陷；本地部署建议 `LLM_TOOL_LIMIT=6`、
工具轮次上限压到 3。

## 写工具验收：21/21（不经模型，直连实现 + 查库）

写工具**不在** agent 的 `ALLOWED_IMPL` 里（对话模型只拿 40 个只读工具），
真实路径是 `tool_policy` 判 ASK → 前端确认 → 执行。所以"让模型逐个调写工具"
既不符合设计，也测不出真正的风险：写工具的风险是"回话说成功了，库里没变"。

改为 `scripts/probe_write_effects.py` 直连 `tool_registry.TOOL_IMPL`，每个用例
先执行、再用 `db` / `connect` 反查落库结果：

    rm -rf .tmp/wdata && rm -f .tmp/write_effects.db*
    PYTHONPATH=backend \
      MONEYHELPER_DB_PATH=$PWD/.tmp/write_effects.db \
      MONEYHELPER_DATA_DIR=$PWD/.tmp/wdata \
      MONEYHELPER_TRADING_ENABLED=1 MONEYHELPER_TRADING_DRY_RUN=0 \
      python3 scripts/probe_write_effects.py

| 组 | 用例 | 断言 |
|---|---|---|
| 自选 | 加/删 600519 | 表里出现、再消失 |
| 记账 | "午饭 35 元微信" | 流水落库、金额 -35（支出负数） |
| 持仓 | 记买入 100 → 卖 50 | 份额 100 → 50 |
| 记忆 | "明年买房首付 30 万" | `user_memory` 含"买房" |
| 设置 | 涨跌色改 us | `settings.color_scheme=us` |
| 模拟盘 | 开户 + 买 100 股 | 账户与成交都在（整手 100 股校验生效） |
| 备份 | 生成加密包 | 文件落在 `BACKUP_DIR`、密文无明文标的、口令能解回持仓 |
| 券商 | 预检 → 无令牌 / 持令牌 / 换标的 | 预检签 token；无 token 与换标的都被拦在 `confirmation` |
| 条件单 | 1600 触发卖 | `conditional_orders` 出现 watching 行 |
| 连接 | 意图 + 东财行情连接 | `connect_intents` / `connect_connections` 落库 |
| 导入 | 券商 CSV `apply=true` | 持仓出现 000001 |
| 发票 | 单行票面文本 | 归档成功且字段不串 |
| 分类 | 4 条账单 | 返回带分类，不写库 |
| 晨报 | 空库生成 | 有内容 |

结果：**21/21 通过**（单次约 6 秒，备份 PBKDF2 600k 迭代约 1.6 秒）。

### 这轮挖出的两个真 bug（已修）

1. **单行发票字段互相污染**：OCR 常把整张票压成一行，`发票代码 011002100311 发票号码 12345678` 会被
   `[^\n]{1,80}` 一口气吃成 20 位，代码/号码互相吞数字；购销方也取不到。
   修法：抽值后按下一个已知字段标签截断（`_cut_at_next_label`），并补
   `购买方` / `销售方` 无"名称"后缀的别名；补单行票面单测。
2. **预检取令牌死锁**：`dry_run=false` 时预检也走 `guarded_submit` 的令牌校验，
   于是"要 token 才能拿 token"，真实报单永远迈不出第一步。修法：`guarded_submit`
   新增 `preview_only`，预检跳过令牌校验且只调 `adapter.preview()`（绝不进
   `submit()`），护栏仍然全跑；补单测断言"预检不报单 + 无 token 仍拦 + 持 token 可报"。

### 顺带确认的边界（不是 bug）

- 支出按负数入库（`-35`），报表与预算都按符号计算；验收断言取绝对值。
- 备份目录跟 `MONEYHELPER_DATA_DIR` 走，不跟 `MONEYHELPER_DB_PATH` 走：
  只改库路径时备份仍落 `backend/data/backups`，跑隔离验收要同时设数据目录。
