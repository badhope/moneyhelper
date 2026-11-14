# 自检记录（2026-11-11）

范围：本轮安全/数据可信修复后的演示实例，使用隔离数据目录 `.tmp/demo`。
这不是生产验收，也不替代渗透测试或完整代码审计。

## 1. 运行与截图

- 后端：`127.0.0.1:18790`（非默认端口，仅本机），演示数据 4 个持仓、11 条流水。
- 前端：生产构建由后端同端口托管。
- 截图：`frontend/e2e/shots-full.mjs`，桌面 1440×900、移动 390×844，共 22 张。
- 产物：`out/selfcheck-shots/`。
- 自动化检查：无控制台错误、无页面级横向溢出，脚本输出 `all clean`。

## 2. 页面检查结论

### 正常

- 总览：风险待办按紧急度排序；净资产、资产分布、集中度可读。
- 持仓：表格与移动卡片均在视口内；操作按钮可点；盈亏颜色符合中国习惯。
- 记账：一句话记账、导入、持仓/负债/订阅/目标入口完整；流水日期与金额对齐。
- 公司财税：增值税参数与结果分区清楚；1,000,000×13% - 600,000×13% = 52,000，附加 6,240，合计 58,240，复核一致。
- 财报：JSON 输入、字段说明、本地保存空态完整。
- 还债规划：雪崩/雪球对比、预计还清时间、总利息与可省利息均有明确来源。
- 模拟盘：空态说明“先开户再下单”，不会显示误导性的 0 收益。

### 发现并已修复

1. **持仓“占比”口径歧义**：表格 51.8% 是“占总资产”（含现金），风险卡 64.9% 是“占持仓/可投资资产”。两处都叫“占比”容易被误读。
   - 已改为：表格列“占总资产”，集中度卡片“集中度（占持仓）”，风险提示改为“占持仓 64.9%”。
   - 复核截图：`out/selfcheck-shots/v2-desktop-holdings.png`、`v2-mobile-holdings.png`。

### 发现但暂未改

1. **演示数据净资产为负**：总资产约 27.2 万，房贷 128 万 + 信用卡 7,200，净资产 -1,015,153 是正确计算结果，不是 bug；演示数据本身偏“高负债家庭”。
2. **移动端财报 JSON 文本域内部横向滚动**：长 JSON 行被输入框裁切，但可横向滚动，不是页面溢出；企业版建议改为分段表单或自动换行。
3. **总览风险重复**：同一持仓的“标的集中”和“行业集中”拆成两条，信息密度可再优化。
4. **未配置模型时仍显示具体模型名**：聊天页模型选择器显示 `DeepSeek Chat`，底部同时提示“未接入 AI”；建议未配置时显示“未配置”而不是具体模型。

### 组织设置页（切片 3）

- 入口：设置 → 组织架构；桌面截图 `out/selfcheck-shots/org-03-final.png`。
- 实测：新增部门“财务部/FIN”、岗位“会计”，计数从 0 变 1；无控制台错误。
- 修复：租户下拉原来显示“本机账本 · 本机账本 · 所有者”，已去掉本地租户的重复类型；状态 `active` 已本地化为“启用/归档”。
- 边界：租户切换只作用于组织 API；账本仍按登录用户归属，页面已明确提示。

### 总账页（切片 5a）

- 入口：财务 → 算账 → 总账；桌面截图 `gl-01-entries.png`、`gl-02-trial.png`、`gl-03-accounts.png`、`gl-04-periods.png`。
- 移动端截图 `gl-05-mobile-entries.png`、`gl-06-mobile-trial.png`，页面横向溢出 0。
- 实测：2026-11 期间、库存现金/营业收入两科目、一张已过账凭证；试算表借贷各 1,000，显示“借贷平衡”。
- 修复：期间状态下拉曾显示英文 `open`；试算表贷方科目余额曾显示负数（已按科目正常方向展示）；移动端借贷输入曾被拆成两行（改为科目整行、借贷并排、备注整行）。
- 边界：总账页暂无单据来源、审核流与银行对账；只支持手工凭证。

