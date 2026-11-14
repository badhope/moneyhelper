# Changelog

项目版本号与发布历史。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，版本语义遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [4.16.0] - 2026-11-14

### 摘要

企业化切片 8-10：采购/应付闭环、代理安全边界（程序不能自己改掉）、长任务引擎；
财务工作区导航重构为「业务 / 账务」两层；测试门禁补齐到 1717 + 195 + 33 且零跳过。

### 企业化切片 10：长任务引擎（分段执行 + 断点续跑 + 产物落盘）

- 新增 `backend/app/longtask.py` 与 `/api/longtasks/*`：把"百万字小说、完整网页、
  Word 报告、论文、程序开发"这类大任务拆成阶段逐段执行。
- 每阶段一次模型调用，输入=任务目标+已完成阶段摘要+本阶段要求；产物落
  `data/longtasks/<id>/artifacts/`，阶段状态/字数/错误实时可查。
- 单阶段失败只影响该阶段：状态记 failed 并继续后续；再次 run 只补未完成阶段。
  进程中断留下的 running 任务 10 分钟未更新自动重置（可续跑）。
- 韧性：单阶段超时后自动压缩重试一次（字数上限压到 1/3）——推理型模型写
  12000 字代码阶段实测常超 10 分钟，压短提示词比放大超时更可靠。
- 防失控：阶段数 ≤40、单阶段 ≤12000 字、任务总时长 ≤1 小时，超限跳过并标注。
- 前端新增「业务 → 长任务」页：建任务、执行、取消、按阶段展开产物。
- 写操作要求实例管理员（长任务消耗模型额度并写文件）；测试 12 项全绿。
- 真实模型实测（spark-x2.6-4b）：小说 15216 字、Word 报告 25010 字、论文 29542 字
  三个任务完整跑通；代码类任务的长阶段在压缩重试后收敛。

### 安全切片 9：程序不能被自己改掉（6 项真实漏洞修复）

- 权限自升：`PUT /api/studio/permissions` 此前无管理员校验，缺省 mode 还会隐式
  升到 open；现在必须实例管理员，且单开 `allow_chat_admin` 必须显式提交
  `mode=open`，非法模式 fail-closed 回落 standard。
- 全局配置写：`POST /api/agent-config`、`POST /api/skills/{id}/run` 要求实例管理员；
  `PUT /api/settings` 的 custom_system_prompt / ai_base_url / ai_model 三个键
  要求实例管理员（普通偏好不受影响）。
- 内置安全 Hook 不可停用：拦截命令执行/文件写入/审计写操作的 Hook 此前一句
  "停用 Hook" 就能关掉；现在停用直接 403。
- `parse_invoice` 会写 invoices 表，此前被误标只读直通；现固定为必须确认。
- 备份恢复 settings 改为白名单：studio_config / agent_config / custom_system_prompt /
  ai_base_url / ai_model 不再能被备份文件写回；恢复的 MCP 地址重新过 SSRF 校验，
  打码凭据剥离后由用户重填；恢复动作清空本机 ai_api_key（备份可能来自别机）。
- MCP stdio 收口：`save_servers`/`set_server_enabled`/`_open_session` 三层统一
  校验 MONEYHELPER_ALLOW_STDIO_MCP；stdio 的 cwd/args 指向源码目录直接拒绝；
  独立 MCP Server 默认绑 127.0.0.1（此前 0.0.0.0 无鉴权）。
- 新增 `backend/app/pathguard.py`：数据目录/数据库不允许指向源码、.git、依赖清单；
  最高权限需显式 `MONEYHELPER_ALLOW_SYSTEM_ACCESS=1`。回归测试 8 项
  （tests/test_security_boundaries.py）。

### UI：导航重构与三处真实渲染缺陷修复

- 设置页改两级折叠导航：先选分组再进分区，移动端不再 24 个 pill 一条横滚。
- 财务主区导航拆「业务 / 账务」两组，形成 报销/采购 → 总账/银行 → 报表/税 的工作流顺序。
- 采购页三个新建表单默认折叠，列表优先；表单 label 与控件显式关联（可访问性）。
- 修复：ECharts 在 0 尺寸容器上 setOption 抛错（切页瞬间可见）；
  treemap/radar 模块未注册完成就 setOption 的竞态；
  `fmtDay` 纯日期字段不再显示伪造的 08:00。
- 新增 E2E：设置 24 分区逐个点开、财务 16 页逐个点开，断言零页面异常
  ——导航重构后"某页不可达"这类只有用户才会发现的问题有了门禁。

### 安全加固（续）：远程安装重定向 SSRF

- `fetch_remote_text` 原用 `follow_redirects=True`：SSRF 校验只查首跳 URL，
  攻击者控制的公网地址可 302 到 `169.254.169.254` / 内网段绕过检查。
  改为手动跟随、每跳重新 `assert_public_http_url`（含 DNS），上限 3 跳。
- 新增 `backend/tests/test_remote_install_ssrf.py`（2 项）：重定向到内网必须在
  校验处被拒且不发出第二跳；非 http(s) scheme 直接拒绝。
- Dockerfile：运行用户不再拥有源码目录（原 `chown -R xia:xia /app`），
  仅 `backend/data` 与 `backend/logs` 可写，源码/前端产物归 root 只读。
  本机无 Docker，镜像构建未验证（已在路线图标注）。

### 工具链：发版与推送

- `scripts/release.sh` 不再硬编码 `python3`：Windows 没有该命令，脚本会在改完文件后
  中断在 commit 一步（实测）。现优先用项目 venv，再按 `python3 → python → py` 探测。
- `scripts/push_via_api.py` 新增 `--incremental`：对比远端 tree 只上传变化 blob
  （690 文件全量 ×3 镜像易撞 secondary rate limit；实测增量后每次 152 个），
  推送后校验远端 tree == 本地 HEAD tree，不一致立即报错。

### 测试门禁：跳过清零 + E2E/真实模型验收

- 补齐可选依赖 `qrcode[pil]`、`reportlab`、`opencv-python-headless`，后端测试从
  `1689 passed / 6 skipped` 变为 `1695 passed / 0 skipped`（二维码、PDF、发票解码用例不再跳过）。
- 修复 `scripts/e2e-backend.sh` 与 `scripts/lint.sh` 只探测 `backend/.venv` 的问题：
  本项目 venv 在仓库根，旧逻辑会静默回退到系统 Python 3.15 并报“uvicorn 未安装”。
- `playwright.config.ts` 支持 `PLAYWRIGHT_CHANNEL=msedge|chrome`，在 Chromium
  二进制下载受限的机器上复用本机浏览器；默认行为不变。E2E `30/30 passed`。
- 真实模型验收（spark-x2.6-4b）：50 题评测 `46/50`、`91.5%`，0 次调用失败；
  `verify_live.py` 的记账、function calling、多轮追问全部通过。

### 修复：评测部分运行与模型名

- `max_questions=N` 调试模式此前只跑 N 题，但判分分母仍是全部 50 题，
  3 题全对会被显示成 `3/50 = 6.1%`。`score_answers` 新增 `only_ids`，
  分母只统计实际跑过的题。
- 评测结果里的 `model` 此前恒为 `"default"`，排行榜无法区分模型；现回填配置中的真实模型名。

### 企业化切片 8：采购/应付最小闭环

从"报销付款"扩到"供应商付款"，补上企业采购到付款的最小链路：
供应商档案 → 采购单 → 应付单 → 付款 → 银行流水匹配。

### 新增：采购/应付域

- 新表 `vendors` / `purchase_orders` / `payables`；金额仍存整数分。
- 采购单状态机 `draft → submitted → approved`，审核只代表采购获批，**不生成总账凭证**。
- 应付单状态机 `draft → submitted → approving → approved → paid`：
  审核生成「借费用/资产、贷应付」凭证草稿；付款生成「借应付、贷银行」凭证草稿。
  过账仍由会计在总账页确认，审批与付款都不直接改已过账账务。
- 付款复用 `payments` 表：`claim_id=0` + `payable_id` 标识应付付款，
  `gl_entry_id` 记录付款凭证；银行流水匹配逻辑不需要区分两类付款。
- 权限点新增 7 个：`procurement:read/write/approve`、`payable:read/write/approve/pay`；
  会计可建单/付款但不能审核，审批人可审核但不能建单（职责分离）。
- 前端新增「财务 → 算账 → 采购应付」页（供应商/采购单/应付单三个标签），
  按钮按 `/api/org/capabilities` 禁用；付款记录与银行页显示应付单号。
- 备份恢复纳入 3 张新表，并处理 `payables.payment_id ↔ payments.payable_id`
  的循环引用：先恢复应付与付款，再回填 `payment_id`。

### 修复：旧库升级与日期显示

- **旧库启动会失败**：`SCHEMA` 里给 `payments` 建的部分索引引用了新列 `payable_id`，
  老库还没补列时 `executescript` 直接报 "no such column"。
  两个部分索引统一移到 `_migrate_add_columns()` 在补列之后创建。
- 旧库原 `UNIQUE(tenant_id,claim_id)` 必须替换为 `WHERE claim_id > 0` 的部分索引，
  否则所有应付付款都以 `claim_id=0` 互相冲突；新增迁移回归测试锁住。
- 纯日期字段（采购日/发票日/到期日）此前用 `fmtDate` 显示成 `08:00`，
  新增 `fmtDay` 只显示日期；供应商下拉不再复用"选择科目"占位符。

### 企业化切片 7：权限点字典、Casbin 影子模式、全局租户切换

延续切片 1-6b 的企业底座与财务闭环。本轮把"权限"和"租户"两件事从
"散落在各模块的条件判断"变成"有唯一定义、可验证、可审计的东西"。

### 新增：权限点字典（`backend/app/authz.py`）

- **权限点之前只存在于 5 个路由模块的角色白名单里。** 同一个"谁能过账"的问题，
  要翻遍 `org.py` / `gl.py` / `expenses.py` / `banking.py` 才能答；
  新增一个域或调整一个角色时，没有一处能说清全貌。
- 新增 17 个权限点（`<域>:<动作>` 形式，覆盖组织/总账/报销/付款/银行流水/对账 6 个域）
  与角色 → 权限点映射。未知角色、未知权限点一律 fail-closed。
- **角色 → 权限点改为从字典派生**（`authz.roles_with`），各业务域不再手写角色白名单。
  回归测试 `test_derived_role_sets_match_previous_hardcoded_lists` 锁死
  "派生结果 == 原白名单"，防止以后调字典时无声地改变某个域的准入角色。

### 新增：Casbin 影子模式（`backend/app/authz_engine.py`）

- 按路线图选型接入 PyCasbin（RBAC with domains，domain = tenant_id），
  在真实请求上跑同一套策略，**只记录不拦截**：
  `authz_shadow_log` 并排记录"字典判定"与"代码实际是否放行"，
  `mismatch=1` 即两者不一致——这是切到拦截之前必须先修掉的清单。
- casbin 缺失 / 模型解析失败 / 写库失败一律降级，**业务路径完全不受影响**。
  回归里把 Casbin 判定改成永远 deny，`POST /api/org/departments` 仍返回 200。
- 5 个业务域的权限闸统一经 `backend/app/authz_guard.py` 汇报判定，
  漏记一处就等于该权限点没覆盖。
- 新增 API：`GET /api/authz/permissions`（字典）、`GET /api/authz/shadow`（判定流水）、
  `GET /api/authz/shadow/summary`（不一致汇总）、`DELETE /api/authz/shadow`、`GET /api/authz/status`。
  读接口走 `require_instance_admin`。
- 开关：`MONEYHELPER_AUTHZ_SHADOW=0` 整体停用影子（业务照常）。

### 修复：只读角色能新建报销单

- 影子模式发现的**第一条真实差异**：`viewer`（只读角色）也能新建报销单——
  实现按"任意成员"放行，字典按只读拒绝。
  修法是让实现改用字典派生的角色集合（不是让影子去拦截）：
  现在 viewer 建单返回 403，并给出"需要该租户的审核权限"以外的正确提示。
- 前端同步：`GET /api/org/capabilities` 返回当前用户在当前工作租户的权限点，
  报销页据此禁用"保存草稿"并显示"当前角色只读"提示，
  不再出现"按钮能点、点了 403"。

### 新增：全局租户切换（切片 7b）

- **企业租户以前进不去。** `resolve_tenant_id()` 优先个人租户（id == user_id），
  既是员工又是企业成员的人永远落在个人租户上，组织/总账/报销/付款/对账
  全部只能看到自己那一份。组织设置页虽然有租户下拉，但只作用于组织域。
- 新增 `users.active_tenant_id` 记录用户显式选择的工作租户，
  映射优先级改为「显式选择 → 个人租户 → 有效成员资格」。
  成员资格失效后显式选择自动回落，不会把人留在看不见的租户。
- 顶栏新增「工作租户」选择器（`frontend/src/components/TenantSwitcher.tsx`），
  切换后财务工作区整体重建以重新取数。
- **边界（已在 UI 上明示）**：切换只作用于企业域（组织/总账/报销/付款/对账）；
  个人流水（记账/总览/持仓）仍按登录用户归属，不随切换改变。
- 真实浏览器实测（`frontend/e2e/tenant-switch.mjs`）：切到个人租户后总账科目为空，
  切回企业租户后出现该企业的科目，两种租户下个人流水都在。

### 文档

- 新增 `docs/LEDGER-TENANT-STRATEGY.md`：现有账本的 tenant_id 映射与双写评估。
  **结论：暂不做双写、暂不做账本迁移**，而是显式划界——
  个人理财域永远属于登录用户，企业财务域永远属于当前工作租户。
  迁移的前置条件（法人/账套模型、复合主键去键、家庭共享语义）尚未满足，
  强行双写会造出"两个真相"。

## [4.15.1] - 2026-11-09（审计第二轮：税负引擎与账单解析）

延续 4.15.0 的筛选标准——**结果错但接口不报错**。这一轮查的是钱进出的两端：
税怎么算、账单怎么读。共修 9 处，新增 40 项回归测试；后端 1615 passed / 0 failed，
前端 189 passed、tsc 零错、build 成功。

### 修复：工资核算与税负（`calculations/tax.py`）

- **实发工资少扣了一个月的税。** `payroll(months=N)` 的 `income_tax` 是累计预扣口径
  （累计应预扣 − 已预扣），`net_pay` 却把它整个减在**一个月**的应发上。实测月薪 3 万、
  `months=3`、`already_withheld=0`：`income_tax=2955`（三个月累计），`net_pay` 报
  **20295**，而该月正确实发是 **21425**。前端「实发工资」卡片就这么错了，
  且没有任何字段说明这是累计口径。现拆成四个字段各归其位：`income_tax`（累计申报）、
  `current_month_tax`（当月应预扣）、`net_pay`（单月实发）、`period_net_pay`（N 个月合计实发），
  `months>1` 时补一条 note 说明关系；已传 `already_withheld` 时当月税就等于 `income_tax`
  （那本来就是当月数）。前端工资核算面板同步补 `months` 输入——此前写死 1，
  累计口径根本用不到。
- **公积金基数被社保上限压住。** 函数自己的 docstring 写着「公积金基数可单独指定
  （常见上限高于社保）」，实现却和社保共用一个 `base_max`：传 `housing_base=50000`、
  `base_max=35000`，实际按 35000 计，只在 notes 里留一句钳制提示。新增
  `housing_base_min` / `housing_base_max`（默认沿用社保口径，不传行为不变），
  路由与 MCP 工具同步暴露。
- **基数区间倒置被静默接受。** `base_min > base_max` 时 `min(max(...))` 退化成 `base_max`，
  于是提示文案写「按 [35000, 3500] 钳制为 3500」——基数与解释互相矛盾。改为直接 ValueError。
- **免征分支返回结构不一致。** `vat()` 走免征时不返回 `surcharge_detail`，
  消费方（MCP / 报表导出 / 前端明细行）必须为"免征"单开一条分支。补齐为三项 0.0。
- **不存在的月份能建清单。** `month_end_checklist` 只校验长度与分隔符，`"2026-13"`、
  `"2026-00"` 照样生成 12 项清单，记录挂在不存在的月份上、之后按月查询永远查不到。
  补月份范围校验。

### 修复：账单解析（`import_parsers/`）

- **金额的符号会丢。** `_parse_amount` 只认前导负号：会计负数 `(1,234.56)` 解析成
  **+1234.56**、尾随减号 `100.00-` 解析成 **+100.00**。银行对账单里一笔支出导入后
  变成收入，账目直接反了且不报错——这是导入链路里最贵的一类错。现支持半角/全角括号负数、
  尾随减号；并按「`.` 与 `,` 同时出现时靠后者为小数点」解析欧式小数逗号
  （`1.234,56` → 1234.56，旧实现给出 **1.234**，差三个数量级）。
- **缺「收/支」列时静默导入 0 笔。** 微信/支付宝解析器把空方向值当"不计收支"跳过，
  于是缺列（或表头被改过）时每一行都命中跳过分支：导入"成功"、0 笔、0 条错误，
  用户以为账单是空的。现缺列直接报错回话；方向值非空但无法识别的行单独计数并进 errors
  （整批都命中通常意味着传进来的不是账单明细）。
- **报错行号指向错误的行。** 解析前 `[r for r in reader if r]` 过滤了空行，行号整体前移；
  微信/支付宝还手工 `row_num += 1` 多加一次（首条数据行报成表头 +3）。
  用户按「第 N 行」去核对，查到的是另一笔交易。现保留原始行、
  用 `enumerate(data_rows, start=header_idx + 2)` 得到真实行号，三个解析器口径一致。
- **0 元流水被塞进账本。** `generic_csv` 在单一金额列取到 0 时就认定 `has_amount`，
  而银行常见排版是「金额列恒为 0 + 借方/贷方分列」，结果每行都以 0 元入库。
  现金额为 0 视为该列本行无值，继续走借贷分列，仍拿不到才报错。

### 测试

新增 `backend/tests/test_audit_regressions_v416.py`（40 项）：金额符号 12 个参数化用例、
括号负数端到端落到支出、方向列缺失时微信与支付宝都必须报错而非静默 0 笔、
无法识别方向要计数、含空行文件的报错行号、金额列恒为 0 时走借贷分列、全 0 行不入库、
`months=1/2/3/6/12` 下 `net_pay` 恒为单月实发且 `period_net_pay` 覆盖整个期间、
传 `already_withheld` 时当月税等于 `income_tax`、公积金基数可高于社保上限、
区间倒置被拒、免征分支结构一致、非法月份被拒。

## [4.15.0] - 2026-11-09（全量审计：修掉 9 个"算错但不报错"的缺陷）

这一版没有新功能。做了一轮定向审计，专挑**结果错但接口不报错**的缺陷——
它们比崩溃更危险：崩溃会被测试和用户发现，算错只会安静地给出一个
看起来很专业的错误数字。修掉的 9 处全部补了回归测试（新增 37 项：
后端 32 + 前端 5），后端 1571 passed / 0 failed，前端 189 passed。

