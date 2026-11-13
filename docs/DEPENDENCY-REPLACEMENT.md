# 依赖替换清单（少写代码，多用成熟库）

> 原则：**买原语，不买系统；先替换机械代码，不重写业务内核。**
> 状态截至 2026-11-11。每一项都标注证据、收益、风险和当前状态。
> 本清单是“可替换项”审计结果，不代表所有代码已逐行审完。

## 1. 本轮已替换（有回归）

| # | 原实现 | 替换为 | 证据 | 结果 |
|---|---|---|---|---|
| 1 | 仪表盘手写 TTL 字典 | `cachetools.TTLCache` | `backend/app/analysis.py:30` | 自动过期、容量上限，删手写时间戳比较 |
| 2 | MCP 发现/失败手写时间戳缓存 | `cachetools.TTLCache` ×2 | `backend/app/mcp_client.py:48` | 失败退避自动过期，配置切换仍按指纹失效 |
| 3 | 账单编码仅 UTF-8/GBK 手工回退 | `charset-normalizer` | `backend/app/import_parsers/base.py:158` | UTF-16/BIG5 等可识别；UTF-8/GBK 行为保持 |
| 4 | `passlib[bcrypt]` 死依赖 | 直接 `bcrypt` | `backend/app/db/users.py:17`、`pyproject.toml` | 去掉停更包；旧 `$2b$` 哈希兼容 |
| 5 | 税额 `round()`（银行家舍入） | `Decimal + ROUND_HALF_UP` | `backend/app/calculations/tax.py:28` | 符合税务四舍五入到分；90 项财税测试通过 |
| 6 | 手写牛顿+二分 XIRR（约 100 行） | `pyxirr` | `backend/app/calculations/returns.py:18` | 删数值迭代；无解/非有限值统一抛 `ValueError` |
| 7 | 手写 tablist/aria-selected | `@radix-ui/react-tabs` | `frontend/src/components/ui/grouped-nav.tsx:73` | 方向键/Home/End、aria-controls、单一 Tab 停靠点 |
| 8 | 手写日期/月格式化（缺年份） | `Intl.DateTimeFormat` | `frontend/src/lib/format.ts:56` | 修复跨年只显示月日；去掉手写月份名 |
| 9 | 4 处裸 `navigator.clipboard` | `copy-to-clipboard` | `frontend/src/lib/clipboard.ts` | 非安全上下文（局域网 HTTP）可回退复制 |
| 10 | MCP stdio 可通过 API 写入 | 默认拒绝 + 显式开关 | `backend/app/routes/agentcfg.py:121`、`backend/app/db/backup.py:398` | 关闭任意命令执行入口；备份恢复同样默认丢弃 |

回归结果：后端 1600+ 通过、前端 192 通过、前端生产构建通过（详见本轮记录）。新增安全回归：`backend/tests/test_mcp_stdio_guard.py`、`backend/tests/test_instance_admin.py`、`backend/tests/test_mcp_readonly_policy.py`、`backend/tests/test_backup_completeness.py`、`backend/tests/test_data_integrity_fixes.py`。

## 1.1 同批安全/数据可信修复（非替换）

| 问题 | 处理 |
|---|---|
| MCP stdio 可通过 API 写入并启动任意命令 | 默认拒绝，`MONEYHELPER_ALLOW_STDIO_MCP=1` 才放行；备份恢复同样默认丢弃 |
| 停用账号旧 JWT 仍可访问无 `require_user` 路由 | 统一鉴权闸校验账号存在/未停用；`user_count` 统计全部账号，堵住“全停用=无账号模式” |
| MCP/审计/备份恢复缺实例管理员边界 | 统一 `require_instance_admin`；单机无账号模式仍可用 |
| 审计 actor 是客户端 IP、403 不记 AUTH、清空无记录 | actor 改稳定身份；401/403 都记；清空本身也留审计 |
| 审计记录可被静默篡改/删除 | 租户内 SHA-256 哈希链 + `GET /api/audit/verify`；物理清空默认拒绝 |
| 外部 MCP 工具按名字判只读 | 只信 `readOnlyHint`，未声明默认不暴露；自有 MCP Server 已标注 |
| 备份缺模拟盘/净值快照/家庭议案/定投/财报 | 导出与恢复补齐，做往返测试 |
| 流水更新可写入 Inf | 更新与批量入口统一拒绝 0/NaN/±Inf |
| 税务接口显式 0 被默认值覆盖 | `_f()` 只对缺省/None/空串回落默认值 |