### 报销页（切片 5b）

- 入口：财务 → 算账 → 报销；桌面截图 `expenses-01-desktop.png`、移动端 `expenses-01-mobile.png`。
- 实测：演示库生成 `BX-202611-0001` 上海出差报销 1,280.50，审核通过后生成凭证 `GL-202611-0002`（草稿）。
- 无控制台错误；移动端页面横向溢出 0。
- 修复：本机申请人原来显示 `#0`，已改为“本机用户”。
- 边界：审批通过只生成凭证草稿，过账仍需会计在总账页确认；无付款、银行对账、发票验真。

### 银行对账页（切片 6a）

- 入口：财务 → 算账 → 银行对账；桌面截图 `bank-01-desktop.png`（付款）、`bank-02-desktop.png`（流水），移动端 `bank-01-mobile.png`、`bank-02-mobile.png`。
- 实测：付款 `PAY-202611-0001` 1,280.50，银行支出流水已匹配，汇总显示“已全部匹配”；无控制台错误，移动端溢出 0。
- 修复：付款时间原来直接显示 ISO 字符串，已改为本地日期时间。
- 边界：付款与流水匹配只是勾稽，不自动改总账；对账签核见下节 6b。

### 对账签核（切片 6b，内置浏览器实测）

- 入口：财务 → 算账 → 银行对账 → 对账签核；截图 `bank-03-reconcile.png`、`bank-04-signed.png`。
- 实测：1002 银行存款 / 2026-11，对账单余额 0、账面余额 0、差额 0、无未匹配；点击“签核关账”后状态变为“已签核”，toast 显示“对账已签核”。
- 门禁：差额不为 0 或仍有未匹配流水时后端拒绝签核；差额需先通过总账调整凭证处理。
- 边界：没有自动生成差异调整凭证；付款/流水/对账已纳入 JSON 备份并重映射内部 ID。

### 权限点字典与 Casbin 影子模式（切片 7a）

- 新增权限点字典（`backend/app/authz.py`，17 个权限点 / 6 个域）与 Casbin 影子引擎
  （`backend/app/authz_engine.py`，RBAC with domains，domain = tenant_id）。
- 影子模式**只记录不拦截**：5 个业务域的权限闸统一经 `backend/app/authz_guard.py` 汇报判定，
  `authz_shadow_log` 并排记录“字典判定”与“代码实际是否放行”。
- 各域不再手写角色白名单，改由 `authz.roles_with(permission_id)` 从字典派生。
- 实测（演示实例，demo 账号 = Acme 企业租户 admin）：
  - `GET /api/authz/shadow/summary` → `total=3, allows=3, denies=0, mismatches=0`；
  - `GET /api/authz/status` → `casbin_available=true, points=17, roles=7`；
  - 记录到的权限点：`org:read`、`gl:read`（与字典一致，无差异）。
- 回归里锁死了“影子不拦截”：把 Casbin 判定改成永远 deny，
  `POST /api/org/departments` 仍返回 200，且该次判定被记成 mismatch。
- **影子模式发现并修掉的第一条真实差异**：`viewer`（只读角色）原本也能新建报销单——
  代码按“任意成员”放行，字典按只读拒绝。修法是让实现改用字典派生角色集合，
  不是让影子去拦截。修完后 viewer 建单返回 403，影子不再报 mismatch。
- 新增 `GET /api/org/capabilities`：返回当前用户在当前工作租户的权限点，
  前端据此隐藏写操作入口，避免“按钮能点、点了 403”。

### 全局租户切换（切片 7b，真实浏览器实测）

- 入口：顶栏“工作租户”选择器；截图 `tenant-01-switcher.png`（Acme 科技）、
  `tenant-02-personal.png`（切回个人租户，toast“已切换工作租户”）、
  `tenant-03-enterprise.png`、`tenant-04-viewer-readonly.png`（只读角色）。