### 修复：技术指标（`calculations/technical.py`）

- **RSI 方向反了。** `avg_loss == 0`（区间内没有一根下跌）时旧实现按 RS=0
  计算，单边上涨 60 根得出 **RSI 0.00**，并触发「深度超卖」买入信号。
  RSI 的正确边界是 100（无下跌）/ 0（无上涨）/ 50（价格纹丝不动）。
  这是本轮最严重的一处：它不是精度问题，是把最强的一段行情判成最该抄底。
- **信号截断留下的是最不重要的 12 条。** 旧写法
  `signals.sort(重要度升序)[-12:]`，实测 300 根日线里 MA_CROSS /
  MACD_CROSS / KDJ_CROSS / BOLL_BREAK 全部被丢弃，只剩 RSI_OVER 与
  VOL_SURGE，多空倾向 `bias` 于是由噪声决定（同一份行情判成 bear，
  实际应为 bull）。改为按「重要度 + 新近度」选取，输出仍按时间升序。
- **残缺 K 线让投研接口 500。** `kdj()` 直接 `float(p["high"])`，
  而行情层只保证 `close` 非空——停牌/新股的 high/low 是 `"-"` 占位。
  现跳过残缺行并保留上一根 K/D，一条脏数据不再拖垮整条指标。
- **并行序列错位。** `closes` 过滤了 None，`dates`/`volumes` 没有，
  一旦有残缺行，所有 `ma[i]`/`dates[i]` 整体错开一格且无任何提示：
  信号挂到错误的日期上，图表日期轴与净值轴对不上。新增 `clean_points()`
  在进指标层前统一清洗一次，各序列长度天然对齐。
- **放量判据自相矛盾。** 5 日均量把当天成交量算了进去，实际阈值被抬到
  「前四日均量 × 2.67」，与文案「5日均量×2」不符。改为只用当日之前的 5 根。

### 修复：回测（`calculations/backtest.py`、`strategies.py`）

- **盈亏比恒为负。** 分母用的是负收益率之和，实测胜率 80%、平均盈利 5.74% /
  平均亏损 12.62% 的组合报出 `profit_factor = -1.82`，前端原样显示成
  「盈亏比 -1.82」，读起来像策略在稳定亏钱。改为 Σ盈利 ÷ |Σ亏损|。
- **首价为 0 直接 500。** 买入持有基准以 `closes[0]` 作分母，停牌/退市/
  脏数据留下的 0 会让 ma_cross 与 dca 抛 ZeroDivisionError。新增
  `prepare_series()` 统一剔除非正价格；`strategies.py` 三处基准曲线也收口到
  `_benchmark_curve()`——此前 `_benchmark()` 已挡 0、曲线部分却裸除，
  同一份数据一半返回 None 一半 500。
- **`fast >= slow` 给出一份语义相反的报告。** 快线周期不小于慢线时
  「多头排列」判据反向，跑的是均值回归，但输出格式与正常回测完全一样。
  现在引擎抛 ValueError、路由返回 400、MCP 工具返回可读错误；
  前端输入框联动，用户调不进这个区间，参数非法时也不发必然失败的请求。
- **closes 与 dates 不同步过滤。** 各调用点都是「过滤 closes、不过滤 dates」，
  曲线日期轴与净值轴错开一格、`trade.date` 指向错误的交易日。
  统一改用 `series_from_points()`（research / paper / MCP 工具共 6 处）。
- **定投笔数虚报。** `trade_count` 数的是「计划投入次数」，跳过非正价格日时
  与 `total_invested ÷ invest_amount` 对不上。改为实际成交笔数。

### 修复：债务清偿（`calculations/debt_payoff.py`）

- **余额为 0 的负债凭空造钱。** 计算「已结清负债释放出的月供」时遍历了
  全部负债，于是用户填进来的 `balance=0` 条目（已结清车贷、已销卡）
  从第 1 个月起就把它的月供当成可支配现金灌进还款池。实测：1 万元 18%
  信用卡、月供 300，多加一条 balance=0 / 月供 2000 的记录后，
  还清时间从 **47 个月变成 5 个月**、总利息从 3967 变成 423，
  而 `monthly_budget` 仍显示 300——既多出不存在的钱，又与自身声明的预算矛盾。
  现只统计「起始就欠着、后来结清」的债，雪球效应本身不受影响。
- **`warning_codes` 与文案不同源。** 只要 `warnings` 非空就一律打上
  `negative_amortization`，于是「跑满 50 年仍未还清」会被前端 i18n 翻译成
  「月供不足以覆盖利息」，界面结论与后端结论文案互相矛盾（前端只认 code）。
  改为文案与 code 在同一处成对写入，并补测试断言两者长度恒等。

### 修复：日志尾部读取（`logging_utils.py`、`studio/watchdog.py`）

`read_log_lines()` 用 `seek(size-200KB) + read()` 取尾部，两种情况会抛
OSError：文件在 seek 之后被 truncate（`clear_logs` 就会清空日志）、
底层文件系统不支持越过 EOF 的随机读（FUSE / 网络盘 / 对象存储挂载返回
EINVAL 而不是 `b""`）。异常一路冒到路由层，把 `/api/logs`、看门狗一键自检、
`/api/studio/diagnostics` 全部打成 500——而 watchdog 的 docstring 明确写着
「避免监控本身成为故障源」。日志读不出来只是看不到历史，不是故障：
现降级为空列表，`_scan_logs()` 再加一道兜底。

这也是 `test_endpoint_health` 4 个用例在部分环境下必红的根因（本地与 CI
结论不一致），修完全量套件 0 failed。

### 测试

新增 `backend/tests/test_audit_regressions.py`（32 项）与
`frontend/src/lib/use-research.test.ts`（5 项）。用例一律断言可观测结果
（数字、日期、code、序列长度）而不是实现细节，重构只要口径不变就不该红。

## [4.14.0] - 2026-11-06（债务清偿规划 / README 英文主版 / 仓库收口）

### 新增：债务清偿规划（雪崩法 / 雪球法 / 自定义顺序）

负债此前只参与两个用途——算 DTI、算月供合计。用户真正要决定的是
「多出的 800 块先还给谁、几月能清、能省多少利息」，这需要逐月摊还模拟。

`calculations/debt_payoff.py`：

- **雪崩法**（按年利率降序）：数学上总利息最低；
- **雪球法**（按余额升序）：先清小额换取正反馈，总利息通常略高；
- **自定义顺序**：自己排优先级，未列出的排到最后，不丢数据。

口径写死在实现与输出里：月复利（余额 × 年利率 ÷ 12，四舍五入到分）；
已结清负债的**月供并入额外还款池**（这正是雪球效应的真实来源，早先版本
把释放额度算成"结清即消失"，还款时间会偏长）；月供盖不住当期利息时
**立即停止模拟并返回 `debt_free_date: null`**，而不是输出一个"永远还不完
但看起来像计划"的假结果。

新增端点 `GET|POST /api/finance/debts/payoff`，`POST` 支持 `compare: true`
一次返回两种方法的月数与总利息差额。MCP 与 agent 工具同步新增
`debt_payoff_plan`（第 63 个 MCP 工具）。

前端新增「还债规划」页：结论四卡（还清日期 / 总利息 / 可省利息 / 额外投入）、
两方法对比、逐笔负债表、还清时间线。移动端结论卡改两列——
原四行纵向铺满会把最关键的「还清日期」推出首屏。

### 新增：输入防抖

`lib/use-debounced-value.ts` + 3 项测试。真实成本不是 setState，而是它触发的
请求：每敲一个字符发一次，后到的旧响应还会覆盖新结果。额外还款额输入
停 400ms 才查询；方法对比与主计划分成两个 query，参数变化时各自重取，
不会出现「对比块还显示上一次数字」。

### 变更：默认亮色

首次打开不再跟随系统深色。主场景是白天记账/看盘，跟随系统会让夜间
浅底转深底后涨跌色对比整体变暗。用户手动切换过则仍走 localStorage；
「跟随系统」保留为设置里的第三项。

### 修复：CI 连续 10 个提交全红（ruff 门禁）

`backend/requirements.txt` 把 ruff 锁在 `>=0.8,<1`：ruff 每版都扩充规则集，
上游发版后 CI 在**代码没变**的情况下开始失败——2026-11-03 起连续 10 个提交
`CI / backend` 全红，只有 ruff 这一步挂，pytest 与前端都过。

两层修复：
- 代码层面清掉 85 处（35 处 printf 格式化、18 处 import 排序、9 处多余
  `# -*- coding: utf-8 -*-`、6 处未使用导入等），其中 3 处是真缺陷：
  `db/_core.py` 在函数体内 `import weakref` 却用 `weakref.X` 写注解（F821），
  `decisions.py` / `strategies.py` 各有一个赋值后从未使用的变量，
  `routes/paper.py` 用 `raise ... ` 未带 `from` 吞掉原始异常链。
- 门禁层面 `ruff==0.17.3` 锁死版本，CI 步骤先打印版本号——
  门禁必须可复现，否则「变红」不携带任何代码质量信息。

### 修复：仓库与文档不一致

- `server.json` 版本长期停在 4.8.0（MCP Registry 清单落后 6 个 minor），已对齐；
- `docs/PROGRESS.md`（自称唯一进度真源）停在 4.8.0 / 2026-10-31，已补到 4.14.0；
- 删除误提交的空文件 `Response` 与 `.monkeycode/`（工具产物，不属于项目）；
- 删除 CHANGELOG 中重复且丢失行内代码的 4.13.2 段落；
- `build.spec` 不收集 `backend/app/**/*.json|*.md`：打包版每次启动刷
  30 行 `default_pack_broken`，Studio 内置角色/技能/约束全部缺失（服务能起、功能是空的）；
- `launcher.py` 忽略 `PORT` 环境变量（文档与 `run.py` 都支持），且非数字 PORT 直接崩栈；
- `studio/store.py` 的 `upsert_asset` 在锁外分两次读改写（清墓碑 + 写入），
  12 并发随机丢 1 条且 gather 无异常——这是挂了多轮的
  `test_concurrent_writes_do_not_lose_data` 的真正根因，已整段持锁并补反证测试。

### 变更：README 英文主版

`README.md` 改为英文主版，`README.zh.md` 为中文版，`README.en.md` 保留为重定向。
内容按「安装 → 能做什么 → 数字为什么可信 → 设计原则 → 架构 → 验证 → 边界」重排，
删掉营销段落。截图全集重拍至 `docs/screenshots-v4.14/`（22 张，新增还债页）。

### 修复：独立评审抓出的 13 个缺陷（含 5 个会显示错数字的）

首版实现自测全绿，外部只读评审逐条复现后抓出：

1. **「可省利息」被低估约一半**：对照基线也重投了释放出来的月供，且随排序方法变化
   （雪崩 8236 / 雪球 2644）——同一个客观事实给出两个数，自证口径不成立。
   改为 `reallocate_freed=False`，基线恒等于「只付最低」。
2. **可行方案被判「还不完」**：基线的负摊还告警被并进主方案 warnings，
   一份 75 个月能还清的计划显示「按当前预算无法还清」。
3. **同月结清误报负摊还**：用「当期总还款 vs 当期总利息」判定，某笔债当月还完、
   实付被余额压低（500+100=600 < 利息 750）就报错，实际月供 1100 完全够。
   改为按「当月总余额是否上升」判定。
4. **重名负债静默吞本金**：两笔都叫「信用卡」时按名字做 dict，1.5 万本金只剩 5000。
   改为显式拒绝重复名称。
5. **一方不可行时的对比结论是反话**：拿跑满上限的部分利息去减，得出
   「雪球法少付 11 万」。改为 `comparable: false` + 不给差额。
6. 月供大于余额的差额被丢弃（逐月明细实付 ≠ 月供合计，方案偏长）→ 当期退回还款池。
7. 路由只捕获 ValueError，`balance: [1]` / `10**400` 漏成 500 → 统一 400。
8. 空串/空列表被 `or 0` 静默当 0（显示「这笔债已还清」）→ 显式拒绝。
9. `debt_payoff_plan` 未登记进 `READONLY_TOOLS` → 模型永远调不到（CHANGELOG 却写着已上架）。
10. `delete_asset` / `set_enabled` 的 roles/skills 分支仍在锁外读改写（与 upsert 同类）。
11. 前端查询时整页换骨架 → 输入框被卸载失焦（实测打字中断）。
12. `compare` 返回 `available: false` 时读 `avalanche` 会崩。
13. 记账后还债页缓存不失效（staleTime 内切回看到旧数字）。

另外：不可行方案原本在对比卡显示「月数 1 / 总利息 ¥9,758」，会被读成「1 个月还清」，
改为显示「—」；`schedule_months` 在未收集明细时返回 0（会被读成零个月），改为省略该字段；
逐月明细默认不返回（50 笔 × 600 月实测 1.16MB，每次改数字重传），改 `include_schedule=true` 按需取。

### 验证

后端 **1540 tests**（新增 52 项债务引擎与端点测试：口径、输入卫生、端点契约）；
前端 **184 tests**（新增 14 项：页面行为 11 + 防抖 3）；tsc 零错误；build 成功；
22 张截图桌面/移动双端零 pageerror、零 console error、零横向溢出；
浏览器实测「改数字后输入框不失焦、可连续输入」与负摊还告警路径。

## [4.13.4] - 2026-11-06（敌意 seed e2e：渲染级容错闭环）

上轮报告的最后一项遗留清零。至此「写完了 ≠ 能用了」三条链路（HTTP / MCP / 渲染）全部有自动化门禁。

### 新增：敌意 seed + 全页截图

`backend/scripts/seed_hostile.py`：绕过应用层校验直插 41 行「现实世界会有的脏数据」——
零/负零/万亿金额、10.8k 字符名称、emoji/RTL/零宽字符、纪元与未来日期、进度超 100%、
巨率负债、0→巨数→0 的净值过山车。应用校验挡住的是今天新写入的垃圾，
挡不住历史版本写入的 / CSV 导入的 / 手改库的——渲染层必须自己扛住。

用现有 shots-full.mjs（10 页 × 桌面/移动双端）对敌意库跑截图：
**零 pageerror、零 console error、零横向溢出**。

### 修复：10k 字符持仓名称撑爆整页

敌意截图抓到的唯一真实缺陷：持仓表格的名称单元格没有截断，
10.8k 字符名称把整页撑成一条巨长的列（右侧面板有截断，表格没有）。
修：`PositionsTable` 桌面表格 + 移动卡片两处名称加 `truncate`，
标题属性保留完整名称可悬停查看。修复后同库重跑 20 张全过。

其余页面（总览负净值/万亿利率/过山车净值图、记账万亿流水、模拟盘零本金）
全部原生容错——之前的防御工作没白做。

### 用法

    python backend/scripts/seed_hostile.py .tmp/hostile/hostile.db
    cd backend && MONEYHELPER_DB_PATH=<db> uvicorn app.main:app --port 8789 &
    cd frontend && node e2e/shots-full.mjs http://localhost:8789 <outDir>

### 验证

前端 170 passed；tsc 零错误；build 成功；敌意截图 20/20 全过（修复前抓到 1 个缺陷）。
后端本轮零改动（seed 脚本不进 app 包）。

## [4.13.3] - 2026-11-06（MCP 契约闭环：14 个工具从必炸到可用）

上一轮报告列的三项遗留，本轮清掉两项半。

### 1. 14 个 MCP 工具在真实调用时必炸（本轮最大收获）

`tools.py` 只把 deep impl 的 **dict** 并进 TOOL_IMPL，没把**函数本体**
re-export 进模块命名空间。agent 侧走 dict 查找所以一直正常，
MCP 包装器却是 `xtools.tool_xxx` 属性访问——税计算、现金流预测、
订阅扫描、异常扫描、盘前检查、券商持仓导入、发票解析、市场宽度、
个股画像、条件单、账单归类、券商状态/预检/报单（14 个）
在真实 MCP 调用时全部 AttributeError。

修复：`globals().update({fn.__name__: fn for fn in DEEP_TOOL_IMPL.values()})`——
用循环而非手写 import 清单，新增 deep 工具只改 tool_impl_deep 一处，
从根上消掉「注册表加了、包装器炸了」的漂移类。

**验证方式也是新的**：通过真实 MCP 协议（fastmcp Client）调用修复前必炸的
tax_calc，确认返回税计算结果；不只是静态检查。

### 2. 新增 test_tool_contract.py（58 项）

- 真源对齐：TOOL_IMPL ↔ FINANCE_TOOL_NAMES ↔ TOOLS 双向一致
- MCP 表面：62 个包装器委托的 impl 真实存在（AST 解析）、描述非空、
  入参 schema 已登记
- 行为探测：全量工具空参数调用——缺参允许 ValueError（可读文案），
  不允许 KeyError/TypeError 等实现细节泄漏
- 能力漂移：agent 注册但 MCP 未暴露的工具会被点名

### 3. POST 探测升级 + 4xx 文案门禁

- schema 派生最小有效 body（required + 类型默认值 + 枚举首值），
  打进实现而非停在参数校验层
- 新断言：所有 4xx 的错误文案必须可读（非空、非堆栈）——
  校验拒绝是好事，但用户必须看懂为什么被拒

### 4. 前端敌意输入测试（41 项）+ 3 个真实显示缺陷

后端挡不住的垃圾值（历史脏数据、行情 API 返回异常）最终都流到格式化层。
新增 format.hostile.test.ts：NaN/Infinity/-0/巨数/非法日期/越界月份全量过一遍。

抓出并修复：
- `fmtPct(-0.004)` → "-0.00%"（与后端 -0.0% 同源的事故）
- `fmtDate(非法串)` → "Invalid Date" 直接给用户看
- `fmtMonth("2026-13")` → "undefined 2026"

### 验证

后端 **1485 passed / 6 skipped / 0 failed**（+61）；前端 **170 passed**（+41）；
tsc 零错误；真实 MCP 协议端到端调用通过。

### 仍未做（下一轮）

前端「组件在特定业务数据下崩溃」的渲染级覆盖（现有 20 张截图全是正常 seed）——
需要敌意 seed 的 e2e，成本较高，单独立项。

## [4.13.2] - 2026-11-05（接线核验 + 四个真实 bug + flake 根因）

对「所有做过的地方」做接线核验（不是重扫代码，而是查「用户能不能触达」），
又挖出四个真实缺陷 + 一个长期 flake 的根因。

### 1. 三个策略接口 500（单元测试全绿，接口必崩）

路由里漏了 `from ..calculations.strategies import backtest_grid, backtest_trend, backtest_vol_target`。
上一轮加端点时字符串替换没匹配上，import 从没被加进去——
`NameError` 只在真实调用时暴露，测试用的是函数直调所以全过。