## 2. 下一批（P1，收益明确、改动可控）

| # | 原实现 | 替换为 | 证据 | 约可删 | 风险/注意 |
|---|---|---|---|---|---|
| 11 | 两套手写进程内滑动窗口限流 | `limits`（或 slowapi） | `backend/app/auth.py:172`、`backend/app/middleware.py:45` | 85 行 | 测试直接 import 私有桶，需改 HTTP 行为测试；多 worker 仍需 Redis 才有共享语义 |
| 12 | 22 处 httpx 客户端无重试 | `httpx.AsyncHTTPTransport(retries=2)` + 可选 `tenacity` | `backend/app/quotes.py:88` 等 | 新增少、删重复构造 | 只对幂等 GET；行情接口限频，重试上限 2–3 次 |
| 13 | 手写 Prometheus 文本 | `prometheus-client` | `backend/app/middleware.py:387`、`observability.py:27` | 86 行 | 保持现有指标名兼容；多进程需 multiprocess 模式 |
| 14 | 手拼 HTML 报告 | `Jinja2`（已在依赖树） | `backend/app/report.py:184`、`audit_report.py:46` | 472 行 | 运行时仍是单文件 HTML；模板需保持离线可看 |
| 15 | `LIKE` 搜索 | SQLite FTS5 | `backend/app/db/history.py:171` | 14 行查询 + schema | 中文需双字 tokenizer；迁移与触发器要同步 |
| 16 | 无 XLSX 导入 | `openpyxl` 或 `python-calamine` | `backend/app/import_parsers/` 无 xlsx | 新增能力 | 银行/券商 XLSX 常见；日期序列号与公式单元格要处理 |
| 17 | 手写表单状态/校验 | `react-hook-form` + `zod` | `EntryView.tsx:53` 等 5 个表单 | 400+ | 先补 RTL 表单测试；e2e 有位置选择器，DOM 变化会断 |
| 18 | 手写 i18n Context + 1804×2 字典 | `i18next` + `react-i18next` | `frontend/src/lib/i18n.tsx:14` | 80 行框架 + 迁移 | 量大机械；复数/命名空间收益明确，但测试要保留 key 契约 |
| 19 | 视图状态无 URL | `react-router-dom`（HashRouter） | `App.tsx:44` | 60 行状态机 | 后端无 SPA fallback；用 HashRouter 避免深链 404 |
| 20 | 手写移动抽屉/命令面板焦点 | Radix Dialog | `MobileDrawer.tsx:30`、`CommandPalette.tsx:100` | 70 行 | 单测断言内联 `overflow`/`aria-modal`，迁移需同步改断言 |
| 21 | 金额硬编码 `¥` | `Intl.NumberFormat` + 可选 `currency` | `frontend/src/lib/format.ts:15` | 23 行 | 15 条精确断言；先加参数保持 CNY 输出不变 |
| 22 | SSE 库重试被禁用后又手写一套 | 让 `fetch-event-source` 的 `onerror` 返回退避；或 `eventsource-parser` | `frontend/src/lib/api.ts:128` | 80–100 | 问答主链路；先补半帧/401/abort 测试 |
| 23 | 单表手写排序 | `@tanstack/react-table`（出现第二张表时） | `PositionsTable.tsx:38` | 34 行 | 当前只有一张表，收益有限；先删除未用的 `@tanstack/table-core` 或按触发条件引入 |

## 3. 企业化阶段（P2，需独立分支/迭代）

| 能力 | 结论 | 说明 |
|---|---|---|
| 复式总账 | 自研薄内核 | 科目、期间、分录、过账、反冲、试算表；`transactions` 保留为现金簿 |
| 权限 | PyCasbin | `domain=tenant` 的 RBAC；先影子模式跑 2 周，再强制高风险写路由 |
| 审批 | python-statemachine + 自研审批域 | 单步→多级；申请人≠审批人；会签/委派/SLA 后续加 |
| ORM/迁移 | SQLAlchemy 2.0 + Alembic 增量 | 新域先 ORM，旧裸 SQL 冻结；Alembic baseline `stamp` |
| 数据库 | PostgreSQL 云 + SQLite 桌面 | 双 dialect CI；不一次重写全部 SQL |
| 总账互操作 | beancount 仅导出/测试 oracle | GPL-2.0，不进运行时/桌面包 |
| ERP | ERPNext/Odoo 仅连接器 | 不做内核、不 fork、不嵌入 |
| BPMN | SpiffWorkflow 可选 | 仅客户要求业务人员建模时引入 |
| 长流程 | Temporal 暂不引入 | 跨服务、万级日流程、持久定时器成为瓶颈再评估 |
| OCR | RapidOCR | 已有可选依赖，保持“二维码优先 + OCR 兜底 + 人工复核” |
| 发票模板 | invoice2data | 与现有二维码/OFD/正则组合 |
| 对账 | RapidFuzz + 自建银行适配器 | OFX 可用 ofxparse；中国银行需适配器 |
| 税薪 | 保留现有中国引擎 | 补规则版本表、工资批次、审批、代发与申报导出 |