- 实测（`frontend/e2e/tenant-switch.mjs`，隔离演示库）：

  | 动作 | 结果 |
  |---|---|
  | 顶栏切换器 | 显示“Acme 科技”，下拉含个人租户与 Acme |
  | 切到个人租户 | `GET /api/gl/accounts` → 空（个人租户没建过科目） |
  | 切回 Acme | `GET /api/gl/accounts` → `["1001","4001"]` |
  | 两种租户下 `GET /api/transactions` | 都含“个人午餐” —— **个人流水不随切换移动** |
  | `GET /api/org/overview` | tenant.id = 7100（Acme） |
  | 影子汇总 | mismatches=0 |
  | viewer 的 `GET /api/org/capabilities` | 仅 6 个读权限点，**无** `expense:create` |
  | viewer 的“保存草稿”按钮 | disabled，并显示“当前角色只读：不能新建或提交报销单。” |

- 无控制台错误。
- 复现：

  ```powershell
  $env:MONEYHELPER_DATA_DIR="D:\Moneyhelper\.tmp\demo-tenant"
  $env:PYTHONPATH="D:\Moneyhelper\backend"
  D:\Moneyhelper\.venv\Scripts\python.exe scripts\seed-demo-tenant.py
  D:\Moneyhelper\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18791 --app-dir D:\Moneyhelper\backend
  cd frontend; node e2e/tenant-switch.mjs http://127.0.0.1:18791 ../out/selfcheck-shots
  ```

  > 演示账号：`demo / demo123456`（Acme 企业租户 admin）、
  > `viewer / viewer123456`（Acme 企业租户 viewer）。
  > 种子脚本会建个人租户 + Acme 企业租户，并把两人的工作租户预设为 Acme。

- 边界：切换只作用于企业域；个人流水按登录用户归属，UI 上以 tooltip 明示。

### 采购/应付最小闭环（切片 8，内置浏览器 + API 实测）

- 入口：财务 → 算账 → 采购应付；截图 `procurement-01-payables.png`（应付单）、
  `procurement-02-orders.png`（采购单）。
- 实测链路（tenant 0，2026-11 期间）：

  | 步骤 | 结果 |
  |---|---|
  | 建供应商 `V001 华东办公用品` | 200 |
  | 建采购单 5,000 元并提交/审核 | `PO-202611-0001`，status=approved |
  | 建应付单（关联采购单，税额 300）并提交/审核 | `AP-202611-0001`，生成凭证草稿 `GL-202611-0001` |
  | 应付付款 | `PAY-202611-0001`，生成付款凭证草稿 `GL-202611-0002`，应付 status=paid |
  | 银行支出流水 5,000 → 匹配付款 | 匹配成功；汇总 matched=1、unmatched=0 |
  | 再次付款 | 400，已付款不可重复 |

- 页面实测：供应商 / 采购单 / 应付单三个标签均正常渲染；应付单显示关联采购单、
  发票号、凭证草稿、付款单号与“已付款”状态；无控制台错误。
- 实测中发现并修掉两处显示问题：日期字段被 `fmtDate` 渲染出伪造的 `08:00`
  （改为 `fmtDay` 纯日期格式）；供应商下拉复用了“选择科目”占位符
  （改为“选择供应商”）。
- 边界：无部分付款、预付款、采购入库/库存、采购退货、多币种；付款与应付都在
  凭证草稿层，过账仍由会计在总账页确认。

### 长任务引擎（切片 10，真实模型实测）

- 入口：财务 → 业务 → 长任务；后端 `/api/longtasks/*`；产物落
  `data/longtasks/<id>/artifacts/`。