修 import 后又暴露第二个 bug：`backtest_text` 只认 ma_cross/dca，
对 grid/trend/vol_target 走 else 分支格式化 `total_invested`（新策略没这字段）→ TypeError。
重写为「有哪些字段就说哪些话」，并把失效场景写进结论。

### 2. /openapi.json 一直 500

`export.py` 的 `-> Response` 没 import Response。
因为 `from __future__ import annotations`，运行时完全不报错，
只有 FastAPI 生成 schema 时抛 PydanticUserError。
影响：OpenAPI 文档、SDK 生成、前端类型全部拿不到（231 个端点）。

### 3. ValueError 漏成 500

db 层用 ValueError 表达「输入非法」，但只有部分路由自己 try/except。
漏掉的路径（如 `POST /api/watchlist` 传空 symbol）冒到兜底处理器变 500，
用户看到"内部错误"而实际只是少填一个字段。

新增全局 ValueError 处理器转 400，message 直接回传（db 层报错文案本就是给人看的）。

### 4. 调度器/看门狗的全局状态跨事件循环失效（flake 根因）

- `scheduler.stop()` 把 shutdown 放在 `_sched = None` 之前且无 try/finally：
  所属循环已关闭时抛 RuntimeError: Event loop is closed，导致 `_sched` 永不清空，
  下一个用例 start() 误判「已在运行」直接 return → **后续所有调度测试连锁失败**。
- `watchdog.start()` 里 `_current_interval` 只在协程内赋值，start() 检查时读到旧值，
  连续两次 start 会误判「间隔变了」重启两次。
- `_write_locks` 用 `id(loop)` 作键且从不清理：CPython 会复用 id，新循环命中
  「属于死循环」的 Lock（可能已 acquire），`async with lock` 立即返回 →
  并发保护静默失效。改为 `WeakKeyDictionary` 以循环对象为键。

这三处是「单独跑必过、全量跑偶发挂」的根因，不是偶发。

### 5. 死代码清理

删除 FeaturesView.tsx（75 行，被 FinancePage 取代后无人引用）。

### 新增测试

- test_endpoint_health.py（6 项）：OpenAPI 能生成、102 个 GET + 91 个 POST
  逐端点探测零 5xx、ValueError 必须转 400
- test_api_contract_strategies.py（16 项）：5 个策略接口全部不得 5xx、
  响应结构完整、文字结论对任意策略都不崩、无 -0.0
- test_scheduler.py +2：shutdown 抛错时状态必清空、关闭循环后能恢复
- test_write_isolation.py +1：写锁必须按循环对象隔离

### 顺带优化

- vol_target 调仓带宽 0.5% → 5%（原设置下 250 个交易日调 425 次，
  成本吃掉全部收益；改后 31 次，收益 -12.4% → +32.3%）
- 消除 -0.0% 显示

### 验证

后端 **1424 passed / 6 skipped / 0 failed**（连续两次全量全绿）；
前端 129 passed；tsc 零错误；193 个端点零 5xx。

## [4.13.1] - 2026-11-05（修「写了但没接线」的三处）

上一轮把功能写完了却忘了接进调用链——这类问题测试全绿也发现不了，
因为函数本身是对的。这轮逐个揪出来。

### 1. LLM 摘要压缩从没被调用过

`context.compact_messages` 写好了（LLM 摘要 + 确定性降级 + 可观测元信息），
但 `_build_history` 里实际调用的是同步的 `trim_messages`（只做确定性截断）。
等于「上一轮声称完成的 LLM 摘要压缩」完全没生效。

现在 `_build_history` 走 `compact_messages`：超预算时优先用模型生成结构化摘要
（目标/事实/待办/约束），模型不可用才降级。常规 4 轮对话远低于阈值，
不会额外付模型调用。

新增 `test_context_compaction.py`（10 项）：测「超预算必触发」「保留最近轮次」
「模型不可用要降级」——而不是测函数存在。

### 2. 动量策略只存在于测试里

`backtest_momentum` 实现了多标的动量轮动，但路由里没有入口——
用户在任何界面都调不到。新增 `GET /api/research/momentum`（2~6 个标的），
并发拉取行情、失败标的单列、明确标注「按长度截齐而非严格交易日对齐」。
补 4 项端点测试（参数校验 + 离线降级）。

### 3. write_txn() 定义了、测过了、没人用

上一轮新加的 `write_txn` 事务通道只有测试在用，生产代码零调用。
现在 `update_position` 接入它，顺带修掉原实现的真实缺陷：
- **先写撤销快照再校验**：传入 `shares=abc` 时 `float()` 抛错，
  快照留在未提交事务里，下一条无关写操作的 commit 会把它一起提交（幽灵快照）
- 校验只挡 NaN 不挡 ±Inf
- 失败后连接停在事务中

顺序改为「校验 → 写快照 → 更新」，整段在一个事务里。
新增测试断言「校验失败后连接不在事务中、且没写入快照」。

### 验证

后端 **1400 passed / 6 skipped**（+15）；前端 129 passed；tsc 零错误。

## [4.13.0] - 2026-11-05（回测口径重构 / 策略库 2→5 / README 精简）

### 修复：回测的假数据（比缺功能严重得多）

**定投净值曲线漏了现金**：曲线只累加已投入份额的市值，不含未投入现金，
于是「首尾之比」被当成收益率。实测单边下跌 62% 的行情报出
**年化 +44887%、夏普 243、最大回撤 −1.99%**——三个数字方向全反。

修三处：
1. 曲线 = 累计投入 − 已花费 + 持仓市值（含现金）
2. 年化改用 **XIRR**（资金加权），不用首尾之比
3. 回撤/夏普基于 **TWR 序列**（剔除新增资金），否则曲线单调上升、回撤恒为 0

**双均线只认「金叉那一刻」**：回测起点若已在多头排列（或行情平滑上涨使交叉从未发生），
策略全程空仓——实测单边上涨 60% 报 0% 收益。改为「多头排列即持仓」（状态量而非事件）。

**交易次数算错**：`len(trades)//2` 在只买未卖时得 0，用户以为策略没交易过。
改为按成交笔数计，另给 `round_count`（完整回合）与 `open_position`。

新增 `test_backtest_curve.py`（11 项）锁定这三条口径。

### 新增：策略库 2 → 5

新模块 `calculations/strategies.py`，设计上信号与执行分离（成本/次日成交/风控只写一次）：

| 策略 | 原理 | 参数依据 | 失效场景 |
|---|---|---|---|
| 网格 | 区间等分，跌买涨卖 | 3% 格距 ≈ A股ETF 两日波动 | 单边下跌买满、上涨卖光 |
| 趋势跟随 | 唐奇安突破 + ATR 止损 | 20/10 非对称，ATR×2 ≈ 2σ | 震荡市假突破 |
| 波动率目标 | 仓位 = 目标波动/已实现波动 | 15% 目标 ≈ 沪深300 常态 75% 仓 | 波动率跳升滞后 |
| 动量轮动 | 选 N 日最强标的 | 20 日回看、月度调仓 | 震荡市追高杀低 |

风控叠加层（止损/止盈/移动止损/回撤熔断）可包在任意策略外。

### 修复：行情不可用时整页被吞

投研页在 `available === false` 时只渲染空态，把策略回测一起吞掉——
但回测是独立计算，离线/内网复盘时恰恰最需要它。改为局部降级：
技术面显示空态，回测区照常可用。浏览器实测 5 个策略按钮全部可见。

### README 重写

130 行（原 188）：一句话定位 + 三种安装方式 + 4 张截图 + 能力表 + 验证命令。
删掉「本地优先」「确定性引擎」等营销式长段落。

### 验证

后端 **1385 passed / 6 skipped**；前端 129 passed；tsc 零错误；构建成功。
浏览器实测 5 个策略可选、零控制台错误。

## [4.12.0] - 2026-11-04（遗留项清零：事务原子性 / MCP 三原语 / i18n 覆盖 / 截图自动化）

上一轮列出的 6 项遗留全部完成。

### 数据层：写事务真正原子（此前是「看起来有、实际没有」）

连接改为 `isolation_level=None`（autocommit），彻底消除「A 协程 commit 把 B 协程
半截事务一起提交」的跨协程污染。多语句事务改为显式 `BEGIN IMMEDIATE`，
已在事务中时用 `SAVEPOINT`（SQLite 标准嵌套写法）。

三处关键路径补齐显式事务：
- `import_backup`：先 DELETE 全租户数据再写回。没有事务时「恢复失败回滚」是空话，
  原数据已被删掉。现在失败整批回滚。
- `add_transactions_batch`：批量入账/CSV 导入，任一条失败整批回滚。
- `write_txn()`：新增的统一事务通道，异常必回滚。

新增 `test_write_isolation.py`（5 项）断言：并发 12 笔不丢、失败批次不留半截、
两个批次不交叉污染、事务异常回滚、成功提交。**这批测试第一次跑就抓到了
write_txn 在 autocommit 下 commit/rollback 是空操作的真实缺陷。**

### MCP：三大原语齐全 + instructions

- 补 `instructions`（221 字符）：客户端会把它作为系统提示注入，告诉模型
  「这个服务器是干什么的、什么时候该用」。不设时模型只能从 62 个工具名里猜。
- 补 3 个 `prompts`：月度复盘 / 持仓体检 / 目标规划。tools 让客户端「能算」，
  prompts 让它「知道该怎么问」——没有 prompts 时每个客户端拼的提示词都不一样。
- 现状：62 tools / 3 resources / 3 prompts。

### i18n：三个主功能页完成迁移

StatementsPage / PaperTradingPage / ResearchPage 合计迁移 **135 处**中文字面量
（属性值、JSX 文本、说明段落、placeholder、aria-label），新增 108 个 key。

迁移过程中的三个真实教训（都修在代码里了）：
1. 属性值不能直接换成 `t(...)`，必须 `{t(...)}`——第一版自动替换直接产生语法错误；
2. 对象键位置不能放函数调用，必须用计算属性名 `[t(k)]`；
3. `trades.map((t) => ...)` 的 `t` 会遮蔽 i18n 的 `t`，必须重命名。

浏览器实测：财报页英文模式中文从 36 → **0**；模拟盘 133 → 41（剩余为演示数据里的
账户名「小明」，属用户数据而非界面文案，不应翻译）。

### 前端体验修复

- **错误提示不再显示裸状态码**：代理层返回非 JSON 时，界面曾只显示 500/502，
  用户无法判断是服务没启动还是接口报错。现在给可读句子 + 状态码。
- **图表按需注册**：移除完全未使用的 `graph` 图表；radar/treemap/candlestick/dataZoom
  改为页面级懒加载（`ensureChartModules`），首屏图表只付 bar/line/pie 的体积。

### 截图自动化：覆盖从 7 页扩到 10 页

`e2e/shots-full.mjs` 新增财报/模拟盘/投研三页，并修复两个自动化缺陷：
- 首启引导是 z-50 模态框会拦截所有点击（不是 bug，但自动化必须先关闭）；
- 失败时错误信息被截断成一行，无法定位原因。

实测 **20 张截图（桌面 10 + 移动 10）全部通过，零溢出、零控制台错误**。

### 验证

后端 **1353 passed / 6 skipped**；前端 **129 passed**；tsc 零错误；构建成功。

## [4.11.0] - 2026-11-04（全量审计修复 / 企业级硬化 / 三形态交付）

### 修复（P0 资金与数据正确性）

- **一句话多笔丢账**：`午餐 45 打车 28` 曾被解析成单笔「打车 −45」——金额取自午餐、
  名称取自打车，既丢一笔又把两笔错配成一条坏数据。新增 `nlparse.parse_many`，
  CLI 与 `/api/nl-add` 均已接入；单笔解析行为不变（`房租 6000 元` 仍是一笔）。
- **追加持仓一键翻倍**：前端「追加」曾把当前全部持仓股数当新增股数提交，点一次仓位
  翻倍且成本被重算。改为弹窗输入本次股数与成交价，并实时预览合并后结果。
- **卖出超量即清仓**：`sell_position` 对 `shares > 持仓` 或负数直接删仓。现在显式拒绝
  并给出可用数量；只有省略数量才代表清仓。
- **记录买入覆盖原持仓**：同代码再买入会整行覆盖。改为股数累加 + 加权成本（与 REST
  `/append` 同语义）。
- **CSV 导入半截入账**：边校验边写导致失败时前半截已落库。改为「全量校验 → 单事务写入」，
  任何一行非法即整批拒绝并返回行号。
- **inf 污染账本**：金额/股数只挡 NaN 不挡 ±Inf，写入后 JSON 序列化抛错使 dashboard
  持续 500。全部入口改用 `math.isfinite`。
- **TWR 恒等于 0**：用「当前市值 − 累计流入」反推期初估值，数学上结果恒为 0。
  改为只在有真实历史快照时计算，否则显式返回 `available=false` 并说明原因。
- **健康分空库送分**：未录入负债时 `debt_monthly=0` 被当成「结构干净」给满分。
  改为 `unknown`（不计分，只缩小分母），并说明需要补录。
- **健康分两套实现**：MCP 走 `calculate_health_score`（54/D），REST 走
  `analysis.health_check`（83/B）。统一为后者，MCP 直接复用。
- **涨跌配色只对图表生效**：`@theme inline` 把颜色内联进工具类，`data-scheme` 切换
  影响不到全站文字。改为 `var(--scheme-up/down)` 间接引用，浏览器实测 cn→us 生效。
- **英文金额少 100 倍**：compact 阈值沿用中文的 1e4/1e8、除数却是 1e6/1e9，
  `12345` 显示成 `¥0.0M`。改为 k/M/B 正确分档。
- **空态三个按钮全是死链**：`FinancePage` 未传 `onGoLedger/onGoMarket/onGoChat`，
  新用户点「去记账/添加持仓/问 AI」无反应。已接线。
- **SSE 静默成功**：一帧未收到时正常 return，界面永久「分析中」。改为抛错。
- **查询失效不全**：`bump()` 漏掉 calcs/subscriptions/evaluate，同屏出现两套数字。
  改为按前缀失效并新增 `refetchAllFinancial`。
- **模型切换未接线**：设置页承诺的下拉不存在。`ChatInput` 补实现（仅列已点亮模型）。
- **命令面板「对话」空操作**、**财报删除无确认**、**K 线不支持时永久转圈**：均已修。
- **i18n key 缺失**（`common.cancel`、`family.voter` 等）：新增静态扫描测试，
  源码里 `t("key")` 必须在两个字典都存在，缺失直接让测试失败。

### 安全（P0）

- **MCP 丢弃租户上下文**：`auth_gate` 返回的 tenant_id 未写入 ContextVar，
  多用户实例里用户 B 读写的是用户 A 的账本。已接线并 finally 还原。
- **LLM 配置进程级共享**：第一个配置 Key 的人会把凭据「借」给所有用户。改为按租户缓存。
- **券商适配器全局单例**：缓存键只有券商名，用户 B 会拿到 A 的连接。改为 (user_id, broker)。
- **日志接口无鉴权**：任意登录用户可读可清全实例日志。改为管理员限定。
- **MCP test 可 SSRF + 任意命令执行**：新增 `netguard.py`（拒绝私网/回环/云 metadata，
  含 DNS 解析校验），stdio MCP 不再开放给 API；保存服务器列表同样校验。
- **PBKDF2 阻塞事件循环**：导出加密丢到线程池。

### harness（对齐业界）

- **LLM 摘要式压缩**（`context.py` 重写）：原实现是「每条截前 100 字」的伪摘要，
  改为模型生成结构化摘要（目标/事实/待办/约束）+ 保留最近 N 条，模型不可用时
  退回确定性摘要；返回可观测的 `strategy/before/after/dropped`。
- **工具权限三档**（`tool_policy.py`）：read/ask/deny，最后匹配优先，未知工具默认 ASK
  （fail-closed），高危工具不可被配置降级；`agent.WRITE_EXCLUDED` 改为策略驱动，
  外部 `mcp__` 工具不误伤。
- **审批幂等**：确认路径用条件 UPDATE 抢占，并发/重放不会重复执行；失败后状态如实记
  `failed`（原先对已消费行是空操作）。
- **会话历史 token 闸**：单轮长报告会挤占上下文，改用 tiktoken 计量 + 折叠。

### 新增（金融能力）

- **净值序列与归因**（`networth_series.py` + 每日快照表）：把净资产变动拆成
  「净储蓄 / 投资损益 / 负债变动 / 残差」。归因公式修正过一次：原版把同一个
  `net_inflow` 既当储蓄又当投入，储蓄场景会凭空产生等额负投资损益。
  新增 `/api/calculations/net-worth/history|snapshot|attribution` 与前端趋势卡。

### 交付形态

- **单文件可执行程序**（`build.spec` + `moneyhelper/launcher.py`）：PyInstaller 打包，
  双击即用、自动选端口、数据落用户目录。已实测 `Moneyhelper.exe` 起服务 + 返回完整 SPA。
  修掉两个打包缺陷：litellm 数据文件未收集（启动即崩）、静态资源路径应为 `static/`。
- **`python -m moneyhelper.cli`** 可直接运行（补 `__main__.py`）。
- **README 重写**：335 → 188 行，以表格/mermaid/代码块为主，去掉营销式长段落。

### 验证

- 后端 **1350+ passed / 6 skipped**；前端 **130+ passed**；`tsc` 零错误；生产构建成功。
- 浏览器实测：涨跌配色切换（`rgb(220,38,38)` → `rgb(5,150,105)`）、追加弹窗、
  零横向溢出、零控制台错误。
- CLI / Web / exe 三种形态均实测可用。

## [4.10.0] - 2026-11-04（回测→模拟盘闭环 / 账户合并 / 可交互报告）

### 新增

- **回测 → 模拟盘桥接（`calculations/bridge.py`）**：把策略从「历史验证」推到「样本外验证」。
  - `POST /api/paper/bridge/plan`：回测结果转调仓计划（明确标注 `approximation`，因信号由
    净值曲线方向推断而非原始价格重算，不得冒充精确信号）。
  - `POST /api/paper/bridge/track`：对比模拟盘实际净值与同策略回测预期，输出跟踪误差、
    方向一致率、最大偏离与分档结论。16 项测试。
  - **口径修正**：分档取「均值 / 当前 / 最大偏离」三者最大值——平均值会被起点 0 稀释，
    一条曲线最后偏离 15% 但前 10 天贴合时均值仍可能落在容忍带内，会误报「策略正常」。
- **多账户合并（`calculations/accounts.py`）**：本地账本 + 模拟盘 + 实盘统一净资产口径。
  - 外币账户**不做汇率猜测**，单列并标注「未折算」；本地与实盘重叠时明确提示而非替用户决定。
  - `GET /api/paper/bridge/accounts-overview`；本地净值复用 `calculate_net_worth`，避免同一屏两个数字。
  - 前端 `AccountsMergeCard` 只在账户数 > 1 时显示（单账户与净值卡重复，不占版面）。10 项测试。