## 4. 明确不建议替换

| 领域 | 现有实现 | 不替换理由 |
|---|---|---|
| JWT | PyJWT HS256 | 事实标准，换库无收益 |
| 密码哈希 | 直接 bcrypt | 已是成熟库；Argon2 迁移收益低 |
| TWR | `backend/app/calculations/returns.py:125` | 没有 drop-in 库；它吃估值点/交易事件，不吃收益率序列 |
| 回测引擎 | `backend/app/calculations/backtest.py` | A 股成本/整手/策略是垂直业务；`backtesting.py` 是 AGPL |
| 技术指标 | `technical.py:51` | 在未决定引入 pandas 前，148 行 + 输出对齐契约不值得换 |
| 风险指标 | `portfolio_risk.py:68` | “样本不足返回 None”是产品语义，pandas NaN 语义不同 |
| 日期/金额解析 | `import_parsers/base.py` 等 | 中文日期、会计负数、欧式小数是账单真实格式，通用库覆盖不全；应合并重复实现而非换库 |
| CSV | 标准库 `csv` | 标准库就是成熟实现 |
| PDF/OCR | pdfplumber/pypdf/opencv/rapidocr | 已经是库；未安装 extras 时按设计降级 |
| SQLite 数据访问 | `backend/app/db/` | 300+ 处裸 SQL，大爆炸 ORM 重写风险远大于收益；增量迁移 |
| RBAC（当前两角色） | `admin_only` | 只有 admin/user 时 Casbin 过度；企业版再上 |
| 状态机（连接器 3 态） | `connect/store.py` | 枚举过少；企业审批域才需要状态机库 |
| 审计/provenance | `middleware.py`、`db/audit.py` | Langfuse 需外部 collector，违背本地优先；保留并加 hash chain |
| 长期记忆 | rank-bm25 | mem0 需 embedding 出网，与隐私设计冲突 |
| 图表封装 | `lib/charts.ts` | 懒加载/按需注册/0 尺寸重放是定制点，通用 wrapper 不支持 |
| 代码高亮 | react-syntax-highlighter | 已按需注册、明暗主题、独立 chunk |
| 全局状态 | TanStack Query | 服务端态已归 Query；UI 态应由路由解决，不引入 store |
| 上传/虚拟滚动/PDF 预览 | 原生 input、窗口截断 | 当前体量小；预览是新增功能，不是替换 |

## 5. 替换节奏

1. **一次只换一类**：先机械代码（缓存/格式化/剪贴板），再基础设施（限流/重试/指标），最后领域内核（总账/审批/权限）。
2. **每项必须有回归**：替换前跑相关测试，替换后跑全量；没有测试的先补测试。
3. **高风险项独立分支**：Alembic 迁移、agent 循环、i18n、表单迁移不与其它替换同批。
4. **依赖必须显式声明**：传递依赖（tenacity/charset-normalizer/Jinja2）不能“碰巧可用”，采用即写入 `pyproject.toml` 与 `backend/requirements.txt`。
5. **每季度复核**：检查停更/归档/许可证变化（Oso、passlib、piecash 都是前车之鉴）。

## 6. 本轮未做但已确认的真实缺口

- 后端无 XLSX 解析；
- 收益率接口仍有“用普通流水代理投资现金流”的口径问题；
- 月结勾选只在 localStorage，不能多人共享/审计；
- 聊天流无 `aria-live`；
- 命令面板关闭后仍在 Tab 序列。

`backend/MIGRATION.md` 已标注为历史路线图，避免继续按过时的 mem0/Langfuse 建议改造。

这些应进入产品/技术待办，不要用“已有相关代码”代替验收。
