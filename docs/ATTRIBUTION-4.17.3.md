# 收支归因 4.17.3：规则配置、批量确认与误判回滚

> 版本：4.17.3 · 2026-11-24
> 适用页面：账务 → 报税助手 / 公司财税 → 收支归因
> 边界：规则只产出候选，不自动改账；确认与回滚都必须经过人。

## 一、为什么做

4.17.1 的归因只能使用内置规则表与账本历史。真实账本里总会出现内置词表覆盖不到的商户名，例如「云 GPU 订阅」「社区团购蔬菜」。如果每遇到一个新商户就改代码，规则永远追不上账本。

4.17.3 把规则配置权交还用户，同时保留两条硬边界：

1. 自定义规则只影响**候选**，不会在扫描时改分类。
2. 批量确认是显式人工动作；误判必须能撤回，且撤回不能覆盖后续人工改动。

## 二、规则模型

表 `attribution_rules`：

| 字段 | 含义 |
| --- | --- |
| `tenant_id` / `user_id` | 租户与用户隔离，规则不跨租户共享 |
| `rule_id` | 规则 id，接口返回时使用 |
| `name` | 规则名称，≤40 字 |
| `keyword` | 摘要匹配词，≤30 字；大小写不敏感，支持中文 |
| `category` | 目标分类，≤20 字，不能是「其他」 |
| `direction` | 空 / 收入 / 支出；空表示不限方向 |
| `priority` | -100..100，数值越大越先匹配 |
| `enabled` | 是否启用；停用后立刻退出候选计算 |
| `created_at` / `updated_at` | 审计时间 |

排序规则：`enabled DESC, priority DESC, created_at ASC`。同一笔流水命中多条规则时只取第一条；扫描结果额外返回每条规则的命中数，方便判断规则是否真的有效。

规则分类与内置分类合并后进入下拉候选。内置分类不够用时，前端允许直接输入新分类（例如「办公软件」），但仍受 20 字与「不得为其他」校验。

## 三、确认、回滚与审计

### 批量确认

`POST /api/finance/attribution/confirm-batch` 接收最多 100 条 `transaction_id + category + source + rule_id + confidence`。

处理顺序是先校验全部行，再在一个 `write_txn` 内逐条执行：

1. 流水必须存在；
2. 流水当前分类必须与请求携带的原分类一致；
3. 保存确认行的 `original_category`，供后续撤销使用；
4. 更新流水分类；
5. upsert `attribution_confirmations`。

任何一条失败整批回滚，不允许部分成功。重复 id、分类已变化、分类为空/「其他」/超长、来源不在白名单，都会整批 400。

### 回滚

`POST /api/finance/attribution/rollback` 只在「流水当前分类仍等于确认分类」时生效：恢复原分类、删除 active confirmation、写入 `attribution_rollbacks` 证据。若用户确认后又手工改过分类，回滚返回 400，避免把后续人工判断覆盖掉。

`attribution_rollbacks` 不物理删除，保留 `original_category`、`confirmed_category`、`source`、`rule_id`、`reverted_at`，用于回答「这笔为什么改过、又为什么改回来」。

### 统计

`GET /api/finance/attribution/stats` 按来源与规则聚合「确认数 / 回滚数」。规则卡片的「累计采纳 / 回滚」来自同一统计，不另算一套口径。

## 四、接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/finance/attribution/rules` | 规则列表、分类候选、采纳/回滚统计，最多 20 条 |
| POST | `/api/finance/attribution/rules` | 新增规则 |
| PUT | `/api/finance/attribution/rules/{rule_id}` | 修改规则 |
| DELETE | `/api/finance/attribution/rules/{rule_id}` | 删除规则 |
| POST | `/api/finance/attribution/rules/test` | 用现有规则或临时规则测试一笔摘要 |
| GET | `/api/finance/attribution/confirmed?limit=` | 最近确认明细，含原分类与新分类 |
| POST | `/api/finance/attribution/confirm-batch` | 批量确认，最多 100 条，原子写 |
| POST | `/api/finance/attribution/rollback` | 撤销单笔确认 |
| GET | `/api/finance/attribution/stats` | 来源 / 规则维度统计 |

所有接口沿用 `X-Demo-Mode: 1` 演示隔离；演示重置会清空 `attribution_rules`、`attribution_confirmations`、`attribution_rollbacks`，避免 4.17.2 遗留的旧确认数穿透到新演示账本。

## 五、前端

- **规则设置**折叠区：规则列表、启用/停用、编辑、删除、新增；关键词 → 分类、方向、优先级；「测试」直接返回命中的分类与置信度。
- **批量工具栏**：行级复选框、本页全选、清除、已选数量；选中行缺少分类时禁用批量确认并提示原因。
- **最近确认**：显示原分类 → 新分类、来源、确认时间；每行有「撤销归因」，二次确认后执行。
- **缓存失效**：归因域的查询键都以 `/api/finance/attribution` 开头，统一用 predicate 前缀失效。不能只传 `queryKey: ["/api/finance/attribution"]`，React Query 按元素相等做前缀匹配，不会命中更长的键。

## 六、测试与实测

- 后端定向：`backend/tests/test_finance_timeline.py` 4 项通过；覆盖规则创建/测试/停用、批量确认原子性、回滚与二次回滚 400、演示重置清空。
- 后端全量：`1935 passed, 1 warning in 246.84s`。
- 前端：34 文件 / 243 项通过（68.45s）；`tsc --noEmit` 通过；`npm run build` 18.20s。
- 浏览器实测：创建「云资源」规则（关键词「云 GPU」→「办公软件」，支出，P10），扫描命中 1 笔；批量确认 2 笔后规则累计采纳 1、确认列表出现 2 条；撤销「深夜打车回家」后回滚徽标变为 1，该流水回到候选池。

## 七、仍然是边界

- 规则只匹配摘要关键词，不做正则、金额区间、账户维度或商户 ID 匹配。
- 没有规则版本历史；删除规则不回溯已确认记录，回滚证据仍保留。
- 批量确认最多 100 条，单次请求不跨租户。
- 不自动学习用户选择，不根据历史确认自动生成规则；规则必须显式创建。
- 没有外部消息通知；规则与确认只在站内可见。

## 八、截图

- `docs/screenshots/164-attribution-rules.png`：规则卡、启用状态、扫描命中与批量工具栏。
- `docs/screenshots/165-attribution-batch-confirm.png`：批量确认 2 笔后的确认列表与「已批量确认 2 笔」。
- `docs/screenshots/166-attribution-rollback.png`：撤销 1 笔后回滚徽标、候选回流与最近确认。