- **可交互 HTML 报告（`app/report.py` + `GET /api/export/report`）**：单文件、零外部依赖、离线可看、
  可打印为 PDF。内联 SVG 图表（盈亏正负分侧、资产占比），打印样式隐藏交互控件。12 项测试。
  - 修掉两处自制图表缺陷：盈亏图数值标签压住标的名称（改为三列固定布局）；
    「持仓分布折线」把无顺序关系的持仓连成折线属伪信息（改为真实占比条）。

### 修复

- `pyproject.toml` 版本未随 `version.py` 同步（4.8.0 vs 4.9.0）——`test_release` 抓出，
  这正是「单一真源」要防的漂移。

### 验证

- 后端 **1306 passed / 6 skipped**；前端 123 passed；`tsc --noEmit` 无错。
- 真实浏览器验证：合并账户卡与 HTML 报告（本地 file:// 打开）均正常渲染。

## [4.9.0] - 2026-11-03（harness 能力补齐 + 决策中心 + 导航重构）

### 新增

- **决策中心（`calculations/decisions.py`）**：把风险标记、目标进度、税负机会收敛成一张
  「现在该做什么」清单，按紧急度排序并给出一键跳转。此前四个模块各自正确，排序工作却推给用户。
  集中度超限即使 level 只是 warn 也按紧急处理——它是已经发生的偏离，不是潜在风险。9 项测试。
- **会话 token 计量**：`llm.stream_narrate` 回传模型真实用量，`runs` 表新增 `tokens_in/tokens_out`，
  `GET /api/sessions/by-thread/{tid}/usage` 汇总。此前用量只进日志，界面无从判断上下文开销。
- **会话分叉（`db.fork_session`）**：从任意一轮复制历史到新会话，各自独立演化；
  run_id 不属于该会话时拒绝复制。7 项测试覆盖计量口径、分叉边界与越权。
- **前端分组导航（`ui/grouped-nav.tsx`）**：11 个平级 tab 收敛为「每天看 / 判断时 / 算账 / 接入」
  四组，每屏只暴露当前组 3-4 项；当前激活项所在组自动展开。7 项测试。
- **聊天上下文仪表**：有真实计量时显示 token 总量与「已压缩」标记，模板降级轮不显示（避免 0 误导）。

### 修复

- **盈亏贡献图方向语义错误**：零轴缺失导致亏损条看起来也朝右延伸，会被读成盈利。
  改为对称取值 + 居中零轴 + 正负分侧圆角，负值标签不再压条。
- **`stream_narrate` 新参数向后兼容**：经 `service._narrate` 调用，不支持 `usage_out` 的实现
  （测试桩/第三方替换）自动降级，计量缺失不影响成文。

### 验证

- 后端 1268 测试通过、前端 123 测试通过、`tsc --noEmit` 无错、生产构建成功。
- 真实浏览器截图 14 张（桌面 7 + 移动 7），零横向溢出、零控制台错误：
  `docs/screenshots-v4.9/`，由 `frontend/e2e/shots-full.mjs` 生成（含溢出与报错门禁）。

## [4.8.0] - 2026-10-31（路线图收口：CLI/语音/沙盒/议会/生态）

### 新增

- **M4.1 CLI `dept`**：`run / list / approve / reject / inquire`，本地直连与远程 HTTP 双形态；12 项 CLI 测试。
- **M5.4 语音播报**：`lib/use-speech.ts`（SpeechSynthesis，离线可用），设置项 `voice_output`、回答气泡朗读按钮、
  自动朗读、超长截断 1200 字、代码块跳过；4 项前端测试。
- **M5.5 反事实沙盒**：`calculations/sandbox.py` 四类情景（少花/多存/改定投/一次性），
  `/api/strategy/sandbox` 与 `/base`，前端 `SandboxCard` 并排对比变更前/后/差值；9 项引擎 + 4 项 API 测试。
- **M6.2 评测错误台账**：`POST/GET /api/eval/ledger` 把判错题写入经验库（reflections），同题同模型去重；4 项测试。
- **M6.4 家庭议会**：`family_motions` / `family_votes` 表；2/3 法定人数 + 严格多数；状态机
  voting→approved/rejected/withdrawn；六个 API + 设置页 `MotionsPanel`；8 项测试。
- **M6.5 教程三连 + Registry**：`docs/mcp-guide.md` 补齐 Cline 接入；`server.json` MCP Registry manifest。
- **M6.6 可复核性标准草案**：`docs/reviewability-standard.md`（五条硬性要求、第三方复核流程、诚实清单）。
- **M4.2 Tauri 桌面脚手架**：`desktop/src-tauri`（tauri 2、sidecar 启停、updater 配置、五类 bundle 目标、图标）。

### 修复

- 反事实沙盒口径错误：`save_more` / `dca_change` 曾被当成支出增加，导致净流入反降；改为「储蓄」维度后
  净流入与 FIRE 年限方向正确（6000→8000，27.98→23.76 年），并补回归断言。

### 已知边界

- Tauri 安装包未在本机产出：需目标平台工具链（WiX/NSIS/Xcode/webkit2gtk），本机内存不足以稳定完成 Rust 构建；
  脚手架与配置已校验，`desktop/README.md` 列明阻塞与构建步骤。
- M6.2 的社区运营部分（Issue 模板、每周台账 post）是人工动作，软件侧能力已就绪。

### 测试

后端 1258 passed（新增 28，较 v4.7 的 1230）；前端 116 passed（新增 4）；tsc、build、ruff 通过。

## [4.7.0] - 2026-10-30（真实券商通道：富途/长桥/老虎/盈透/QMT/easytrader）

### 新增

- `broker_live.py` 实装 futu-api、longport、tigeropen、ib_insync 四个真实 SDK 适配器，保留 QMT/ easytrader；
  每个通道提供 probe/connect/cash/positions/preview/submit/poll。
- `broker_credentials` vault 加密存储：没有 `VAULT_PASSPHRASE` 时 fail-closed；API/前端不回显秘密；
  券商密文不进入备份文件。
- 连接中心新增真实券商配置卡：通道选择、参数填写、加密保存、配置状态与本机缺项提示。
- 目录新增四个真实 OpenAPI 通道：富途、长桥、老虎、Interactive Brokers。

### 安全边界

真实通道不会解除 v4.6 护栏：默认 NullBroker + dry-run；真实报单仍需要显式开关、适配器白名单、
金额/集中度限额、一次性确认令牌与成交对账。用户必须自行从券商申请 API 权限、运行 OpenD/TWS 或客户端；
本系统不代开户、不绕过 2FA、不把密码写日志。

### 验证

券商测试 65 项通过；全量后端 **1230 passed**；前端 112 tests、tsc、build 保持通过。

## [4.6.0] - 2026-10-30（边界攻坚：发票识别 / PDF 对账单 / 规则归类 / 券商执行层 / 定位纠偏）

> 上一版标为「边界」的四件事，这一版逐个调研开源实现并落地；另外修正了对外定位描述。

### 新增：发票图片识别（二维码优先 + OCR 兜底）

- **发票二维码解析**（`import_parsers/invoice_vision.py`）：按国家税务总局格式解析
  `01,发票代码,发票号码,金额,开票日期,校验码,随机码`，比 OCR 更准。
- **双解码器探测**：OpenCV `QRCodeDetector`（首选）→ pyzbar（备选）；都缺失时返回安装提示。
- **OCR 兜底**：RapidOCR（首选，离线轻量）→ PaddleOCR；识别文本复用发票字段正则。
- 图片一体化识别：二维码优先取关键字段，OCR 只补购买方/销售方/税额，不覆盖更可信的值。
- 接口：`POST /api/connect/invoices/image`、`GET /api/connect/invoices/vision/status`。

### 新增：PDF 对账单解析

- `import_parsers/pdf_statement.py`：pdfplumber 表格抽取优先 → 文本行回退 → 扫描件明确拒绝。
- **对账核对**：`statement_reconcile()` 按「日期 + 金额」匹配（摘要不参与，避免假差异）。
- 接口：`POST /api/connect/import/statement-pdf`（预览/入账）、`POST /api/connect/statement/reconcile`。

### 新增：账单智能归类规则引擎

- `categorize.py`：参照 double-entry-generator 的多维规则模型（peer/item/category/type/金额区间），
  按「具体度」排序，同分精确优先于正则；正则带编译缓存与长度上限。
- 19 条内置规则；兜底命中打 `needs_review` 标签；`explain()` 输出兜底比例与补规则建议。
- 接口：`GET /api/connect/categorize/rules`、`POST .../preview`、`POST .../apply`。

### 新增：券商执行层（默认永不下单）

- `broker_adapter.py`：`BrokerAdapter` 协议 + 四个实现（NullBroker 默认 / PaperBroker /
  XtQuantBroker / EasytraderBroker）。
- **七道护栏**在 `guarded_submit()` 强制：总开关、dry-run、券商白名单、单笔上限、单日上限、
  单票集中度、二次确认令牌（绑定内容、用后即焚、5 分钟过期）。
- 适配器 `probe()` 明确列出缺什么（xtquant 不能 pip 安装、easytrader 需客户端路径等）。
- 接口：`/api/execute/{status,preview,submit,orders}`、`/api/execute/adapters/{name}/{connect,disconnect}`。

### 变更：定位纠偏

- 全仓 5 个对外文件（README / README.zh / docs/index / pyproject / frontend index.html）
  及 3 处次级文档移除「local-first / 本地优先」作为核心卖点的表述，改为
  「面向个人与小微公司的 AI 财务部门」，本地/自托管/云端明确为部署选项。
- 同步补入真实能力卖点：外部数据接入、公司财税、交易执行护栏。

### 新增依赖分组（全部可选）

`vision`（opencv/pillow/pdfplumber/pypdf）、`ocr`（rapidocr）、`broker`（easytrader/pywinauto）。
未安装时能力探测返回 `available=false` + 安装提示，不报错。

### 测试

后端 **1220 passed**（v4.5 基线 1164 + 新增 56：确定性/解析 39 + HTTP 17）；前端 112、tsc、build 通过。

## [4.5.0] - 2026-10-29（连接中心深化：从「能接上」到「能干活」）

> v4.4 解决接入，v4.5 把每个模块做深：行情加腾讯源与市场温度、导入加持仓对账与发票、
> 交易加预交易风控与条件单、新增公司财税与个人现金流两套确定性引擎。

### 新增：确定性计算引擎

- **税负与薪酬**（`calculations/tax.py`）：增值税（一般 13/9/6%、简易 5/3/1%、留抵与小微免征）、
  附加税（城建 7/5/1% + 教育 3% + 地方教育 2%）、企业所得税（25/15/5%，小微超 300 万自动回落）、
  个税（累计预扣法 + 7 级累进 + 专项附加）、工资五险一金（基数上下限钳制、企业总成本）、
  12 项月度结账清单。
- **现金流**（`calculations/cashflow.py`）：三档预测（P20/P50/P80，剔除一次性大额）、
  订阅识别（周期 + 金额变异系数 + 涨价检测）、异常扣款（中位数 + MAD，3.5σ）。
- **预交易风控**（`calculations/pretrade.py`）：涨跌停（主板/创业板/科创板/北交所/ST 分档）、整手、
  资金/持仓、T+1、集中度、日限额、60 秒重复单，共 9 项；另有再平衡转委托（先卖后买、整手取整、缺口明示）。

### 新增：行情深化

- **腾讯行情源**（`connect/quote_tencent.py`）：一次批量请求取 50+ 字段（PE/PB/市值/换手/量比/振幅/涨跌停），
  并提供分时与 K 线备源——东财 push2 在本机网络被重置时仍可用。
- **市场温度**：涨跌家数、涨停/跌停、强势股、情绪温度 0-100 与冷热档位（东财 push2ex）。
- **个股档案**：估值 + 规模 + 活跃度一次打包，PE 为负时明确提示「亏损，PE 无参考意义」。

### 新增：导入深化

- **券商持仓对账**（`import_parsers/broker_holdings.py`）：识别标准持仓表/带市场前缀/Excel 另存 CSV，
  跳过合计行，成本价或现价缺失时明确告警，同内容文件按 SHA-256 幂等。
- **发票归档**（`import_parsers/invoice.py`）：OFD（zip+XML，纯标准库）、PDF（pypdf，缺失时明确报错）、
  图片（明确提示需 OCR）、文本；置信度按字段完整度分级，绝不编造票号。

### 新增：交易与条件单

- 条件单：`price_below / price_above / pct_change_below / pct_change_above`，命中后**只生成待确认意图**。
- 风控参数可配置（日限额/偏离阈值/集中度阈值），存独立表不与用户设置混用。

### 新增：前端

- 连接中心新增三个页签：投研深化（市场温度 + 个股档案）、交易风控（预交易检查 + 风控参数 + 条件单）、
  发票与对账（发票归档 + 券商持仓导入）。
- 新增「公司财税」页：现金流预测卡 → 增值税/企业所得税/个税/工资/月结五页签 → 订阅与异常双卡；
  打开即用默认参数算一次，所有数字标注口径与免责。

### 新增：接口与工具

- 22 条新端点（连接深化 19 + 财税现金流 9，含 GET/PUT/POST 组合）。
- Agent / MCP 新增 10 个工具：`tax_calc`、`cashflow_forecast`、`scan_subscriptions`、`scan_anomalies`、
  `pretrade_check`、`import_brokerage_holdings`、`parse_invoice`、`market_breadth`、`stock_profile`、
  `conditional_order`；财务工具总数 48。
- 备份覆盖 4 张新表（发票 / 对账记录 / 条件单 / 风控设置）。

### 测试

后端 1164 项（新增 70：确定性引擎 50 + HTTP 20），前端 112 项，tsc 与生产构建通过；
桌面与 390px 手机实测零控制台报错、零横向溢出。

## [4.4.0] - 2026-10-29（连接中心：外部平台一站式接入）

> 目标：用户不再「一条条手输」。能自动的后台直连，要登录的给官方入口 + 一次性配对码，
> 剩下的导出文件丢进收件箱自动入账。

### 新增：连接中心（Connect Hub）

- **27 个内置连接器**：行情与投研（7）、证券与交易（5）、基金（2）、银行（4）、支付与钱包（3）、
  发票（2）、公司财税（2）；每个标注接入方式（公开接口 / 官方跳转 / 浏览器代登录 / 文件导入）
  与自动化档位（全自动 / 一次授权 / 导出即入账）。
- **公开数据源直连**（免登录、免密钥）：四大指数、全市场涨跌/换手/成交额排行、
  场外基金最新净值与历史净值。东财 push2 在部分运营商出口被重置时自动切新浪备源。
- **浏览器代登录**：配对码 10 分钟有效、用后即焚；书签脚本只读用户当前页可见文本，
  不读 cookie/localStorage，等价于用户自己复制粘贴。
- **账单收件箱**：`data/import-inbox/u<uid>/` 放官方导出 CSV，后台每 10 分钟自动扫描入账，
  处理完归档到 `done/`；按租户分目录，互不串账。
- **交易指令**：`paper` 直接写模拟盘（A 股整手 + 佣金 + 印花税口径）；`live` 只生成交接单并
  打开券商页面，系统不代下单，成交后由用户回填。全部进审计链路（provenance）。
- **Agent / MCP 工具**：`connect_catalog` / `connect_sync` / `connect_fund_nav` / `connect_order`
  四个新工具，模型可直接「帮我连上支付宝」「查一下 110011 净值」「模拟买入 100 股」。
- **后台自动化**：`connect_auto_sync` 每小时同步全自动连接；`connect_inbox_scan` 每 10 分钟扫收件箱。
- **前端新增「连接中心」页**（财务工作区第 3 个页签）：行情直连 / 接入目录 / 账单收件箱 / 交易指令
  四个视图；数据源连通性实时探测；中英双语。

### 修复

- **总览整页白屏**：空账本时 `/api/calculations/returns` 不返回 `xirr`/`twr` 键，
  `ReturnsCard` 对 `undefined` 做 `"error" in m` 直接抛 TypeError，整个总览被 ErrorBoundary
  接住显示「页面出错了」。改为空值占位并补回归测试。
- **指数行情条整条消失**：东财 push2 在本机网络被重置时 `indices_quotes()` 直接返回空数组；
  新增新浪 `hq.sinajs.cn` 备源（与个股备源同域名）。
- **限流测试随机假失败**：`test_over_limit_rejects` 把「此刻」写进桶首位，`retry_after` 恰好卡在
  窗口边界导致 60 变 61；改为全部落在过去 10 秒之后。

## [4.3.2] - 2026-10-28（并发一致性、UI 崩溃与卡片化）

### 修复（第三轮：并发一致性与 UI 崩溃）

- **并发保存丢数据**：Studio 配置是「读整份 JSON → 改一个键 → 写回整份」，8 个并发
  保存只存下 3 个（实测）。所有写入改为复用 `db.get_write_lock()` 串行化，12 并发全中；
  安装器/权限/看门狗/内置工具开关同样纳入锁
- **编辑内置资产后 builtin 标记丢失**：一次编辑就把内置项变成可自由删除，
  现在 `upsert_asset` 保留既有 builtin 标记
- **非法定时动作被静默保存**：`time: "99:99"`、`weekdays: [9]` 也能存进库，
  到点永远不触发且没有报错。现在复用 `agent_config.normalize_skill_action` 校验并 400
- **非全面放开模式仍允许 URL 安装**：standard/strict 只关了对话与 CLI，`allow_remote_install`
  仍为 true，等于留了绕过权限的后门。现在三者在非 open 模式下一律关闭
- **看门狗改间隔不生效**：已在运行时改 `interval_minutes` 不会重启 loop。现在检测到间隔变化先
  `stop()` 再重启
- **中文名导入 id 冲突**：`规则甲/乙/丙` 三个文件都映射到 `rule`，后导入静默覆盖前面的
  （实测导入 3 个只剩 1 个）。改为非 ASCII 名拼内容哈希
- **备份泄露 MCP 密钥**：MCP 的 `env` 常放 API Key（GITHUB_TOKEN 等），导出时明文进备份。
  现在 `env` 值一律替换为 `***`，恢复时跳过占位符不写回
- **MCP 配置漂移不可恢复**：`mcp.json` 在 data/ 下、`seeded` 在 DB 里，删了配置文件后已预装的
  MCP 永远回不来。启动时 `repair_mcp_config()` 按 `installed` 记录补回（不复活用户主动卸载的）
- **插件市场整页崩溃**：`MarketplaceSection` 与 `PluginsSection` 共用 queryKey
  `["/api/mcp/servers"]` 但返回形状不同（数组 vs 对象），先进插件页再进市场页会
  `(mcpServers.data ?? []).map is not a function` → 整页「页面出错了」。拆分 queryKey 并加 2 条回归用例
