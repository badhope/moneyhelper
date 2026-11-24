# 4.18.0 企业多主体管理合并

> 版本：4.18.0。定位：**管理口径合并**，不是法定合并。
> 入口：财报页内「单体财报 / 多主体合并」切换，不新增顶层板块。

## 一、为什么做

4.17.3 之前，企业侧已有租户、成员、部门、复式总账、试算平衡与三表还原，但每个租户各看各的账。一个老板同时持有总部与子公司时，只能手工把几套报表相加；内部交易、持股比例和缺账主体都没有统一口径。

4.18.0 解决的是「把多个主体的已过账总账，按明确规则拼成一张集团管理报表」，同时保留三条硬边界：

1. **只读各主体已过账凭证**，不替任何主体改账；
2. **不按 0 冒充缺账**，没有期间或没有已过账凭证的主体显式排除并标记；
3. **不做法定合并**，不自动计算少数股东权益，不自动识别内部交易。

## 二、数据模型

新增三张表，挂载在 `backend/app/db/schema_consolidation.py`：

| 表 | 作用 | 关键约束 |
| --- | --- | --- |
| `tenant_groups` | 集团 | `owner_user_id` 是唯一访问边界；同一 owner 下 active 集团名唯一 |
| `tenant_group_entities` | 合并范围 | PK `(group_id,tenant_id)`；`ownership_pct`、`method`、`sort_order` |
| `consolidation_adjustments` | 抵销分录 | 按明细行存；`(group_id,period,voucher_id,line_no)` 唯一；同凭证借贷必须平衡 |

集团只对创建者本人可见可管，不跨用户授权边界。主体必须是当前用户的有效成员租户；本机租户 0 允许本机管理员直接纳入。每次合并还会复查成员关系，成员资格被撤销的主体标为 `no_access` 并排除，不会凭旧集团范围继续读账。

## 三、纳入方式

| `method` | 持股 | 合并规则 |
| --- | --- | --- |
| `full` | 必须 100% | 逐行全额纳入 |
| `proportional` | `0 < pct <= 100` | 每个科目借/贷发生额按 `pct/100` 折算 |

明确不做：

- 权益法；
- 自动计算少数股东权益；
- 按内部交易自动匹配抵销；
- 法定合并所需的审计调整、合并范围评估与披露。

部分持股如需 NCI，应在后续版本或线下调整中处理；当前 `full` + 非 100% 会被服务端拒绝。

## 四、合并计算流程

`db/consolidation.py` 的 `consolidate()`：

1. 读取集团范围，逐个主体按目标 `YYYY-MM` 查找 `gl_periods`。
2. 没有期间 → `missing`；有期间但 `posted_entries=0` → `no_posted`；两者都不拿 0 计入。
3. 对有效主体调用 `gl_trial_balance()`，按 method 折算；按科目 `code` 聚合。
4. 叠加该期间的抵销分录；未知科目、借贷不平、金额非正都会在写入时拒绝。
5. 用既有的 `statements_from_trial_balance()` 还原集团三表，再调用 `analyze_statements()` 产出指标与预警。
6. 返回单体报表摘要、按持股折算合计、抵销后合并、科目底稿、抵销明细、可选期间与边界说明。

返回中的 `balanced` 表示合并试算借方合计是否等于贷方合计；比例折算产生尾差时保留差额并给出 warning，不自动抹平。

## 五、接口

全部挂在 `/api/consolidation`：

- `GET /groups`：当前用户创建的集团列表。
- `POST /groups`：新建集团。
- `GET /groups/{gid}`：集团、范围、可选期间、科目目录、可加入租户。
- `DELETE /groups/{gid}`：删除集团范围与抵销，主体总账不动。
- `GET /groups/{gid}/candidates`：当前用户可纳入、尚未纳入的租户。
- `POST /groups/{gid}/entities`：纳入已有租户。
- `POST /groups/{gid}/entities/new`：在集团内新建企业租户，写 `tenants`、owner membership，并铺默认科目表。
- `DELETE /groups/{gid}/entities/{tid}`：移出主体。
- `GET /groups/{gid}/report?period=YYYY-MM`：运行合并。
- `GET/POST /groups/{gid}/adjustments`：抵销分录列表/新增。
- `DELETE /groups/{gid}/adjustments/{vid}`：删除一张抵销凭证的所有行。

所有写操作（建集团、加/移主体、建抵销、删抵销）写 provenance 审计，不写主体账本。

## 六、前端

`frontend/src/components/ConsolidationPanel.tsx` 与 `frontend/src/lib/use-consolidation.ts`：

- 财报页顶部「财报视图」切换，`single` 与 `group` 互斥；合并视图在财报页内部，不新增左侧一级导航。
- 集团选择、期间选择、运行合并、删除集团。
- 主体卡：名称、租户 id、持股、纳入方式、期间状态、单体资产/收入/净利；缺账主体显式提示。
- 纳入主体：可新建企业主体，也可从当前用户的已有租户中选择；`full` 锁定 100%，`proportional` 允许比例。
- 三列对照：单体合计 / 按持股折算 / 抵销后合并；附抵销合计、试算平衡、报表预警。
- 科目底稿表；可导出 UTF-8 BOM CSV。
- 抵销分录列表、两行式新增（借方科目、贷方科目、金额）与删除确认；金额以元输入、按分存储。
- 中英文各补 50+ 条文案。

## 七、演示数据

演示租户 `10000001` 是集团 owner，集团 id `grp_demo`：

- `10000001 演示集团总部`：100% `full`；
- `10000002 演示子公司`：80% `proportional`；
- `10000003 待建账分部`：20% `proportional`，故意不建账，用于展示 `missing`；
- 2026-11 预置一张 `adj_demo` 内部销售抵销：借 `6001` 320 元、贷 `6401` 320 元。

演示重置会清空集团、范围、抵销，并重建 `10000002` 的科目、期间与已过账凭证；`10000003` 保持缺账。总部已有总账时不重复写入。

## 八、验证

- 后端新增 `backend/tests/test_consolidation.py` 7 项：范围校验、重复/越权、100% 限制、合并读取、缺账排除、抵销平衡、空范围、演示种子、成员资格撤销、NaN 持股与小数分拒绝。
- 后端全量：`1942 passed, 1 warning in 316.77s`（4.17.3 基线 1935 项）。
- 前端：34 文件 / 243 项通过（75.47s）；`tsc --noEmit` 通过；`npm run build` 18.53s。
- 浏览器实测：演示集团 3 主体，2 个 `ok`、1 个 `missing`；2026-11 单体收入 411,200、按比例 410,960、抵销后 410,640；抵销合计 320；合并试算借贷各 641,680。
- 新增截图：`167-consolidation-overview.png`、`168-consolidation-entity-form.png`、`169-consolidation-adjustment.png`、`170-consolidation-dark.png`。

## 九、边界与未交付

- 不是法定合并报表，不能用于审计披露或税务申报。
- 不自动识别内部交易；抵销分录必须人工录入，且仅支持简单两行/多行借贷，不做抵销模板与跨期自动结转。
- 不做外币折算；当前所有金额为 CNY。
- 不做 NCI、权益法、合并商誉、合并现金流量表。
- 比例折算的尾差保留为 warning，不自动调平。
- 集团成员上限 20；集团与抵销仅创建者可见，未做多人协同与审批。
