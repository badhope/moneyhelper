# 可复核性标准草案（M6.6）

> 定位：本项目所有对外结论必须能被第三方按本文件复核。不是营销承诺，是可执行的验收口径。
> 版本：草案 v0.1（2026-10-31）。任何与本文件冲突的实现，以实现为准并回改本文件。

## 1. 适用范围

适用于 Moneyhelper 输出的全部**数值型结论**：收支统计、持仓盈亏、风险指标、回测结果、
财报比率、税负测算、现金流预测、FIRE 推演、发票与对账单解析结果。

不适用：自然语言解释、建议措辞、模型生成的叙述段落。这些允许不确定，但不得包含未经计算的数字。

## 2. 五条硬性要求

### R1 数字必须来自确定性代码

任何出现在回答、卡片、导出文件里的金额/比率/日期，必须由 `backend/app/calculations/`、
`backend/app/analysis.py`、`backend/app/categorize.py` 等无副作用函数计算得出。
模型只能引用函数返回值，不得自行推算。

**可验证方式**：在仓库执行

```bash
rg -n "round\(|sum\(|/ " backend/app/agent.py backend/app/service.py | rg -v "calculations|analysis"
```

若出现业务数值运算，即为违规。

### R2 数据不足必须返回 null 与原因，不得返回看似合理的假值

每个计算函数在样本不足时返回 `None` 或 `available=false` 并附 `reason`。禁止用 0、
默认值或行业均值填充。

**可验证方式**：对每个计算模块跑空输入，断言 `available is False` 且 `reason` 非空。
现有覆盖：`test_calculations_*`、`test_strategy_api.py::test_risk_endpoint_degrades_without_holdings`、
`test_sandbox.py::test_missing_income_returns_reason`。

### R3 口径必须写进代码并可在输出中追溯

每个指标的口径（分母是什么、是否含现金、是否年化、样本区间）写在函数 docstring 里，
并在 API 响应的 `basis` / `assumptions` / `notes` 字段回传。

**可验证方式**：

```bash
rg -n 'basis|assumptions|notes' backend/app/calculations/*.py backend/app/routes/*.py
```

新增指标若没有口径字段，测试应失败（见 `test_deep_finance.py` 中的字段断言）。

### R4 每次写操作与外部动作必须进审计链

金额变动、交易指令、券商报单、导入批次、备份恢复，都必须写 `provenance_log`，
记录 before/after 与来源（api/agent/mcp/scheduler/connect/execute）。

**可验证方式**：

```bash
curl -s localhost:8788/api/provenance?limit=5 | jq '.entries[].action'
```

写操作后应出现对应 action。

### R5 外部数据必须标注来源与时效

所有行情、净值、指数、涨跌榜、发票解析结果，响应里必须带 `source` 与 `fetched_at`；
降级到备源时必须标明（如 `source=sina`、`note="东财不可用，已切换新浪"`）。

**可验证方式**：`GET /api/connect/indices`、`/api/connect/movers`、`/api/connect/stock/{symbol}/profile`
的响应均含 `source`；缺失即视为违规。

## 3. 复核流程（第三方如何验）

1. **取数**：调用对应 API，保存原始 JSON。
2. **复算**：用响应里的输入字段，按本文件第 2 节口径手算一遍。
3. **比对**：允许误差 = 显示精度的一半（金额 ±0.01，比率 ±0.005%）。
4. **溯源**：`GET /api/provenance?entity_id=<id>` 确认该数字来自哪次操作。
5. **判定**：三项全过为「可复核」；任一不过即记录缺陷，附请求与响应原文。

## 4. 已知不满足项（诚实清单）

| 项 | 现状 | 原因 |
|---|---|---|
| 模型叙述中的定性判断 | 不可复核 | 属于解释层，不承诺可复算 |
| 现金流预测 | 统计外推，非事实 | 输出已标 `basis` 与 `assumptions`，但未来本身不可验证 |
| 发票 OCR 识别 | 依赖第三方引擎 | 输出带 `confidence` 与 `warnings`，低置信度要求人工确认 |
| 券商成交价 | 由券商回报 | 本系统只做对账，不生成成交价 |
| 税务测算 | 参数化近似 | 明确标注「非正式税务意见」，地方比例需用户确认 |

## 5. 与其他文档的关系

- 计算口径细节：`docs/connect-hub-deep.md`（税负/现金流/风控公式）
- 审计字段定义：`backend/app/provenance.py`
- 测试基线：`docs/PROGRESS.md`
- 本文件为草案，接受修订；修订需在 CHANGELOG 记录并同步测试。