- **角色工具白名单被 MCP 工具绕过**：白名单在 MCP 合并之前过滤，mcp__* 工具照样进工具面；
  白名单改为最后一道过滤
- **导入不提示覆盖**：同名资产导入后静默覆盖，用户无从察觉；导入结果新增 `replaced` 计数，
  前端/CLI 都提示「其中 N 项覆盖了同名资产」
- **「一键自检」污染看门狗统计**：诊断接口调用 `run_check()` 会推进 checks 计数与 last_check_at；
  改为 `advance_state=False` 只读扫查
- **设置页 `@container` 缺失**：`Row` 等组件用的 `@sm:`/`@lg:` 变体一直没有容器查询上下文，
  实际从未生效；给设置内容区补 `@container`

### 体验

- 资产列表从单列长条改为**响应式卡片网格**（桌面 2 列 / 平板与手机 1 列），卡片内含状态徽标、
  说明、定时摘要与底部操作条（编辑/删除/触发记录/立即执行/开关）；内置工具与 MCP 分区同样改卡片
- 核心锁定项从配置键名改为中文标签（审批阈值下限 / 模型密钥 / 访问口令 / 内置工具可见性 / 破坏性操作确认）
- 导入区新增「查看官方格式示例」面板（SKILL.md 示例 / JSON bundle 形状 / zip 规则）
- MCP 分区显示「已启用 N/M」、全部启用/全部停用、连接失败红标；市场页对「已配置但未启用」的 MCP 给出提示
- 技能定时徽标显示可读星期（`定时 周五 17:30`），正文与说明相同时不再重复渲染

## [4.3.1] - 2026-10-28（Agent Studio 深度审计修复）

第二轮审计修掉 10 处真实缺陷（详见下方「修复（第二轮深度审计）」），并把设置导航重组为
五组、补导入格式示例面板、MCP 批量启停与失败可视化。后端 1053 测试、前端 111 单测、
28 条 E2E 全通过。

### 新增：Agent Studio（设置中心从「配置项」升级为「能力工坊」）

- **角色 / 技能 / 提示词 / 约束 / Hook 全部可编辑并真正运行时生效**：
  主角色指令、提示词（按优先级）、约束（must/should/may × all/finance/research）、
  pre_prompt 注入统一进入系统提示；pre_tool Hook 可拦截/告警工具调用，post_answer Hook 做审计
- **默认包非空**：8 个角色、9 个技能、4 份提示词、7 条约束、7 个 Hook、8 个内置科研工具，
  首次启动即启用；用户可关闭/删除，重启不会复活（`marketplace.seeded` 只执行一次）
- **四条添加通道**（每个分区都有）：对话内说一句、拖拽/上传（SKILL.md、md、json/yaml、zip）、
  模板手写、AI 一键生成（生成后二次校验，未接入模型时明确报错）
- **插件市场**：内置 42 个开源条目（Anthropic Skills 精选、学术论文/审稿/文献综述/引用管理/
  EDA/科研绘图、科研与工程角色、Cursor 规则、官方 MCP 参考实现 + DeepWiki/GitMCP
  + 科研 MCP（arXiv / Zotero / Paper Search）），
  一键安装；支持粘贴 GitHub/任意 URL 安装单个文件；MCP 安装只写配置、默认停用
- **权限模型**：全面放开 / 标准 / 严格三档；核心项（审批阈值下限、密钥、访问口令、
  内置工具可见性、破坏性操作确认）在任何模式都锁定，`/api/studio/core-guard` 给出拒绝理由
- **内置优势工具（不对外）**：科研大纲、引用格式化（GB/T 7714 / APA / MLA / Chicago）、
  检索式构造、CSV 数据画像、统计摘要、敏感性分析、实验设计核查、来源可信度评分；
  纯标准库、离线可用，只进内部工具面，不进 MCP 对外清单，逐个可开关
- **运行时看门狗**：每 15 分钟检查日志错误、配置完整性、MCP 状态，设置页可立即检查并展示发现项
- **CLI 对等**：`moneyhelper studio list/show/add/remove/toggle/import/market/ai`，
  与设置页共用同一存储与校验（远程模式走同一 HTTP API）
- **MCP 增强**：支持 stdio 传输（command + args）、逐台启用/停用；市场安装的 MCP 默认停用

### 修复（第二轮深度审计，均为真实缺陷）

- **内置科研工具全部不可用**：agent 执行层统一 `await impl(args)`，而 8 个内置工具是同步纯函数，
  `await` 一个 str 会抛 `TypeError: object str can't be used in 'await' expression`；
  改为包一层协程（`_make_internal_runner`），并加端到端测试（模型调用 → 工具结果含「样本量」）
- **删除的内置项会复活**：默认包补齐只看「缺不缺」，用户删掉的内置提示词/约束/Hook/角色/技能
  下次读配置又回来。改为按租户持久化墓碑（`removed` 字段），并补「删除后重建同 id」测试
- **审批阈值下限只是文案**：`core-guard` 声称下限 100 元，但改 `defaults.approval_threshold`
  仍能设成 0；`approval.threshold()` 现在钳制到 ≥100，保存配置时低于下限会被钳制并回报 warning
- **角色「工具白名单 / 温度」只存不用**：模型永远 0.2 温度、永远拿到全量工具；
  现在白名单真正裁剪工具面，温度进入模型调用参数
- **MCP 发现串行且无失败记忆**：一台离线服务器 15s 超时会串成 N×15s；改为并发 4 路 +
  失败退避 30 分钟 + 失败原因回传设置页（红灯 badge）
- **备份漏 MCP 配置**：`data/mcp.json` 不在 settings 表里，恢复后市场装的 MCP 全丢；
  export/import 增加 `mcp_servers`（URL 凭据打码）
- **CLI 与对话权限耦合**：CLI 走 chat 开关，关掉对话管理后 CLI 也被禁；改为独立通道判定
- **市场条目被标成「内置」**：导致删除时走 force 分支、语义混乱；市场安装不再标记 builtin
- **远程 MCP 默认停用不符合「默认配置好」**：远程 HTTP（deepwiki/gitmcp）改为默认启用，
  stdio 仍默认停用（依赖 npx/uvx），并加「全部启用/全部停用」
- **设置导航**：新旧两套「Agent 与技能」重复，旧页面（AgentSection/ai-generate）已删除；
  导航重组为「基础设置 / AI 与自动化 / AGENT 能力 / 数据与安全 / 评测」五组
- 死代码：`routes/studio.py::_apply_entries`、`market._SKILLS_MP`、`watchdog` 空分支、
  `default_studio.permissions.max_tool_turns`、32 个旧 Agent 页孤儿 i18n 键

### 修复（第一轮）

- 设置页新增分区原先会挤在一屏：改为左侧分组导航 + 移动端横向滚动条，14 个入口可达
- 默认角色/技能升级后老库看不到新内置项：启动时按「只补缺失、不覆盖用户改动」合并
- 技能定时动作在 Studio 侧编辑后不生效：写操作后自动 `sync_skill_jobs()`
- 打包版缺 Studio 默认包（JSON 非 Python 模块，PyInstaller 静态分析发现不了）：spec 与 pyproject 同步收录

### 变更：品牌更名 Moneyhelper

- 项目名、包名、CLI 命令、Docker 服务/数据卷、PyInstaller 产物、环境变量前缀统一为 Moneyhelper；
  旧前缀 `XIAOMAN_*` 由 `backend/app/compat_env.py` 兼容读取（新名优先），旧部署升级不会切到空库
- 仓库内所有对外品牌文案（README / docs / 页面标题 / PWA manifest / 双语 i18n）同步更名
- Logo 重绘为「M 折线 + 增长箭头」钱币标，重出 icon.svg / 192 / 512 / apple-touch-icon / app.ico
- 品牌 slogan 改为「算清每一笔，攒稳每一步」并在登录页展示；页面 theme-color / manifest 主色对齐品牌绿 `#0f8a73`
- 新增 `tests/test_brand.py`：旧品牌零残留成为可执行约束（兼容层与升级说明白名单除外）

### 修复

- `paper_trade` / `paper_overview` agent 工具因缺少 `validate_trade` / `fee_for` / `estimate` /
  `ranking` / `team_summary` 导入，调用即 `NameError`；补测试覆盖开户→下单→总览全链路
- `calculations` 门面中 `paper.build_equity_curve` 被 `portfolio_risk` 同名函数覆盖，
  两种签名互相踩；paper 版改名 `build_snapshot_curve` 显式导出
- `docs/ARCHITECTURE.md` 与 `docs/architecture.md` 仅大小写不同，Windows 克隆后互相覆盖且
  mkdocs `--strict` 失败；详版重命名为 `docs/ARCHITECTURE-detail.md`
- `docs/promo.html` 引用了 6 张不存在的截图；改为实际存在的文件
- README 的页签数量（八个 → 九个，漏列模拟盘）与代码不一致
- `frontend/package-lock.json` 版本号停留在 3.0.0，与 `package.json`/`version.py` 漂移
- 本机新版 ruff 在改名前的 v4.2 提交上检出 38 项问题（未用导入、同名重定义、5 处未定义名等）；
  v4.0–v4.2 三个提交直接推到了 GitCode，未经 GitHub CI（最后一次 CI 停在 d9837c2），因此一直没被发现
- 五端一度不同步：GitCode 有 v4.0–v4.2，GitHub 三仓与 Gitee 停在 d9837c2；本次已全部对齐
- 限流配额差一：`len(bucket) >= max` 让「200 次/分钟」实际只放行 199 次，与响应头 `X-RateLimit-Limit: 200` 矛盾
- 登录防爆破只按 `X-Forwarded-For` 取 IP，未校验来源，可伪造头绕过 IP 维度限流；
  改为默认不信任该头，仅 `MONEYHELPER_TRUST_PROXY=1`（可信反代部署）时采信，CONFIG/DEPLOY 中英文四份文档同步说明

## [4.2.0] - 2026-10-27（团队模拟盘：多成员炒股看板，事件溯源内核）

> 延续 4.0/4.1 原则：**所有数字由代码重放算出，不是模型编的**。这次把「人」引进来——
> 多成员虚拟账户、下单成交、持仓估值、团队排行、净值曲线，一套券商终端式看板。

### 新增：团队模拟盘引擎（`app/calculations/paper.py`）

**事件溯源设计**：账户只存开户参数（初始资金），持仓/现金/成本全部从交易记录**重放**得出——
无状态漂移、可审计、可单测。删除/回滚一笔交易即回到对应时点。

| 能力 | 内容 |
|---|---|
| 整手成交 | 买入按 100 股整数倍（`round_lots`），卖出可零股 |
| A股费用口径 | 佣金双边 0.025%（最低 5 元）+ 卖出印花税 0.05% |
| 加权成本 | 买入合并摊薄、卖出不变，盈亏/盈亏% 逐持仓给出 |
| 估值降级 | 缺现价时用最后成交价并标注 `stale`（默认口径，下单时前端填现价） |
| 团队汇总 | 资金加权收益率、总资产、总盈亏、活跃持仓数 |
| 排行 | 收益率降序 + 净值兜底，纯函数可复现 |

### 新增：持久化与 API（`app/db/paper.py`、`app/routes/paper.py`）

- 三表：`paper_accounts` / `paper_trades` / `paper_snapshots`（租户隔离，已注册 `_TENANT_TABLES`）
- 上限治理：每团队 12 账户、单账户 500 笔；快照按日幂等 upsert（净值曲线存档）
- 六端点：`GET/POST /api/paper/accounts`、`DELETE /api/paper/accounts/{aid}`、
  `GET /api/paper/accounts/{aid}`（估值+净值曲线+最近交易）、
  `POST /api/paper/accounts/{aid}/trades`（引擎校验→手续费→落库→当日快照）、
  `POST .../snapshot`（手动存档）
- agent/MCP 工具 ×3：`paper_open` / `paper_trade` / `paper_overview`（工具总数 34）

### 新增：前端「模拟盘」工作台（导航第 9 tab，券商终端式看板）

- **团队摘要条**：账户数 / 总资产 / 总收益 / 团队收益率 / 活跃持仓
- **排行条形图**：成员收益率横向 bar（A 股红涨绿跌、正负分色）+ 明细行（排名/资产/盈亏/持仓）
- **账户详情**：净值曲线（对 1.0 基准）+ 持仓市值 donut 饼图 + 持仓盈亏表 + 最近 20 笔交易表
- **交易表单**：买/卖切换（红买绿卖）、代码/现价/股数、整手与现金不足即时校验、佣金+印花税费用预估、成交后自动刷新净值与排行
- **开户表单**：成员名 + 初始资金（≥1000），一键入队；删除账户连同交易/快照级联清理
- 图表全部走 `useEChart` / `useCandleColors` / `usePalette` 共享基建，深色模式与红涨绿跌方案即时换色

### 验证

- 后端：引擎 19 项单测 + API 集成测试（开户→下单→排行→详情→删除全链路、400/404 分支），全量回归通过
- 前端：tsc 类型检查、vitest 111 passed、vite build 绿
- 版本 4.2.0 三处同步（`version.py` / `pyproject.toml` / `package.json`）

## [4.1.0] - 2026-10-26（投研深化：统计预测 + 财报可视化增强）

> 延续 4.0 原则：**确定性计算 + 可复核输出**，预测也交给统计引擎而非模型猜。

### 新增：价格统计预测引擎（`app/calculations/forecast.py`）

| 能力 | 内容 |
|---|---|
| 线性趋势 | 最小二乘回归外推未来 N 期（斜率方向 → 偏多/偏空/中性） |
| 波动率 | 对数收益率年化波动率（√252），区间宽度随波动率放大 |
| 蒙特卡洛 GBM | 固定种子（42）可复现，2000 条路径 → 中值 + 5%/95% 分位区间带 |
| 均值回归 | 当前价相对 20 日均线偏离 %，偏离 ≥5% 提示回归倾向 |
| 结论 | 模板化中文说明（统计情景推演 + 免责声明），无需模型 |

新增端点 `/api/research/forecast`；agent/MCP 工具 `research_forecast`（工具总数 31）。

### 新增：财报分析增强

- `trends.cashflow_stack`：经营 / 投资 / 筹资三流序列（供前端堆叠柱图与现金净增加额汇总）
- 每期原始三流随 `periods[].cashflow` 返回，多期对比可直接落表

### 前端深化（金融可视化）

- **投研页**：K 线蜡烛改 **A 股红涨绿跌**（跟随全局颜色方案，us 模式自动反转）；日/周/月周期切换；缩放重置按钮；新增「价格统计预测」面板（趋势线 + 中值 + 5%-95% 区间带 + 四项指标）；回测参数可调（双均线快/慢线、定投金额/间隔）；双均线交易回合明细表
- **财报页**：现金流三流堆叠柱图 + 现金净增加额汇总；杜邦拆解条图（三因子 × → ROE，缺因子标注）；多期指标对比明细表（14 项指标 × 各期，同比/现金流着色）
- 新增共享 hook `useCandleColors`（解析 `--color-up/--color-down`，方案切换即时换色）

### 测试与修复

- 新增 `tests/test_forecast.py`（18 项：趋势/波动率/GBM 可复现/区间带/文本）+ API 用例
- 修复 `test_secrets.py` 超时：改用 `git ls-files` 只扫代码树（语义更贴合，避开 node_modules 海量遍历）

## [4.0.0] - 2026-10-26（财务智能体工作台：投研 + 财报分析）

> 定位升级：从「能管仓位的财务部门」变成「**垂直财务智能体工作台**」——对话只是入口，
> 八个页签整页切换，每页都是「指标条 + 图表 + 明细表」的决策看板。
> 新增两个垂直引擎（投研 / 财报），延续 3.0.0 的原则：**确定性计算 + 可复核输出**。

### 新增：股票投研引擎（`app/calculations/{technical,backtest}.py`）

| 能力 | 内容 |
|---|---|
| 技术指标 | MA(5/10/20/60)、EMA、MACD(12/26/9)、RSI(14)、BOLL(20,2σ)、KDJ(9,3,3) |
| 信号合成 | 规则引擎：MA 金叉死叉 / MACD 金叉死叉 / RSI 超买超卖 / 布林突破 / KDJ 金叉死叉 / 放量，带多空倾向聚合 |
| 策略回测 | 双均线（MA5/20，含交易成本）、定投（固定间隔定额）；总收益、年化、最大回撤、夏普、胜率、盈亏比、资金曲线 vs 买入持有 |
| 行情源 | 直接复用东财 K 线层（push2his 前复权），失败降级标注原因，不 500 |

新增 REST 端点：`/api/research/{analyze,backtest,overview}`；3 个 agent/MCP 工具
（`research_analyze` / `research_backtest` / `statements_analyze`）。

### 新增：财报分析引擎（`app/calculations/financial_statements.py`）

| 能力 | 内容 |
|---|---|
| 指标 | 20+：毛利率/净利率/营业利润率/ROE/ROA、资产负债率/流动比率/速动比率/利息保障倍数、三类周转率、经营现金流/净利润、现金营收比、同比成长 |
| 杜邦拆解 | ROE = 净利率 × 总资产周转率 × 权益乘数，缺因子标注不完整 |
| 异常预警 | 规则引擎：经营现金流为负、利润含金量低、商誉占比>20%、高杠杆、流动比率<1、毛利率骤降、应收/存货异常 |
| 报告 | 模板化中文分析报告（确定性，无需模型） |
| 持久化 | 三表 JSON 落本地库（financial_statements 表，租户隔离），可重新分析/删除 |

新增 REST 端点：`/api/statements/{analyze, 保存, 列表, 详情, 删除}`。

### 新增：前端投研页 + 财报分析页（可视化差异化）

- **投研页**：现价条 → 技术指标卡 → 可缩放 K 线主图（蜡烛 + MA5/20/60 + 布林带切换，成交量副图）
  → 信号流 → 策略回测（双均线/定投切换，指标条 + 资金曲线对比）；行情不可用逐块降级
- **财报页**：三表 JSON 输入（一键载入示例）→ 四组指标卡 → 营收&净利/盈利比率/偿债/现金流趋势图
  → 五维财务雷达图 → 预警流 → 报告文本 → 本地保存与重新分析
- ECharts 按需注册新增 candlestick / dataZoom 模块；首屏包不含投研/财报代码（懒加载）

### 文档与版本

- README / README.zh 定位重写：明确「与通用智能体的区别」，对话入口 + 工作台主场
- 国产模型优先表述（DeepSeek / 豆包 / 通义 / Kimi），弱化国外平台
- 版本号 3.0.0 → 4.0.0（version.py 单一真源）

## [3.0.0] - 2026-10-24（投资策略引擎 + 可复核底稿 + 模型评测）