- 实测（spark-x2.6-4b，串行执行）：

  | 任务 | 结果 | 总字数 | 耗时 |
  |---|---|---|---|
  | 长篇小说《长夜灯塔》 | done（6/6 阶段） | 15,216 | 961s |
  | Word 季度经营报告 | done（4/4 阶段） | 25,010 | 693s |
  | 论文《生成式 AI 对知识工作的影响》 | done（6/6 阶段） | 29,542 | 1,283s |
  | 个人记账 Web 应用 | 多轮续跑后收敛 | 45,139 | — |
  | CSV 清洗 CLI | 多轮续跑后收敛 | — | — |

- 实测发现并修掉四个真实缺陷：产物文件名中文被正则清空（`01--.md`）；
  任务目录被清后 `_write` 直接 500；单阶段 240s 超时误杀正常产出；
  模型写满 12000 字代码阶段常超 10 分钟 → 加「超时压缩重试一次」。
- 客户端断开不会停服务端执行：重复触发会造成多任务并发写同一目录，
  排障时以 `task.json.updated_at` 与后端进程为准，必要时重启后端清场。

### 容器验证（CI 实跑，本机不允许装容器）

开发机 `docker`/`podman` 均不可用，WSL2 与 Hyper-V 均 Disabled，所以容器验证放在
GitHub Actions 的 `docker` job 里真跑（7 步全 success）：

| 检查 | 结果 |
|---|---|
| `docker build` | 成功 |
| 运行用户非 root | `xia` |
| 源码目录对运行用户只读 | `touch /app/backend/app/x` 失败（符合预期） |
| 数据目录可写 | 成功 |
| 测试依赖未进镜像 | `import cv2` 失败（符合预期，运行时不依赖） |
| 容器健康检查 | `/api/health` 200 |
| 前端静态资源 | `/` 200 |
| 本轮新增 API | `/api/longtasks/templates`、`/api/procurement/vendors`、`/api/org/capabilities` 均 200 |
| 数据卷持久化 | 写入流水 → 重启容器 → 数据仍在 |

## 3. 真实 API 案例

在演示实例上执行，结果如下：

| 案例 | 请求 | 结果 |
|---|---|---|
| 记账写入 | `POST /api/transactions` `{"date":"2026-11-11","item":"自检案例-咖啡","category":"餐饮","amount":-28}` | 200，`id=12`；随后 `/api/transactions` 能查到该条 |
| 零税率增值税 | `POST /api/finance/tax/vat` `{"sales":1000,"purchases":0,"rate":0}` | 200，销项/进项/应纳/附加/合计全部为 0，`method=general@0%` |
| 审计哈希链 | `GET /api/audit/verify` | 200，`{"ok":true,"checked":6,"legacy_rows":0,"head":"c9336569…"}` |
| stdio MCP 防护 | `PUT /api/mcp/servers` 带 `command=cmd.exe` | 400，明确拒绝“避免任意命令执行” |
| 备份字段 | `GET /api/export` | 模拟盘账户/成交/快照、净值快照、家庭议案、再平衡目标、定投计划、财报分析字段均存在 |

### 复式总账案例（切片 4）

- 建科目：`1001 库存现金 / asset`、`4001 营业收入 / income`；
- 开期间：2026-11；
- 录凭证：借 1001 1000 元、贷 4001 1000 元，状态 `draft`，编号形如 `GL-202611-0001`；
- 过账后试算表：借方合计 1000、贷方合计 1000，`balanced=true`；
- 反冲后：原凭证保留，新增 `source=reversal` 的已过账凭证，试算表借贷各 2000，现金余额归零；
- 重复反冲返回 400；关账期间新增凭证返回 400；
- 备份导出→恢复后，总账 4 张表行数一致，试算表仍平衡（内部 ID 已重映射）。

## 4. 自动化回归

