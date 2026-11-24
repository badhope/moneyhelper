# 4.19.0 企业预算与资金计划 + P1 能力补全

> 口径时间：2026-11-24。版本 4.19.0（上一版 4.18.0 多主体管理合并）。
> 本轮只交付可由本地数据确定性计算的能力：预算、资金计划、时序下钻、归因规则维度与个人资产调优。
> 税局直连、真实资金划转、法定合并、五社区代发布仍受资质/授权约束，不在本轮伪造完成。

## 一、企业预算

### 数据模型

- `enterprise_budget_plans(id, tenant_id, period, name, note, created_by, created_at, updated_at)`，唯一 `(tenant_id, period, name)`。
- `enterprise_budget_lines(id, plan_id, tenant_id, account_code, account_name, account_type, amount_cents, note)`，唯一 `(tenant_id, plan_id, account_code)`。

### 口径

- 期间统一 `YYYY-MM`，年份限制 2000–2100。
- 只允许现存 `income` / `expense` 科目；`assets` / `liabilities` / `equity` 拒绝。
- 金额以元输入、分存储；负数拒绝；`NaN` 拒绝；同一科目重复拒绝；单计划最多 200 行。
- 实际收入 `credit - debit`，实际费用 `debit - credit`，只取 `status=posted` 的总账凭证。
- 未预算但有实际数的科目进入 `rows` 并标 `unbudgeted`；预算总额只统计计划行，实际总额包含未预算行，这是有意口径。
- 草稿凭证不计入，但返回 `draft_entries` 并在 `warnings` 里提示。
- 保存预算只写计划表，不生成凭证、不改变账本。

## 二、资金计划

### 数据模型

- `enterprise_cash_plans(id, tenant_id, period, name, opening_cents, target_min_cents, note, created_by, created_at, updated_at)`。
- `enterprise_cash_plan_lines(id, plan_id, tenant_id, expected_date, direction, account_code, counterparty, amount_cents, certainty, note)`。

### 口径

- 计划行日期必须落在目标月份；方向只允许 `in` / `out`；金额必须为正。
- 现金科目只允许 `1001`（银行存款）/ `1002`（库存现金）；确定性只允许 `high` / `medium` / `low`。
- 期初余额由用户填写，不从历史账套推算。
- 实际数只取 `gl_entry_lines + gl_accounts` 中 `1001/1002` 的已过账行，按日期汇总。
- `cash_report` 输出 `as_of`、`projected_end`、`actual_to_date`、`planned_to_date`、`variance_to_date`、逐日 `series` 与 warnings。
- 资金计划是管理推演，不是银行余额；不代任何资金划转。

## 三、接口

- `GET /api/plan/periods`：计划期间 + 总账期间，并补当前月，最多 36 个。
- `GET /api/plan/budget?period=&name=` / `PUT /api/plan/budget`。
- `GET /api/plan/budget/report?period=&name=`。
- `GET /api/plan/cash?period=&name=` / `PUT /api/plan/cash`。
- `GET /api/plan/cash/report?period=&name=`。
- 读权限沿用 `gl:read`，写权限沿用 `gl:write`；预算与资金计划保存写 provenance。

## 四、P1.1 个人资产调优

新增纯函数 `calculations/asset_tune.py`，仪表盘返回 `asset_tune`，前端新增资产调优卡片。输入全部来自仪表盘既有口径：应急金、负债、集中度、现金流、目标配置。

候选类型：

- `liquidity`：应急金月数不足，给出补足金额。
- `debt`：利率 ≥ 8% 的负债，给出余额与年化利息。
- `concentration`：单一持仓超过集中度阈值，给出降至阈值所需减少金额。
- `rebalance`：复用 `compute_rebalance`，只列超出容忍带的买卖金额。
- `savings`：储蓄率低于 20%，给出每月多存金额。

每条候选都带 `detail`、`impact`、`risk`、`amount`、`confidence`、`requires_confirmation`；不代下单、不代还款、不预测收益。目标配置未设置时 `compute_rebalance` 只返回说明，不编造调仓。

## 五、P1.2 财税时序下钻

- 新增 `GET /api/finance/timeline/{month}`，月份必须 `YYYY-MM`。
- 返回该月已过账凭证 `entry_no / entry_date / description / lines`，逐行科目编码、名称、借贷金额与摘要，并返回借/贷合计与草稿数。
- 没有会计期间的月份返回 `status=missing` 与空列表，不用 0 或上月数据替代。
- 前端时序表月份行可点击展开，展示凭证与逐行科目；再次点击收起。

## 六、P1.3 归因规则增强

`attribution_rules` 新增：

- `merchant`：商户名，作为关键词之外的二次限定。
- `min_amount_cents` / `max_amount_cents`：按绝对值分的金额区间，0 表示不限。
- `member_id`：限定流水归属成员，空表示不限。

匹配顺序仍是启用规则按优先级从高到低取第一条；关键词、商户、金额区间、成员任一不满足即跳过。候选 `matched` 与 `reason` 会写明命中的商户、金额区间或成员。老库通过 `migrate_columns.py` 补列。

**账户维度边界**：现有 `transactions` 表没有账户字段，只有 `owner_id` 成员归属；不新增一个无法真实匹配的“账户”字段，避免伪功能。

## 七、P2 外部依赖项（未完成，不伪造）

| 项目 | 硬阻塞 |
| --- | --- |
| 税局直连申报/缴款 | 需要乐企准入或服务商通道，当前无资质 |
| 银行/券商真实资金划转 | 需要持牌通道与用户授权，默认只做 handoff |
| 法定合并报表 | 需要审计口径、合并范围确认与合规评审 |
| 五个内容社区代发布 | 需要各平台账号、登录与发布授权 |

## 八、交付判断

- 企业预算与资金计划：完成，可编制、可对比、可逐日推演。
- P1.1 个人资产调优：完成，确定性候选 + 风险说明，不代执行。
- P1.2 财税时序下钻：完成，单月凭证与逐行科目可查。
- P1.3 归因规则增强：完成，商户/金额/成员维度落库并参与匹配。
- P2：未完成，原因见上表。

## 九、验证与截图

- 后端定向 13 项通过；全量 `1951 passed, 1 warning in 290.91s`。
- 前端 35 文件 / 245 项通过（69.20s）；`tsc --noEmit`、`npm run build`（17.62s）通过。
- 浏览器：预算与资金数据、时序凭证下钻、归因商户/成员/金额字段、资产调优卡片均在实际构建上可见。
- 截图：`docs/screenshots/171-budget-plan.png`、`172-cash-plan.png`、`173-timeline-drilldown.png`、`174-attribution-rule-fields.png`、`175-asset-tune.png`、`176-cash-plan-dark.png`。