> 定位升级：从"会记账的助手"变成"能管仓位的财务部门"。
> 三条主线都是**确定性计算 + 可复核输出**，没有一处让模型自己算数。

### 新增：投资策略引擎（`app/calculations/{portfolio_risk,strategy,valuation}.py`）

纯标准库实现，零新增依赖。所有指标口径写进 docstring，样本不足时返回
`null` 并标注原因，绝不返回看起来合理的假数值。

| 能力 | 内容 |
|---|---|
| 组合风险 | 年化波动率、夏普、索提诺、最大回撤、Calmar、Beta/Alpha、历史模拟法 VaR(95%)、上涨天数占比、单日最佳/最差 |
| 基准对比 | 沪深300/上证/深成/创业板四条基准，净值曲线双线归一化对比，超额收益 |
| 再平衡 | 目标配置 + 容忍带（3/5/8/10%），输出买/卖金额与整手股数；A 股卖出可零股、买入必须整手 |
| 估值温度计 | 当前价在近 750 个交易日区间中的位置分位，五档分区（低位区/偏低/中枢/偏高/高位区） |
| 定投 | 月/周计划、累计投入、份额、成本线、当前盈亏、下一期扣款日；数据覆盖前的定投日不补记 |
| FIRE | 目标本金（年支出/提取率）、完成度、储蓄率、复利年限；不可达时返回 `reachable=false` 而不是一个假年限 |

新增 6 个 REST 端点（`/api/strategy/*`）、5 个 agent 工具、5 个 MCP 工具
（外部 AI 也能调用），以及前端「投资策略」页（风险指标条 + 净值曲线 +
再平衡表 + 估值色阶 + 定投表 + FIRE 进度）。

### 新增：审计底稿导出（M6.1）

`GET /api/audit-report` 把 provenance 链路渲染成可归档 HTML：每条记录带
来源徽标、操作人、before/after **只列变化字段**的差异表。浏览器内一键
打印为 PDF。输出 HTML 而不是 PDF 是为了不引入几十 MB 的渲染依赖；
所有动态内容经 `html.escape`，并附 CSP 头禁用外部资源。

### 新增：模型评测题库与判分器（M6.3）

`app/eval_bank.py` 50 道题，覆盖记账解析/预算/负债/持仓/策略/口径推理六类。
`app/model_eval.py` 用**确定性判据**打分（数值按容差、文本按关键结论），
不让 LLM 给自己打分。端点：`/api/eval/{questions,run,score,leaderboard}`。
未配置模型时明确返回未评分，不生成假成绩。

### 性能：后端预聚合（M5.3）

`/api/dashboard` 本月现金流改走 SQL `GROUP BY`（`db.month_cashflow`），
流水明细限 500 条 + 独立总数；加 10 秒 TTL 缓存（键含 DB 路径与租户），
所有写路径（记账/持仓/负债/订阅/目标/预算/设置/确认执行/对话记账）
统一失效。账本十万行时不再把整库搬进内存。

### 修复：界面口径与真实缺陷（截图审查发现，全部有回归测试）

- **持仓编辑成本价放大 100 倍**：`positions[].cost` 是总成本，编辑框要每股成本；
  新增 `cost_per_share` 字段，前端与"追加持仓"都改用它。
- **占比双口径打架**：`by_asset` 同时给 `pct`（相对总市值，合计 100%，
  供饼图与占比列）与 `investable_pct`（相对非现金，供集中度判定）；
  此前现金行也用非现金分母，导致占比列合计 126%、风险提示 50.4% 与
  集中度 63.6% 同屏并存。
- **今日盈亏恒为 +0.00%**：分母把已是总额的 `cost` 又乘了一次股数。
- **健康评分两套值（51 vs 50）**：`/api/calculations/health` 改走
  `analysis.health_check` 单一实现。
- **亏损写成"浮盈"**：文案按盈亏正负切换浮盈/浮亏。
- **总资产两个值（282,540 vs 264,884）**：`/api/calculations/net-worth`
  与健康评分都改用实时行情，与总览同源。
- **手机端**：设置项 Row 改上下堆叠（供应商选择器不再横向溢出）；
  对话上下文条改 `sticky top-0`（不再被顶栏裁切）。
- **饼图中心文字被扇区覆盖**：环孔从 0% 改为 48%。
- **命令面板**补「去投资策略」入口。
- **表格/统计格**：占比列合计归 100%；平板宽度下大数字不再断行。

### 仓库与文档

- 删除入库的 `frontend/coverage/`（48 个产物文件）与零引用的 `docs/demo/`（980KB 旧图）。
- `scripts/push-all.sh` 重写：5 目标真实可用，支持 `--dry-run`/`--only`，
  凭据只从环境读取、打码输出。
- README 补 Release/CI/Docker badge、30 秒上手、Why Moneyhelper 对比、策略页截图；
  测试数统一为真实值。
- PROGRESS 同步到 3.0.0；ROADMAP-v3 标注为历史快照；三份旧审计文档加
  「历史快照，不代表当前状态」声明并归入「质量与审计（历史）」分组。

### 验证

- 后端 **906 passed**（原 791 + 新增 115）；`ruff check app tests` 全过。
- 前端 111 单测 + tsc + vite build 全过。
- 截图审查 15 张（桌面/手机/平板/暗色/空库/降级），逐张人工核对，无
  `undefined`/`NaN`/空白/裁切。

### 说明

组合风险曲线是**按当前持仓回溯的模拟净值**，不是实盘历史成交净值；
接口用 `basis: "backtest"` 与 `basis_note` 明确标注，前端在卡片上展示该提示。

## [2.9.3] - 2026-10-23（安全与数据完整性收口）

- **MCP 侧补齐多用户 fail-closed 鉴权**：`/mcp`、`/mcp-sse` 的挂载守卫此前只校验共享口令
  与 Host/Origin，已注册用户的实例里仍可无令牌调用工具。现把主 API 的鉴权总闸
  （口令 + 有账号必须 JWT）抽取为 `middleware.auth_gate`，主 API 与 MCP 子应用共用同一套判定，
  消除"主站有防护、MCP 侧裸奔"的第二条信任边界。
- **工具入参校验真正落地**：`tool_schemas` 新增 `validate_tool_args`（`extra="forbid"` 此前
  只停留在 schema 声明、从不执行），并在三个执行边界统一接线——agent 工具循环
  （错误回填给模型 self-correct）、agent_graph action 节点（校验失败返回"失败"结果）、
  confirm 直接执行（校验失败返回 400，杜绝以空参/多参误触写工具）。
- **备份覆盖补齐**：备份/恢复此前漏掉附件、会话摘要、部门呈批件三张租户表，
  恢复后知识库、会话上下文、呈批历史会整体消失；现一并纳入导出与恢复
  （reflections / undo_records / pending_actions 为运维态数据，刻意不进备份）。
- **CSV 列映射确定性**：`generic_csv` 列名候选从 set 改为按优先级排列的元组，
  同一文件在不同进程（PYTHONHASHSEED 不同）下解析结果完全一致。
- **前端清理**：删除零引用的 `ui/tabs.tsx`（65 行，被 pill-tabs 取代）；
  `responsive-shots` 截图脚本改为先进「功能」页再点「总览」（主导航已无总览入口）。

## [2.9.2] - 2026-10-23（收尾：体检页去重 + 浏览器启动开关 + 清理）

- 体检页：下方维度卡不再重复「建议」（上方「优先处理」已列出），只保留现状描述。
- `run.py` 支持 `MONEYHELPER_NO_BROWSER=1`：自动化验证不再弹出系统浏览器；
  用户双击 exe 时仍自动打开（并把端口改为读取 `PORT`，此前硬编码 8788）。
- 清理：关闭全部开发/演示服务进程，移除 `out/` 临时截图与演示库、缓存目录。

## [2.9.1] - 2026-10-23（对话内富回答块 + 上下文条）

> 界面最后一层：让对话里的数字"能操作"，而不是只读文本。

### 富回答块（`components/chat/FinanceBlocks.tsx`）
后端一直有 `card` 事件带完整的 market / ledger / flags，但前端只画了个静态四宫格。
现在按数据的实际内容渲染三种可操作块：

- **持仓概览**：总市值 + 盈亏/收益率，列出前三大非现金持仓；
  点任一行展开该标的 60 日走势（纯 SVG，不引图表库）；底部提示超限项。
- **本月收支**：收入/支出/结余/储蓄率四指标 + 支出分类条形（按金额排序）。
- **需要注意**：风控 flags 列表，每条带「去处理」跳转到对应页面。

### 去重
同一信息此前会重复三遍（风险块 / SummaryBlock 的等级徽章 / Action 按钮）：
- 有富回答块时 `SummaryBlock` 只保留「Moneyhelper 的理解」（意图识别），不重复指标与等级。
- 有块时不再渲染 action 按钮（块内已有「查看 →」）。
- 风险块跳过集中度条目（持仓块底部已提示）。

### 上下文条
对话顶部新增一行：`本地数据 · 3 项持仓 · 2 条消息 · 更新于 16:59`。
没有它，回答里的数字缺少可信度锚点，用户不知道助手看的是哪份数据、多久之前。

### 验证
- 前端 111 单测 + 21 e2e 通过；后端 786 通过；
- 截图确认：持仓块可展开走势、收支块分类条形、风险块跳转、上下文条按实际数据渲染。

## [2.9.0] - 2026-10-23（补齐 Skill / Prompt / Plugin / 知识库 + Agent harness 加固）

> 按「设置里该有的四类能力」逐项核对：Skill 已有、Prompt 只读、Plugin 缺失、知识库缺失。
> 补完后 Agent harness 的三个缺口（循环、输出上限、重试）也一并补上。

### 四类能力盘点与补齐

| 能力 | 补齐前 | 现在 |
|---|---|---|
| Skill | 4 个内置 + 自定义可增删、可绑定时 | 不变（已完备） |
| Prompt | `agents/<name>/instructions.md` 文件驱动，**设置页不能改** | 新增「系统提示词」分区：可视化编辑、留空回落默认、4000 字上限、即时生效 |
| Plugin | **缺失**：外部 MCP 服务器只能手改 `backend/data/mcp.json`，格式错一处整份失效 | 新增「插件（MCP）」分区：增删、测试连接、显示已发现工具；URL 凭据打码；写工具仍被禁止 |
| 知识库 | **缺失**：附件只能附在单条消息上，不参与检索 | 新增「知识库」分区：上传文档→切片→BM25 检索→注入 system 消息；可逐个开关、删除 |

### 知识库实现（`app/knowledge.py`）
- 切片：段落优先 + 长段落带重叠滑窗（400 字 / 80 字重叠），避免把句子切断。
- 检索：复用 rank-bm25（与长期记忆同一套中文双字+单字分词），只保留 score > 0 的命中。
- 注入：拼成带文件名的片段，2400 字预算内按得分顺序截断。
- 开关：`knowledge_enabled`（默认 on），关闭后完全不检索。
- 为什么不上向量库：与「本地优先、零外网」冲突（embedding 需外部 API 或几百 MB 本地模型）；
  接口按 retriever 设计，将来换向量实现只需替换 `rank_chunks`。

### Agent harness 加固
- **工具循环检测**：连续 3 次用相同参数调同一工具时中断并告知模型「结果不会变化」。
  此前只有 turn_cap 兜底，要烧满 5 轮才停。
- **输出上限**：工具循环的模型调用补 `max_tokens=2048`，防超长生成拖到超时。
- **重试与超时**：非流式调用补 `num_retries=2` + `timeout=60`（与流式路径对齐）。

### 验证
- 后端 786 通过（新增：MCP 管理 8、知识库纯函数 9、知识库接线 3、循环保护 6）。
- 知识库接线测试断言「入库文档的原文确实出现在 system 消息里」，非入库文档不出现。
- 前端 111 单测 + 21 e2e 通过；设置页 16 个分区逐页截图无报错。

## [2.8.6] - 2026-10-23（修复 Windows exe 启动闪退）

- **Windows exe 双击闪退（Critical，CI 实测复现）**：`run.py` 打印中文横幅时，
  Windows 控制台默认编码是 cp936/cp1252，`UnicodeEncodeError: 'charmap' codec can't
  encode characters` → 未捕获异常 → 进程退出。现在启动时把 stdout/stderr 切成 UTF-8
  并带 `errors="replace"` 兜底。
- 移除 spec 里无效的 `croniter` hidden import（项目未使用该依赖，PyInstaller 报
  `Hidden import 'croniter' not found`，在 CI 中只是警告，但会干扰真实错误定位）。

## [2.8.5] - 2026-10-23（设置页使用逻辑修复）

> 逐个分区走查设置页，修的都是"用户会踩到但不会报错"的逻辑问题。

- **未保存改动静默丢失**：改完设置点「关闭」直接丢弃修改，没有任何提示。
  现在关闭前弹确认（放弃并关闭 / 继续编辑）。
- **访问口令页自相矛盾**：输入框说明"后端 API_TOKEN 相同时才生效"，下面又说
  "未设置时无需口令"，用户填完无从判断是否生效。现在 `/api/health` 返回
  `auth_mode`（token / accounts / local），页面顶部直接显示当前实例的真实鉴权模式，
  并区分「需要口令 / 已启用账号体系 / 本机免登录」三种情况下的操作指引。
- **默认配置只读且无指引**：「Agent 与技能」底部展示默认语言/模型/审批阈值/工具轮次，
  用户看到数值却不知道去哪改。现在每项下方标注实际修改位置。
- **危险操作无区分**：「清空全部历史」与普通按钮同样式。改为危险色描边，
  并把「备份与恢复」独立成段，与危险操作分开。
- 「恢复」按钮文案改为「加载示例数据」，明确它做的是覆盖式载入演示数据。
- 设置页内容区放宽（max-w-5xl → 6xl 并改为 flex 布局），1440 下不再出现右侧大片空白。

### 验证

- 后端 760 通过（新增 3 项 auth_mode 回归）；前端 111 单测 + 21 e2e 通过。
- 设置页 13 个分区逐页截图 + 无 console/page error。

## [2.8.4] - 2026-10-22（设置页左右分段导航 + EXE 图标/版本信息）

### 界面

- **设置页改为真正的左右分段导航**：桌面左侧固定导航栏（三组：基础设置 / AI 与自动化 /
  数据与安全），右侧内容区独立滚动；手机端改为顶部横向分段条（一次一段，单次点击到达），
  替代原先需要两次点击的两层折叠。
- 分段控件与标签在 390px 下不再被挤压换行。

### 打包

- `moneyhelper.exe` 嵌入图标（`backend/app.ico`，7 个尺寸）与版本资源
  （FileVersion / ProductName / FileDescription 来自 `version.py` 单一真源）。
- 实测：`FileVersion 2.8.3`、`ProductName Moneyhelper`，运行首页 200 / API 正常 / MCP 正常。

## [2.8.3] - 2026-10-22（安全审计 + 全维度审查修复 + README 重做）

> 一次产品级审查：安全、可靠性、性能、可维护性、测试有效性、竞品对标。
> 所有发现均附复现路径；修复项均有回归测试。

### 安全（Critical / High）

- **认证绕过（Critical）**：`api_auth` 只在设置了 `API_TOKEN` 时校验，未设置就完全放行；
  租户由 JWT 解析、失败一律归默认租户 0。结果是注册了用户的实例，任何人无令牌即可
  `GET /api/dashboard`、`GET /api/export` 读到全部账本。已复现（返回 200 + 数据）。
  修复：库中已有账号时强制 JWT（共享口令除外），无用户时保持本机免登录。fail-closed。
  回归：`test_no_token_rejected_once_users_exist` + `test_no_token_allowed_when_no_users`。
- **MCP 工具绕过写保护（High）**：模型可见工具已排除写操作，但 `mcp__` 前缀走
  `resolve_mcp_tool` 分支，不受 `WRITE_EXCLUDED` 约束——外部 MCP 服务器若暴露
  记账/下单能力，模型可绕过确定性写分支直接调用。修复：MCP 工具按去前缀后的名字
  比对禁止清单。回归：`test_agent_mcp_guard.py`（9 项）。
- **限流可绕过（Medium）**：限流按 `client.host` 原始字符串建桶，双栈监听下
  `127.0.0.1` 与 `::1` 各拿一份配额。修复：`_normalize_ip` 归一化回环写法。
  回归：`test_rate_limit_ip.py`（6 项）。
- **ECharts XSS（Moderate，GHSA-fgmj-fm8m-jvvx）**：`npm audit` 实测存在，
  升级 echarts 5.5 → 6.1.0，复测 0 vulnerabilities，页面渲染回归通过。

### 界面缺陷（实测发现并修复）

- **图表整块空白（High）**：`useEChart` 的初始化副作用在组件提前 `return null` 时
  跑过一次、`ref` 为 null 就退出；数据到达后容器才出现，但再也不会初始化。
  健康五维雷达、现金流瀑布、支出结构、订阅时间线四个卡片全部受影响。
  修复：deps 变化时若容器存在但实例不存在，补一次 init。
- **订阅时间线不可读**：用气泡大小表达金额，¥2,034 被放大到占半张图、¥18 小到看不见。
  改为横向条形图（长度编码金额），并标出扣款日。
- **命令面板被裁切**：面板高度未随视口约束，最后两个分组被截断；Esc 也无法关闭。
  改为 `max-h: calc(100dvh - 16vh)` + 内部滚动 + Esc 关闭。
- **行情列表每行一条 404**：场外基金（如 110011）没有 K 线，前端仍逐行请求。
  改为按后端同一套规则预判，跳过不支持 K 线的标的。
- **净资产卡布局松散**：环图与明细分列两端、数值贴最右。改为整体限宽 + 固定数值列。
- **持仓页右栏留白**：补「风险提示」卡（直接列出后端算好的 flags）。

### 测试与文档

- 后端 757 通过（新增 17 项回归）；前端 111 单测 + 21 e2e 通过。
- 覆盖率实测：后端行覆盖 81.51%（9388 语句）；前端 53.55%（含未被单测覆盖的 UI 组件）。
- `docs/screenshots/` 全部重拍（旧图是两代之前的界面，与当前 UI 不一致）；
  README 中英双版重写「界面」章节与截图矩阵。
- 新增 `frontend/scripts/readme-shots.mjs`（README 展示图）与 `ui-audit.mjs`（全界面审查截图）。

## [2.8.2] - 2026-10-22（对标股票软件重做三个数据页 + EXE 实打包）

> 用户反馈"界面参考 codex/qoder/zcode、工作台软件和股票软件"，并追问是否打包了 exe。

### 三页重做（借鉴股票/证券软件的信息组织）
- **持仓页**：摘要条 → 集中度超限提示条 → 左「明细表格 + 盈亏贡献条形图」/ 右「集中度 + 行业分布」双栏。
  新增 `PositionContributionCard`：按盈亏绝对值排序的横向条形图，回答"这些钱是哪几只赚/亏出来的"。