- 后端：`1697 passed, 0 skipped`（2026-11-13，补齐 qrcode/reportlab/opencv 后无跳过）。
- 前端：`195 passed`，生产构建通过。
- Playwright E2E：`55 passed`（含采购/应付全链路、设置 24 分区可达 + 22 项配置级验证、财务 16 页遍历），
  `PLAYWRIGHT_CHANNEL=msedge` 复用本机 Edge（Chromium 下载受限时）。
- 统一门禁 `scripts/verify-all.sh`：ruff + 后端全量 + 前端单测 + 构建各层独立失败即停；
  `--with-e2e`/`--with-live` 追加 E2E 与真实模型验收。
- 真实模型验收（spark-x2.6-4b）：50 题题库 `46/50`、加权得分 `91.5%`、0 次调用失败；
  `scripts/verify_live.py` 的模型连通、确定性记账、function calling、多轮追问全部通过；
  复杂多步问题（本月支出 vs 预算、3 年还贷规划）分别正确调用 `get_ledger_view`/`get_budget`
  与 `get_ledger_view`/`get_risk_flags`/`debt_payoff_plan`。
- 新增回归：
  - `backend/tests/test_audit_hash_chain.py`：正常链、改字段断链、删中间行断链、legacy 行跳过。
  - `backend/tests/test_instance_admin.py`：停用 JWT、全停用仍要求登录、实例管理员边界、审计清空默认拒绝。
  - `backend/tests/test_mcp_readonly_policy.py`：未声明只读工具不暴露。
  - `backend/tests/test_backup_completeness.py`：9 张扩展表导出→恢复往返。
  - `backend/tests/test_data_integrity_fixes.py`：更新流水拒绝 Inf、零税率不被默认值覆盖。
  - `backend/tests/test_authz_shadow.py`（切片 7a，16 项）：字典自洽、字典派生角色集合 == 原白名单、
    Casbin 判定与字典一致、影子记录放行与拒绝、**影子不拦截**、影子可关停、
    mismatch 必被标出、只读角色建单被拒、能力接口与字典一致、影子 API 权限边界。
  - `backend/tests/test_tenant_switch.py`（切片 7b，7 项）：显式选择优先于个人租户、
    非成员不能切换、成员资格失效自动回落、租户列表 active 标记、
    **切换只作用于企业域而个人流水不动**、本机模式无可切换租户。
  - `backend/tests/test_procurement_flow.py`（切片 8，5 项）：采购→应付→付款→银行匹配全链路、
    状态机门禁（未审核采购不能生成应付、草稿应付不能付款、科目类型校验）、
    角色权限（会计建单/pay 但不可审核、审批人可审核不可建单、非成员 403）、
    备份恢复含供应商/采购单/应付单并双向重映射 payment_id、
    **旧库 `UNIQUE(tenant_id,claim_id)` 迁移为部分索引**（否则多条应付付款互相冲突）。
  - `frontend/e2e/procurement.spec.ts`：真实 UI 全链路——建供应商 → 建采购单 → 提交/审核 →
    建应付单 → 提交/审核（断言凭证号出现）→ 付款（断言付款单号与已付款状态）。
  - `backend/tests/test_model_eval.py` 补 2 项：部分运行分母只算实跑题（回归 3/50=6.1% 的误报）、
    空 model 参数回填真实模型名。

## 5. 复现方式

```powershell
# 1) 准备隔离数据
$env:MONEYHELPER_DATA_DIR="D:\Moneyhelper\.tmp\demo"
$env:PYTHONPATH="D:\Moneyhelper\backend"
D:\Moneyhelper\.venv\Scripts\python.exe scripts\seed-demo.py

# 2) 起后端（非默认端口）
D:\Moneyhelper\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18790 --app-dir D:\Moneyhelper\backend

# 3) 截图
cd D:\Moneyhelper\frontend
node e2e/shots-full.mjs http://127.0.0.1:18790 ../out/selfcheck-shots
```

> 截图脚本会调用本机 Edge/Chromium；仅访问 `127.0.0.1`。运行结束后停止后端进程，避免残留。