- **行情页**：改为股票软件式「列表 + 详情」双栏。左侧自选/持仓表新增「近 60 日」迷你走势列
  （纯 SVG `MiniSparkline`，不引图表库）；右侧 `MarketDetail` 显示选中标的的走势、区间涨跌、
  60 日高/低，并可展开 K 线。
- **记账页**：流水从"日期独占一行"的两行结构改为标准单行表格（日期 / 条目 / 分类 / 金额 / 操作），
  11 条流水一屏看完；去掉固定 320px 内滚动（最后一行会被切一半）。
- **体检页**：评分卡改为「评分 + 状态计数 + 五维进度条」，右侧放结论与「优先处理」清单；
  下方维度卡改两列并补上建议文案（原来 4 张卡在 3 列网格里空一格，且只显示原始 `warn`/`bad`）。
- **总览页净资产卡**：环图与右侧明细两列对齐，环形中心显示资产合计；去掉重复的图表内图例。

### EXE 打包
- 实际执行 `pyinstaller moneyhelper.spec` 产出 **`backend/dist/moneyhelper.exe`（约 150MB）**，
  并实机运行验证：首页 200、`/api/health` 正常、`/mcp` 正常（406 为缺少 Accept 头的规范行为）。
- 说明：此前仓库只有打包脚本、从未真正产出过 exe。本次验证了完整链路。

### 行情可用性修复
- **K 线在部分网络下永远取不到**：`push2his.eastmoney.com` 的 HTTPS 握手会被中间设备重置
  （curl 正常、httpx 被断），但同路径 HTTP 端点可用。`_fetch_kline` 增加 HTTP 回退。

### 验证
- 后端 pytest 741 通过；ruff 通过。
- 前端 tsc 通过；vitest 111 通过；Playwright e2e 21 通过；vite build 通过。
- 桌面/手机/平板 + 亮色/暗色全量截图复核，无 pageerror。

## [2.8.1] - 2026-10-21（界面审查修复：整页财务工作区 + 8 个真实缺陷）

> 逐页截图审查（对话 / 财务五页 / 设置十三区 / 记账五面板 / 弹窗 / 手机 / 平板 / 暗色 / 空库），
> 每个界面都实际点开验证，发现的问题按"影响用户"排序修复。

### 布局：数据页从侧栏抽屉改为整页工作区
- 总览/持仓/行情/记账/体检此前塞在 440px 右侧抽屉里，表格被挤成两列、金额折行。
  改为**整页切换**（左侧导航保持不动，主区按 1200px 居中），对标 opencode / codex 的 section 导航。
- 顶部用页签切换五个子页，当前项下划线高亮；右上「返回问答」回对话。
- 删除 `DataModal.tsx`，新增 `FinancePage.tsx` / `HealthPage.tsx`。

### 修复的真实缺陷
- **命令面板完全错乱**：`cmd-item` 类名没有任何 CSS 定义，所有命令退化成竖排裸文本。
  补齐条目/分组/选中态样式（`index.css`）。
- **命令面板 Esc 关不掉**：只监听了 Ctrl+K，按 Esc 无反应，面板会卡住整屏。
- **K 线弹窗永远空白**：`useEChart` 的初始化副作用在面板关闭时就跑完，ref 还是 null，
  之后再打开不会重新初始化。把图表拆成只在打开后挂载的子组件。
- **行情搜索永远返回空**：东财 suggest 的响应是顶层 `QuotationCodeTable`，
  代码却读 `body["data"]`，所以搜什么都"没找到"。修正解析并抽出可测试的 `_parse_suggest`。
- **「这个月的开销怎么样」被判成闲聊**：`LEDGER_WORDS` 只收「支出」，
  口语「开销/开支/花费」全部漏掉，回答回落成"未接入模型"文案。补词并加回归测试。
- **财务快照卡显示无意义的「—」**：问持仓时后端只查 market，卡片仍渲染 ledger 字段。
  改为按实际拿到的数据渲染格子，展开按钮也指向对应页面。
- **新对话在侧栏留空会话**：每点一次「新对话」就立刻在库里建一条"新会话"。
  改为只切本地临时线程，首条消息发出后才真正建会话（对齐 ChatGPT）。
- **点「新对话」后界面停在旧会话**：先设临时线程再等接口返回，切换滞后。
- **审计日志/日志页被 asyncio DEBUG 刷屏**：Windows 的 Proactor 每建一个事件循环打一行，
  把真告警挤出屏幕。压到 WARNING，并给日志页加「只看问题 / 全部」切换。
- **体检空库显示 0 分**：数据不足时后端返回 score=0 且无维度，界面显示红字 0 分 + 三个空徽章，
  像是体检失败。改为引导态。
- **空库首屏文案**：标题从「我是 Moneyhelper」改为统一的「问你的钱，这里都有答案」，
  副标题按有无数据切换引导语。

### 其他一致性
- 行情自选/持仓列表改为对齐的表格（标的 / 现价 / 涨跌幅 / 操作），移动端退回两行卡片。
- 记账流水改成真正的四列表格行（日期分组头 + 条目 / 分类 / 金额 / 操作），移动端不再重复日期。
- 移动端底部导航「总览」改名「财务」（该入口覆盖五个子页），财务子页也高亮。
- 财务页顶栏保留移动端菜单按钮（原先后返回按钮把菜单挤掉了）。
- 设置页分段控件在 320–390px 不再把「标准/大/特大」压成竖排。
- 体检页评分卡改为评分 + 状态计数 + 五维卡片（原来直接显示 `warn` / `bad` 原始枚举）。
- 新增 `frontend/scripts/ui-audit.mjs`：一条命令拍完桌面/手机/平板所有页面与弹窗。

### 验证
- 后端 pytest 741 通过（新增 4 项：搜索解析 2、口语路由 1、空查询 1）；ruff 通过。
- 前端 tsc 通过；vitest 111 通过；Playwright e2e 21 通过；vite build 通过。
- `ui-audit.mjs` 全量跑完：无 pageerror、无 console error。

## [2.8.0] - 2026-10-21（前端重构：对齐 ChatGPT 的对话界面范式）

> 用户反馈"前端拉垮、不要自己乱做"。本轮不发明设计，按 ChatGPT 已验证的界面结构重排。

### 布局
- 侧栏改为浅灰底（`--sidebar`），主区纯白：只有发送键/焦点态保留品牌绿，交互底色一律中性灰，
  不再整屏泛绿。
- 侧栏结构对齐 ChatGPT：品牌（名称+标语）→「新对话」→ 搜索 → 今天/过去 7 天/更早 分组 →
  底部功能入口（总览/定时产出/财务部门/晨报/设置）。会话项悬停才出重命名/删除。
- 顶栏压成 48px 无分割线工具条：移动端导航 + 品牌，右侧仅语言/明暗/设置三个弱化图标。
- 对话列固定 `48rem` 居中；用户消息改为中性灰圆角气泡（原为绿色），助手消息无容器、
  左侧品牌头像 + 可读宽度正文。
- 空态：品牌标记 + 一句话标题 + 4 个带图标的建议卡（有账本数据时用后端按真实数据生成的建议）。
- 输入器改为 ChatGPT 式圆角容器：附件、文本域、语音、发送同处一框，聚焦时整块抬起。
- 助手操作条（复制/重新生成/下载）移到回答下方，悬停显示。
- 移除右侧常驻 Agent 面板：计划与工具调用在回答内已有内联展示，侧栏只会挤压对话。

### 排版与细节
- 新增 `.md-body` 排版规范：16px / 1.75 行高、标题层级、列表缩进、表格与引用块边界，
  Markdown 回答的阅读密度对齐 ChatGPT。
- 新建会话改为立即切到临时线程（此前会先停在旧会话，需等接口返回才切换）。
- 设置页改为独立全屏页：顶部标题 + 关闭，内容区居中 `max-w-5xl`；桌面侧栏去掉卡片描边。
- 移动抽屉背景统一为侧栏灰，去掉与内容区不一致的卡片白。
- 助手显示名与首屏标题随界面语言切换（英文 Moneyhelper / 中文 Moneyhelper）。
- 删除 `ChatHeader.tsx`、`AgentPanel.tsx` 两个不再使用的组件与相关文案。

### 验证
- `tsc --noEmit` 通过；vitest 111 通过；Playwright e2e 21 通过；`vite build` 通过。
- 1440×900 / 1024×768 / 768×1024 / 390×844 四档截图复核，横向溢出均为 0。

## [2.7.1] - 2026-10-21（专家评审 9 个 P0 全部修复）

> 独立专家评审给出 19/50 打回，逐条修复后复验。

### P0（数据安全 / 功能不可用）

- **迁移备份在 WAL 下是空文件**：`shutil.copy2` 只复制主文件，已提交数据可能全在 `-wal`。
  改用 `sqlite3.Connection.backup()` 生成一致性快照；**备份失败直接中止迁移**（不再"留痕继续"）。
- **迁移非原子**：重建表（DROP+RENAME）无事务，崩溃即永久卡死。整个迁移包进
  `BEGIN IMMEDIATE ... COMMIT`，并新增 `_recover_stale_temp_tables()` 启动清理/恢复遗留临时表。
- **半迁移库永远修不好**：判据从"列是否存在"改为**主键形状**（PRAGMA），
  有 user_id 但主键仍是单列的库能被识别并重建。
- **注册接口必然 500**：passlib 1.7.4 读 `bcrypt.__about__`（bcrypt 5 已移除）导致哈希抛错。
  改为直接用 `bcrypt.hashpw/checkpw`；另修 `_ensure_secret()`（未跑 lifespan 时 JWT secret 为空）。
- **reset 抹掉全实例账本**：`DELETE FROM {t}` 无 WHERE。现在只清当前租户；
  已有用户时未登录调用返回 401。
- **settings / budgets / members 未隔离**：settings 主键改 `(user_id,key)`、
  budgets 改 `(user_id,month,category)`、members 加 `user_id` + `UNIQUE(user_id,username)`；
  `_COMPOSITE_MULTI` 负责旧库重建。
- **备份恢复丢流水**：恢复顺序改为 members → member_loans → transactions；
  `_restore_table` 不再静默 `continue`，失败即抛错整体回滚。
- **编辑 / 合并流水必报错**：多租户改造时补了 SQL 的 `user_id=?` 却漏传实参（6 处）。
- **审计写入提交他人事务**：`add_audit_log` 改为 SAVEPOINT 隔离（与 provenance 一致）。

### 其他

- **CLI 跨事件循环卡死**：读连接池与写连接都绑定事件循环，同一进程连续调用 `asyncio.run`
  会永久等待。读池加 `set_read_pool(False)`（CLI 禁用）、`init_db`/`_read_conn` 检测 loop
  归属、`close_db` 先回滚再带超时关闭；读池的 `mode=ro` 改 `PRAGMA query_only`（WAL 下
  mode=ro 会等写连接 checkpoint）。

### 回归测试

- 新增 `backend/tests/test_p0_regressions.py`（14 项），每条 P0 至少一个用例。
- 全量 737 passed；ruff / tsc / vitest 111 / e2e 21 / mkdocs strict 全绿。

## [2.7.0] - 2026-10-21（可安装性修复 + 多平台产物 + MCP 定时产出）

### 修复（可安装性，实测驱动）

- **`pip install` 出来的包根本跑不起来**：wheel 只含 5 个门面文件（15KB），
  真正的实现在 `backend/app` 下没有被打包；装完 `import moneyhelper.server`
  直接 `ModuleNotFoundError: app`。现配置 `package-dir` 同时安装 `app.*`，
  wheel 变为 320KB / 102 个文件；实测从 `C:/Windows` 目录导入成功、
  `moneyhelper.server.app` 是真实 FastAPI 实例、CLI `--help` 正常。
- **`pyproject.toml` 依赖漂移**：仍引用已删除的 mem0 / chromadb / opentelemetry /
  langchain-litellm，且 `moneyhelper.mcp` 未纳入包列表。已与 requirements 对齐。

### 新增

- **多平台桌面构建工作流** `.github/workflows/desktop.yml`：Windows / macOS / Linux
  三平台矩阵，各自打 PyInstaller 单文件，带"产物能启动并响应健康检查"的冒烟测试，
  tag 触发时自动附加到 Release。
- **MCP 定时产出资源**（Tasks 的可行替代）：
  - `moneyhelper://scheduled-outputs` —— 最近 10 条晨报/技能产出
  - `moneyhelper://scheduler-status` —— 调度状态
  为什么不用 Tasks：mcp 1.30 的 Tasks 仍是 experimental，fastmcp 2.x 未透传；
  而"客户端能拿到定时产出"用 resource 拉取即可满足，服务端仍由 APScheduler 生成。


### 修复（并行稳定性，根因）

- **审计写入破坏事务边界**：`provenance._persist_entry` 原先复用全局唯一写连接并
  `commit`，会把别的协程未完成的多语句事务一并提交。改为在同一连接上用
  `SAVEPOINT` 局部隔离——既不提交外层事务，也不因独立连接在 Windows 上与主连接
  互等而死锁（两种更简单的做法都实测失败过）。
- **进程级活跃成员状态跨用例泄漏**：`_active_member_id` 是模块级全局字典，
  某用例设置后未清理，会让后续用例把流水挂到"别的库里的成员 id"上，
  触发 `FOREIGN KEY constraint failed`。`temp_db` 与 `test_evaluate` 的
  fixture 现在逐用例清零。修复后连续 8 轮并行回归 723 项全绿（此前约每 5–8 轮
  偶发一次）。

### 验证

- 文档站静态校验：`mkdocs.yml` 的 16 个导航条目全部存在，全仓库文档相对链接 0 坏链
  （本机无法访问 pypi，装不了 mkdocs，故用静态校验替代 `mkdocs build --strict`）。

## [2.6.1] - 2026-10-21（流式断流不再伪装成功）

### 修复

- **半截回答被当成完整结果**：`apiStream` 原先只要收到过任意一帧就把连接关闭当作成功
  （`if (got) return`），断流时用户看到的是一段看似完整的文字，实际缺后半段。
  现在以服务端 `done` 终帧作为完成标志；已收到内容但未收到终帧时如实抛错。
- **错误时隐藏已收到的内容**：`ChatMessageBubble` 原先只要有 error 就整块替换成报错行，
  用户刚看到的文字会消失。现在有正文时保留内容，另起一行提示"回答可能不完整"。

### 测试

- 新增 e2e：拦截 `/api/ask` 只发两帧文本后关闭，断言页面既显示已收到的文字、
  也显示不完整提示。这条用例是驱动上述修复的回归护栏。

## [2.6.0] - 2026-10-21（测试真实性整改 + 权限模型 + 适老化 + 桌面端）

### 测试真实性（重点）

审计发现"看起来有测试、实际没验证"的情况，已整改：

- **`test_dept_agent.py` 的 7 个用例 mock 掉了 `agent.run_agent` 本身**，只验证
  "参数被传下去了"，真正的工具循环/参数解析/结果回填从未执行。新增
  `test_agent_real_loop.py`（6 项）：只桩模型 I/O 边界，让 agent 循环与工具实现
  真实跑起来，断言"工具被真实执行、结果被回填、账本确实变了、写工具不可见"。
- **删除 `ImportPanel.tsx` 及其 3 个假测试**：该组件与 `EntryView` 内的同名实现
  重复，实际是死代码；三条用例都在断言"渲染不报错"，其中一条与另一条完全重复。
- **补强 `test_evaluate`**：原先只断言 200，现验证返回结构（month/refreshed_at/
  summary/items）与每条评估项的字段契约。
- 新增语音 hook 测试 5 项（真实分支：不支持时的提示、识别结果写回、停止复位、语言跟随）。
- 迁移类测试加 `xdist_group` 隔离（会切换全局 DB_PATH，必须与其它用例串行）；
  连续 6 轮并行回归稳定在 721 项。

### 权限模型（方案 B）

对比三种方案后选择"严格隔离 + 管理员只读概览"：
- 每个登录用户只能读写自己的租户数据（角色不能越权读明细，有测试证明）。
- 管理员新增两个端点：`/api/auth/users`（账号列表）、`/api/auth/tenants-overview`
  （各租户**条数**概览）。**只给规模，不给金额/名称/流水**——管理员需要知道
  "多少人在用"，不需要知道"张三花了多少钱"；家庭共享由 members 机制承载。
- 非管理员 403、未登录 401，均有测试。

### 适老化

- 新增设置项 `text_scale`（标准/大/特大）与 `high_contrast`，通过根元素
  `data-*` 驱动全局 CSS：字号基准 16 → 18/20px，高对比加深文字与边框。
- 实测：手机宽度（390px）切到特大 + 高对比后仍无横向溢出。
- 语音识别语言改为跟随界面语言（此前硬编码 zh-CN，英文界面也用中文识别）。

### 桌面端（M4）

- 重写 `moneyhelper.spec`：清掉已删除的 mem0/chromadb/alembic/opentelemetry 引用，
  用文件系统递归收集 litellm 子模块 + 整目录收集其非 Python 资源
  （模型价格表、tokenizer）——缺任一项启动即失败，实测踩过。
- `run.py` 修数据目录：打包后默认 `~/.moneyhelper`（此前文档这么写但代码没做）。
- 实测产出 144MB 单文件，启动后健康检查 200、前端完整渲染、写入落盘、MCP 200。

## [2.5.0] - 2026-10-20（家庭账本上界面 + 升级路径实证）

### 新增

- **家庭账本界面**（设置 → 家庭账本）：成员增删、成员间借贷（记录/结清/删除）、
  家庭收支汇总与各成员占比。这套后端能力（12 个端点）此前完全没有前端入口。
- **升级演练脚本** `backend/scripts/upgrade_drill.py`：用旧版 schema 造一个带数据的库，
  再用当前代码打开，验证 12 张表数据完整、复合主键共存、重复启动幂等、旧路径自动搬迁。
- e2e 新增家庭账本全流程（添加成员 → 汇总 → 借贷 → 结清）。

### 安全

- **迁移前自动整库备份**：多租户迁移会重建四张表（DROP + RENAME，无回滚点），
  现在动结构前先复制一份 `<db>.pre-mt-<时间戳>`。备份失败只告警不阻断，但一定留痕。
- 迁移幂等有测试兜底：已迁移的库再次启动不会再产生备份。

### 验证

- 升级演练 ALL PASSED（旧库 12 张表 → 迁移后条数一致）。
- 迁移备份实测：`.pre-mt-*` 文件内容为迁移前状态（无 user_id、数据完整）。

## [2.4.3] - 2026-10-20（溯源链上界面）

### 新增

- **溯源链界面**（设置 → 数据与安全 → 溯源链）：把后端已有的 `/api/provenance` 接到前端。
  可按实体类型与 ID 过滤，逐条展开查看改动前/后快照，回答"这个数字是谁在什么时候改的"。
  此前该能力只有接口、界面上完全看不到——而这正是产品宣称的"数字可对质"卖点。
- 接口测试 2 项：写入产生溯源记录、按类型过滤、单条详情 404。

## [2.4.2] - 2026-10-20（Docker 数据持久化修复 + 实测验证）

### 修复（P0）

- **容器重建丢账本**：代码默认把库写在 `backend/app/data`，而 Dockerfile 的 VOLUME 与
  compose 挂的是 `backend/data`。实测确认：容器内写入的数据落在卷外，`docker rm` 即丢。
  现在库 / 备份 / LangGraph checkpoint 统一由 `MONEYHELPER_DATA_DIR` 决定（默认 `backend/data`），
  镜像内置 `/app/backend/data`，与数据卷一致。
- **旧数据自动迁移**：升级后首次启动若新位置无库、旧位置有库，自动搬移（连带 `-wal` / `-shm`，
  避免 WAL 中已提交事务丢失）。显式设置 `MONEYHELPER_DB_PATH` 时不猜。
- **备份与 checkpoint 同目录**：`BACKUP_DIR` 与 `agent_checkpoints.db` 一并跟随数据目录，
  不再散落在代码目录里。

### 验证（本轮实际执行）

- Docker 实机构建 + 运行：健康检查 `healthy`、首页 200、`/mcp` 200、以 uid 1000 非 root 运行。
- 容器写入数据 → `docker rm` → 重建 → 数据仍在（此前会丢）。
- 部门工单白名单补端到端测试：模型实际收到的工具面被收窄到工单声明的那一个。

### 文档

- `docs/planning/` 九份规划文档统一加「归档说明」：标明记录的是当时决策过程，
  当前状态以 PROGRESS 与代码为准（文中 mem0/规则引擎/react_agent 等已移除）。
- PROGRESS 里程碑校准：M2 95%、M3 100%（白名单已生效）、M4 60%（Docker 已验证）。

## [2.4.1] - 2026-10-20（关键端点测试补全 + 性能与超时）

### 新增

- **关键端点 HTTP 测试**（10 项）：`/api/confirm` 的一次性 token 语义（重复确认必须 409、写操作只发生一次）、附件上传/删除/类型校验、审计与日志列表。

### 修复

- **收尾请求不再拖死整次问答**：工具轮次用尽后本应基于已有结果成文，但此前该请求无超时预算，网关抖动时会挂到 120s。现收紧到 20s（外层 25s 兜底），超时立即走确定性模板——实测网关 504 时 1.1 秒内给出降级回答。
- **LLM 客户端指纹包含 api_key**：此前只比对模型名与端点，用户在设置页换密钥后仍复用旧 client，表现为"改了 key 仍 401，重启才好"。现用密钥哈希前 8 位参与指纹。

### 性能

- **MCP 工具发现加 30s 缓存**：每次问答都重新握手并 list_tools，实测拉长首 token 时间。缓存键包含配置指纹，换配置立即失效。

### 清理

- 删除与 `manifest.webmanifest` 逐字节相同的 `manifest.json`，同步更新 Service Worker 预缓存清单。

## [2.4.0] - 2026-10-20（完整多租户 + 遗留缺陷收口）

> 定位：一个实例支持多个独立账本，且历史数据可平滑升级。

### 新增

- **完整多租户隔离**：业务表新增 `user_id` 维度，JWT 登录用户各自拥有独立数据。
  - 四类"业务字段作主键"的表（持仓 `symbol`、订阅/负债/目标 `name`、自选 `symbol`）改为 `(user_id, 原主键)` 复合主键——两人都持有「茅台」或都有「买房」目标时不再互相覆盖。
  - `sessions.thread_id` 的全局唯一约束改为 `(user_id, thread_id)`；`conversation_summary` 同理。
  - 所有读写按请求上下文中的租户过滤（`app/db/tenant.py` 的 ContextVar），未登录请求落在默认租户 0。
  - 备份/恢复按租户隔离：恢复只清当前用户的数据，绝不抹掉别人的账本。
  - 自动迁移：启动时检测旧库并就地升级（补列、重建复合主键表、回填历史数据到默认租户），幂等可重跑。
- **租户覆盖护栏**：`backend/scripts/check_tenant_coverage.py` 静态扫描数据层 SQL，任何漏加 `user_id` 的查询都会报错；确需跨租户的维护操作须显式标注 `# tenant: allow`。
- **隔离测试**：数据层 7 项 + HTTP 端到端 4 项（两个 JWT 用户的持仓/流水/目标互不可见）。

### 修复

- **健康分统一口径**：`analysis.health_check` 改用五维加权（与 `calculations/health.py` 一致），并补上 `grade` 字段（呈批件此前一直显示"得分 X（—）"）。
- **部门工单白名单生效**：执行阶段按 `order.tools_allowed` 收窄工具面，LLM 派工的"只给两个工具"约束不再是空话。
- **MCP 清仓接入审批**：`shares=0`（清仓）此前算成 0 元永不触发审批，现按持仓市值兜底，清仓这种最不可逆的操作必须确认。
- **测试并行稳定**：`test_evaluate` 的临时库 fixture 未先关闭旧连接，共享默认库时会串数据；补 `close_db()`。
- **测试 JWT 密钥固定**：避免每次导入生成随机 secret 导致同轮测试签发/校验不一致。

## [2.3.0] - 2026-10-20（可用性总修：工具链路、部署、响应式、跨平台）

> 定位：把"能跑"变成"跑对"。本轮以实际运行验证为准，修复了会让核心能力整体失效的缺陷。

### 修复（P0）

- **工具调用整体失效**：LiteLLM 1.106 在带 `tools` 时会导入其内置 MCP 网关，该模块依赖 mcp>=2 才有的 `CacheableResult`，而项目锁定 mcp 1.30（fastmcp 2.x 要求 <2.0）。表现为任何 function calling 直接 ImportError，模型永远拿不到工具。现在显式传 `_skip_mcp_handler=True` 绕开这条未使用的分支。
- **前端静态托管被遮蔽**：MCP 子应用曾 `Mount("/")`，拦截所有未匹配请求，单端口部署时 `/` 与 `/index.html` 返回 503。改为只挂 `/mcp`，并新增精确路径路由，使 `/mcp` 与 `/mcp/` 都直达（不再 307）。
- **`/mcp` 鉴权与来源校验**：改为复用主应用同一套判定（口令 + 本机/内网来源 + Host/Origin 白名单），消除"主站有防护、MCP 侧裸奔"的第二信任边界。
- **MCP 批量导入 100% 失败**：`mcp_server.py` 中 `from ..csvimport` 越界相对导入，改为 `from .csvimport`。
- **设置页无法保存**：`saveMutate` 从未被调用，月收入/应急目标/储蓄率/晨报时间只改本地 state。新增底部保存栏（含未保存提示与放弃改动）。
- **首屏 hooks 顺序违规**：`App.tsx` 在部分 hooks 之间条件 return 登录页，已注册实例且无 token 时会白屏。条件 return 移到全部 hooks 之后。
- **依赖不可解**：`langgraph` 与 `langchain-core<0.4` 约束互斥；移除重复的 `react_agent`（官方 ReAct 包装）后统一走 `agent.run_agent`，依赖树恢复可解。
- **Docker 数据路径退化**：compose 注入空串导致 `MONEYHELPER_DB_PATH=""`，`Path("")` 解析为当前目录。路径解析改为忽略空值并展开相对路径；compose 不再传该变量。
- **`.env` 泄密路径**：一键脚本把含密钥的 `.env` 写到仓库根但未被忽略，现已在 `.gitignore` 覆盖根目录 `.env`。

### 修复（P1）

- **确认接口可重复执行**：新增 `claim_pending_action` 原子抢占（条件 UPDATE + rowcount 校验），并发/重放只有一方能执行；图内与降级路径都改用它。
- **成员删除外键失败**：改为先删 `member_loans` 再删 `members`，并包在事务里。
- **撤回流水外键失败**：`owner_id` 为空时保持 NULL，不再写成 0。
- **备份不完整**：导出/恢复补齐成员、借贷、自选、溯源、审计五类数据；流水恢复保留 `owner_id`/`is_shared`；格式版本升到 3（兼容读 v2）。
- **关闭晨报连带关掉订阅巡检**：两者解耦，巡检始终注册。
- **收益率口径**：简单收益率只把非工资性流入算作追加本金；XIRR 改为"成本投入 → 当前市值"两笔现金流，不再把生活收支混进投资收益。
- **附件上传必然 400**：前端不再对 FormData 强制注入 JSON Content-Type；后端校验 multipart 并拒绝 PDF（明确告知，而不是把二进制当文本）。
- **财务快照卡恒为空**：字段名修正为 `total_market_value`，储蓄率不再重复乘 100。
- **收件箱请求循环**：`markAllRead` 改用 ref 读取最新列表，回调身份稳定，不再触发 effect 反复请求。
- **Service Worker 永不更新**：构建脚本改为按内容哈希替换 `CACHE` 常量，并可幂等重跑。
- **行情下跌不显示跌幅**：涨跌额/涨跌幅改用允许负数的解析器。
- **`/api/health-check` 免鉴权**：从白名单移除（会输出财务体检结论）。
- **工具层设置键不一致**：补 `lang` 白名单，`morning_report_time` 归一为 `report_time` 并触发调度重排。

### 变更

- **长记忆改为纯本地**：移除 mem0 + chromadb（其 embedder 默认走 OpenAI，记忆内容会离开本机），改用本地 BM25 检索 `user_memory`，接口 `remember/recall` 不变。
- **删除未接线的规则引擎**：`rules.py` / `settings_rules.py` 全仓无调用，连同测试一并移除。
- **删除 11 个未使用 UI 组件与 7 个 Radix 依赖**。
- **可观测性改为零依赖**：移除 OpenTelemetry/Phoenix 依赖，改用标准库记录 LLM/工具耗时，`/api/metrics` 输出平均值/峰值/次数。
- **响应式**：侧栏与数据面板支持拖拽调宽（持久化、双击复位）；手机端新增底部导航；设置页在窄屏按三组折叠；数据面板在 xl 断点才挤占主区，消除 768–1279 的半遮挡；面板补齐焦点陷阱与焦点归还。
- **首屏体积**：Dashboard/部门面板/收件箱面板改为懒加载，主包 581KB → 453KB。

### 跨平台

- `scripts/dev.sh`、`scripts/lint.sh`、`scripts/e2e-backend.sh`、`deploy/one-click.sh` 自动探测 `Scripts/python.exe` 与 `bin/python`，Python 命令按 `python3 → python → py` 回退。
- `start.bat` 支持 `--prod`，自动建 venv 与装依赖；`.gitattributes` 固定 `.bat` 为 CRLF、`.sh` 为 LF。

## [1.4.0] - 2026-10-07（安全加固 + 前端渲染修复 + 测试覆盖提升 + 订阅/撤回/预算）

> 定位：安全漏洞全面修复；空白页根因治理；CI 真正跑测试；订阅到期巡检+撤回面板+预算/订阅卡片落地。

### 安全修复

- **P0 `/mcp` 鉴权绕过**：`mount_to_app` 新增 `_McpAuthGuard`（`BaseHTTPMiddleware`），对 `/mcp` 路径强制校验 `API_TOKEN`，关闭"挂载 ASGI 子应用绕过主中间件链"的缺口
- **P0 MCP 工具命名隔离**：外部 MCP 工具统一加 `mcp__` 前缀，防止与内置财务工具命名冲突及 prompt injection 误调用
- **P0 SQL LIKE 通配符注入**（`db.search_runs`）：转义 `%` / `_` / `\`，加 `ESCAPE '\'` 子句，杜绝用户输入被当通配符引发全表扫描
- **P1 备份口令 SSE 泄漏**：`tool_backup_now` 返回文本不再含明文口令，口令仅通过独立 `passphrase` 字段一次性传递
- **P1 登录限流分布式爆破**：`auth.login()` 注入 `FastAPI Request`；支持 `X-Forwarded-For` 取真实 IP；额外按用户名限流
- **P1 `ai_enabled` 工具层拒绝**：从 `SETTING_KEYS_ALLOWED` 移除 `ai_enabled`，防止模型静默关闭 AI 功能
- **P1 LLM 配置读取静默吞异常**：`llm._config()` DB 失败改为 `_log.warning`，区分"未接入"与"配置损坏"

### 前端修复

- **白屏根因**：`main.tsx` 中 `I18nProvider` 提升至 `ErrorBoundary` 外层，消除 `useI18n()` 在 Provider 外 throw 导致整树崩溃

### 工程化

- **CI/CD**：`.github/workflows/ci.yml` 后端段新增 `pytest` 运行（289 用例），前端段新增 `vitest run`（31 用例），CI 真正成为质量门禁
- **文档**：`CHANGELOG` 版本降序重排；中英文 README 版本号统一；`CONTRIBUTING.md` 端口号修正；删"AI生成"残留标记
- **Git**：移除 remote URL 中的 PAT 凭据明文

### 来自 1.3.x/1.2.x（保留条目）

- **订阅到期巡检**：`app.scheduler.subs_due_check` CronTrigger Asia/Shanghai，7 天窗口，月度幂等去重写入 `user_memory`
- **通用撤销面板**：`CommandPalette`（Cmd+K）撤销分组，`POST /api/undo/{record_id}` 撤回
- **Dashboard 预算卡**（`BudgetCard`）三档配色 + 红色超支徽标 + 分类进度行 + 无预算引导
- **订阅待缴卡**（`SubscriptionsCard`）前端纯 hook 计算 7 天内到期项；今日红/3 天黄
- **BudgetSection 实时预览**：分类输入即时渲染堆叠进度条，溢出红提示
- **新增端点**：`GET /api/subscriptions` + `GET /api/undoables` + `POST /api/undo/{record_id}` + `DELETE /api/memory?kind=`

## [1.3.0] - 2026-10-05（撤回 + 规则引擎 + 限流 + 前端单测）

> 定位：让应用在「可用」之上进一步「可逆、可自治、可回归」——写错能撤回、分类能自学习、接口能被保护、前端能被单测约束。

### 新增

- **SQLite 快照式 undo**：每笔写交易/持仓/负债/订阅落库前 `_record_snapshot`，撤回时 `_restore_from_snapshot` 还原。单条 + 批量撤回，零新依赖
- **JSON DSL 分类规则引擎**（`backend/app/rules.py`）：`desc_contains`/`desc_regex`/`category_is`/`amount_min`/`amount_max`，priority 数字大者优先，命中即短路
- **in-memory 滑动窗口 API 限流**：200 次/分钟/IP，429 + `Retry-After`；`/api/health` 与 `/api/metrics` 不计。绕过 slowapi 依赖
- **vitest + RTL + jsdom 前端单测**：覆盖 `i18n`/`store`/`AlertBanner` = 16 项

### 工程化

- 后端 282 用例全绿；前端 16 用例全绿
- Playwright 11 项 e2e（smoke×5 + chat×2 + data×4）在位
- `test_rate_limit.py` 4 项专项测限流行为

## [1.2.1] - 2026-10-05（去自研发化 + 前端安全/性能加固 + e2e 补齐）

> 定位：消除重复造轮子；收紧前端安全与性能基线；补齐端到端测试短板。

### 重构

- backend/mcp_client.py：自研 JSON-RPC + StreamableHTTP 帧重试移除，改用官方 `mcp.ClientSession` + `streamable_http_client`
- backend/db.py memory_retrieve：手写 Okapi BM25 换为 `rank_bm25.BM25L`；保留中文二元组分词

### 安全

- ReactMarkdown 输出过 `rehype-sanitize` 阻断脚本注入
- DataSection.importBackup：探测明文/加密备份，差异化提示

### 性能

- FinishedMessages 消息虚拟化窗口，长会话 DOM 节点下降约 10 倍
- build：esbuild `pure: [console.log/debug/info]` 剔除生产 console

### 依赖

- + `mcp>=1.0,<2` / `rank-bm25>=0.2,<1` (backend)
- + `rehype-sanitize` / `@playwright/test@1.63.0` (frontend)

### 测试

- Playwright 端到端 11 项冒烟 + 问答 + 功能页

## [1.2.0] - 2026-10-05（Agent 智能体升版）

> 定位：Agent 路线图 P0/P1/P2 全部落地，真实模型端到端联调与质量安全收尾。

### 新增

- **Agent P0**：长会话摘要压缩；模型点亮/可用性探测 + 自动降级
- **Agent P1**：记忆分层（会话/长期/经验）+ BM25 语义检索 + 经验库反思 + 主动遗忘
- **Agent P2**：多 Agent 编排（supervisor → 财务/通用/记忆）；审计日志；MCP 客户端；附件上传
- 真实 AI 端到端联调 + 压力测试（20 并发写 / 15 混合读写 / 极端输入全 422）

### 修复

- 空库 agent 降级误报「总市值 0」→ 改走「还没有录入」引导
- conftest 注入 `_no_real_llm`，全量 5–6 分钟降到 42.8s

### 工程化

- 后端 269 用例全绿（42.8s）、覆盖率 77%（核心模块 90%+）
- 前端生产构建通过

## [1.0.0] - 2026-10-01（正式版）

> 定位：**本地运行 × 云端能力**。对话界面中枢；数据 100% 本地存储；国产 AI 端点。

### 新增

- 5 页签投资者心智前端；17 个 agent 工具；财务目标/长期记忆/体检（5 维度）+ 晨报
- PBKDF2 + Fernet 加密备份（口令一次性展示）；行情三级降级；空库首启引导
- 双语 UI + 高度自定义（默认首页/涨跌色/语言/轮询…）

### 修复

- 理财咨询句不被记账劫持；6 位代码买入不错记支出；晨报递归修复
- 安全：agent 模式只暴露读类工具（7 个写工具从模型侧移除）；`tool_set_setting` 白名单

### 工程化

- 182 测试全绿；覆盖率 75%+
- 开源化：中英文 README + 真实截图 + SEO + docs 五件套

## [0.9.0] - 2026-09（投资者心智重构 + 工作流）

- 5 页签导航、指数条、持仓分组 + 集中度风控、行情自选/搜索/K 线、17 个 agent 工具

## [0.8.0] - 2026-09（目标 · 记忆 · 体检）

- 财务目标、长期记忆、5 维度体检；对话中"记住…"直存

## [0.7.0] - 2026-09（LangGraph 单路径）

- LangGraph 图成为唯一执行路径；React 19 / Vite 7 / Tailwind 4

## [0.6.0] - 2026-09（Agent 升级）

- 真实 agent 工具循环、K 线、备份/恢复、Docker、一键启动

## [0.5.0] - 2026-09

- 预算、记账、CSV 导入、PWA、会话搜索、AI 问答、品牌系统

## [Unreleased]

（暂无未发布变更）

