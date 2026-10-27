# 模块清单与职责（M0.7 产出）

> 每个后端模块的职责、体量与结构。本表由脚本从模块 docstring 与 AST 统计生成，
> 不是手写维护的清单 —— 它保证"文件里写的职责"和"实际代码结构"对得上。
>
> 用途：
> - 新人定位：要改什么先查这里，避免在 80 个文件里盲搜
> - 拆分判断：行数 + 函数数 + 类数一起看，单文件超 500 行或函数超 20 个是拆分信号
> - 审查基线：改完一个模块后回来看本表，职责描述是否仍然准确（不准确就该更新 docstring）
>
> 重新生成（在 backend/ 下）：
>
> ```bash
> python .monkeycode/scripts/gen_module_table.py
> ```

## 分层速览

| 层 | 目录 | 判据 |
|---|---|---|
| 确定性内核 | `app/analysis.py`、`app/calculations/`、`app/quotes.py`、`app/nlparse.py`、`app/evaluate.py` | 不依赖 HTTP，换 CLI/MCP 调用仍成立 |
| 持久化 | `app/db/` | 只管读写与事务，不做业务判断 |
| 编排 | `app/service.py`、`app/agent_graph.py`、`app/agent.py`、`app/department.py` | 决定"用哪条路径得到答案" |
| LLM 接入 | `app/llm.py`、`app/context.py`、`app/mem.py` | 模型调用与上下文管理 |
| HTTP 壳 | `app/main.py`、`app/middleware.py`、`app/routes/` | 收请求、调内核、出响应 |
| 横切能力 | `app/provenance.py`、`app/vault.py`、`app/backup.py`、`app/logging_utils.py`、`app/observability.py` | 审计 / 加密 / 备份 / 日志 / 追踪 |
| 协议 | `app/mcp_server.py`、`app/mcp_client.py` | 对外暴露与调用 MCP |

## 全部模块

| 模块 | 行数 | 函数 | 类 | 职责 |
|---|---:|---:|---:|---|
| `__init__.py` | 23 | 0 | 0 | Moneyhelper · 个人理财多智能体后端。 |
| `agent.py` | 461 | 6 | 1 | Agent 编排层：LLM function calling 多轮工具循环（真正的垂直 agent）。 |
| `agent_config.py` | 221 | 11 | 0 | Agent 配置系统：角色 / skills / 工具开关。 |
| `agent_graph.py` | 1285 | 30 | 1 | LangGraph 多智能体编排图 —— 主执行路径（service.run_question 的图化替代）。 |
| `agents/bookkeeping/tools.py` | 17 | 0 | 0 | Bookkeeping agent 专属工具：记账、账本、预算、趋势。 |
| `agents/portfolio/tools.py` | 27 | 0 | 0 | Portfolio agent 专属工具：持仓、行情、K线、自选。 |
| `agents/supervisor/tools.py` | 31 | 0 | 0 | Supervisor agent 专属工具：风险、目标、健康检查、记忆、通用动作。 |
| `agui.py` | 241 | 6 | 1 | AG-UI 映射层（M2.4）：把内部 SSE 事件翻译成 AG-UI 协议事件流。 |
| `analysis.py` | 819 | 12 | 0 | 确定性分析内核：持仓、现金流、负债、应急金、风控规则。 |
| `approval.py` | 75 | 4 | 0 | 写操作审批：Web 对话与 MCP 共用的门槛判定与提示文案（M2.3）。 |
| `auth.py` | 275 | 11 | 3 | 用户认证：JWT + bcrypt + 快依赖注入。 |
| `backup.py` | 81 | 4 | 0 | 本地加密备份：口令派生密钥 + Fernet 对称加密（cryptography）。 |
| `calculations/__init__.py` | 34 | 0 | 0 | 确定性金融计算引擎：所有数值计算纯代码执行，LLM 只做叙述解读。 |
| `calculations/goals.py` | 181 | 3 | 1 | 目标进度确定性计算：每个状态的 on_track 纯代码判断，不涉及 LLM。 |
| `calculations/health.py` | 255 | 7 | 2 | 财务健康评分：五维 0-100 分确定性评估。 |
| `calculations/net_worth.py` | 109 | 2 | 1 | 净值追踪：持仓市值 + 现金 - 负债 = 净值。 |
| `calculations/returns.py` | 242 | 7 | 0 | 收益率计算模块：XIRR（内部收益率）、TWR（时间加权收益率）、简单收益率。 |
| `context.py` | 86 | 4 | 0 | 上下文工程 —— 用 tiktoken（OpenAI 官方）精确管理上下文窗口。 |
| `csvimport.py` | 175 | 8 | 0 | 账单 CSV 解析与列映射：解析常见平台导出格式（微信/支付宝/银行 CSV、Excel 另存的 UTF-8 CSV）。 |
| `db/__init__.py` | 300 | 0 | 0 | db 门面：保持 `from . import db` / `db.X` 旧用法 100% 兼容（M1 拆分，见 docs/PLAN-DETAILED.md M |
| `db/_core.py` | 490 | 30 | 0 | 组合库 + 运行历史持久化（aiosqlite，单连接串行，不阻塞事件循环）。 |
| `db/_schema.py` | 359 | 0 | 0 | 数据库 schema 与种子数据（从 _core.py 拆出）。 |
| `db/audit.py` | 116 | 7 | 0 | 审计与附件域：审计日志 + 附件元数据。 |
| `db/backup.py` | 237 | 5 | 0 | 数据可移植域：全量导出/导入/月度趋势。 |
| `db/budgets.py` | 130 | 5 | 0 | 预算域：月度预算设置与用量统计。 |
| `db/debts.py` | 96 | 4 | 0 | 负债与订阅域。 |
| `db/dept_reports.py` | 136 | 7 | 0 | 部门呈批件存储（M3.5）：呈批件的落库与审批状态流转。 |
| `db/family.py` | 296 | 13 | 0 | 家庭域：成员/成员间借贷/家庭汇总。 |
| `db/goals.py` | 103 | 4 | 0 | 财务目标域 CRUD。 |
| `db/history.py` | 410 | 23 | 0 | 历史域：问答 runs/会话 sessions/会话摘要/待确认动作。 |
| `db/ledger.py` | 319 | 5 | 0 | 流水域：入账（单笔/批量原子）/改删/合并。 |
| `db/memory.py` | 242 | 14 | 0 | 记忆域：user_memory + reflections。 |
| `db/portfolio.py` | 241 | 8 | 0 | 持仓域：持仓 CRUD/合并 + 自选股。 |
| `db/undo.py` | 227 | 6 | 0 | 撤销域：快照记录/恢复/应用（供 main 的 undo 端点与各写入口使用）。 |
| `db/users.py` | 78 | 6 | 0 | 用户体系：注册/查询/密码校验/登录时间。 |
| `department.py` | 419 | 12 | 0 | M3 财务部门模式：一句话 → 工单分解 → 四部门并行 → 秘书交叉对账 → 呈批件。 |
| `dept_agent.py` | 235 | 6 | 0 | 部门 agent（M3.3）：每个部门跑一轮独立的 agent 工具循环。 |
| `dept_dispatch.py` | 179 | 4 | 0 | LLM 派工（M3.2）：让模型把老板一句话拆成工单，而不是关键词匹配。 |
| `dept_models.py` | 133 | 5 | 3 | 财务部门模式的工单模型（M3.1）。 |
| `evaluate.py` | 331 | 13 | 1 | 规则驱动的"首页评估层"：聚合预算/订阅/债务/目标/现金流信号，生成结构化行动项。 |
| `import_parsers/__init__.py` | 58 | 2 | 0 | 交易数据导入解析器包：按不同来源（通用 CSV / 微信 / 支付宝）提供统一解析接口。 |
| `import_parsers/alipay.py` | 202 | 5 | 1 | 支付宝账单 CSV 解析器。 |
| `import_parsers/base.py` | 185 | 12 | 4 | 导入解析器抽象基类与数据类。 |
| `import_parsers/generic_csv.py` | 220 | 8 | 1 | 通用 CSV 交易解析器：自动识别列名（中英文）、收支方向、编码。 |
| `import_parsers/wechat.py` | 182 | 5 | 1 | 微信支付账单 CSV 解析器。 |
| `llm.py` | 602 | 19 | 3 | LiteLLM 统一模型接入——替掉自研 openai SDK 直连 + 手写路由 + 手动重试。 |
| `logging_utils.py` | 118 | 6 | 1 | 统一日志：RotatingFileHandler 落 backend/logs/moneyhelper.log，控制台输出。 |
| `main.py` | 278 | 8 | 0 | FastAPI 入口（薄装配层，M1.4 拆分后）：中间件注册 + 路由装配 + lifespan + 静态托管。 |
| `mcp_client.py` | 161 | 8 | 0 | MCP 客户端：基于官方 `mcp` SDK（StreamableHTTP 传输），不自研协议实现。 |
| `mcp_server.py` | 760 | 53 | 4 | MCP Server：把 Moneyhelper 所有工具暴露为标准 MCP 协议。 |
| `mem.py` | 149 | 8 | 0 | 长记忆层 —— 接 mem0（2026 年 local-first 首选）。 |
| `middleware.py` | 330 | 14 | 0 | 全局中间件栈：异常兜底 / 限流 / 鉴权 / Host 防护 / 安全响应头 / 观测计数 / 审计。 |
| `nlparse.py` | 323 | 8 | 0 | 自然语言记账解析：规则引擎优先（本地秒回），AI 兜底（歧义/未知分类）。 |
| `observability.py` | 120 | 8 | 1 | 可观测性层 —— 接 Arize Phoenix（开源，单容器本地跑，不需要外部账号）。 |
| `provenance.py` | 330 | 14 | 1 | 审计追踪：每个金额变动操作的完整来龙去脉。 |
| `quotes.py` | 599 | 18 | 0 | 行情层：异步、可插拔、失败降级。 |
| `react_agent.py` | 188 | 4 | 0 | LangGraph 官方 create_react_agent 替换手写 tool loop。 |
| `routes/__init__.py` | 35 | 0 | 0 | Route modules: each subpackage registers CRUD + query routes on the main app's r |
| `routes/agentcfg.py` | 90 | 4 | 0 | Agent 配置：角色 / skills / 工具开关；技能立即触发；AI 一键生成。 |
| `routes/attachment.py` | 58 | 3 | 0 | 附件：上传（multipart）/ 列出 / 删除。 |
| `routes/audit.py` | 28 | 2 | 0 | 审计日志（provenance 之外的 audit_log 表）：查询与清空。 |
| `routes/auth.py` | 38 | 4 | 0 | 用户认证路由：注册 / 登录 / 当前用户 / 用户数。 |
| `routes/budgets.py` | 229 | 6 | 0 | 预算路由：查询 + 更新月度预算设置。 |
| `routes/calculations.py` | 320 | 6 | 0 | 金融计算引擎路由：净值 / 收益率 / 健康评分 / 目标进度。 |
| `routes/debts_subs.py` | 89 | 4 | 0 | 负债与订阅路由：CRUD 操作（db 层 undo 快照由调用方经由 undo endpoint 触发）。 |
| `routes/export.py` | 101 | 4 | 0 | 数据导出 / 备份恢复 / CSV 导出。 |
| `routes/family.py` | 15 | 1 | 0 | 家庭共享仪表板：整体汇总。 |
| `routes/goals.py` | 71 | 4 | 0 | 财务目标路由：目标 CRUD + 进度计算。 |
| `routes/import_routes.py` | 231 | 6 | 2 | 交易数据导入路由：CSV 上传 → 解析预览 → 确认入账。 |
| `routes/ledger.py` | 503 | 24 | 0 | 数据录入域路由：仪表盘 / 持仓 / 流水 / 一句话记账 / CSV 入账 / 撤回 / 体检。 |
| `routes/logs.py` | 36 | 2 | 0 | 运行日志查看与清空。 |
| `routes/market.py` | 117 | 8 | 0 | 行情 / 自选路由：K 线、趋势、报价、搜索、自选股管理。 |
| `routes/members.py` | 181 | 11 | 0 | 家庭成员管理路由：CRUD + 成员间借贷 + 成员汇总。 |
| `routes/memory.py` | 145 | 10 | 0 | 长期记忆与经验库（reflections）：列出 / 新增 / 删除 / 清空 / 遗忘 / AI 归纳。 |
| `routes/provenance.py` | 48 | 2 | 0 | 审计追踪路由：查询操作来龙去脉。 |
| `routes/qa.py` | 603 | 32 | 1 | 问答域路由：SSE 流式问答（ask）+ HITL 确认（confirm）+ 历史/会话管理。 |
| `routes/reports.py` | 72 | 4 | 0 | 晨报 / 调度器状态 / 定时产出收件箱。 |
| `routes/settings.py` | 191 | 3 | 0 | 设置路由：GET/PUT /api/settings（原 main.py 设置域，M1.4 拆出）。 |
| `routes/status.py` | 75 | 5 | 0 | 健康检查与指标：/api/health、/api/metrics、/api/bootstrap、模型目录。 |
| `routes/system.py` | 111 | 0 | 0 | 系统域聚合入口（M1.4 收尾拆分后的门面）。 |
| `rules.py` | 169 | 4 | 0 | 轻量分类规则引擎：CSV 导入 / 对话记账的分类增强。 |
| `scheduler.py` | 419 | 18 | 0 | 定时任务（APScheduler）：每日晨报 + 订阅到期巡检。 |
| `service.py` | 821 | 20 | 0 | 问答服务：把用户的提问跑成一份可复核的财务回答。 |
| `settings_rules.py` | 41 | 3 | 0 | tx_rules 的 settings 表读写：把规则 JSON 序列化后存到 settings 表的 "tx_rules" key。 |
| `tool_schemas.py` | 310 | 3 | 32 | 工具入参的 pydantic 模型 —— schema 的单一真源（M2.1）。 |
| `tools.py` | 1094 | 33 | 0 | Agent 工具层：把确定性分析内核暴露成 LLM 可调用的工具（function calling）。 |
| `vault.py` | 145 | 10 | 0 | 加密密钥管理系统：DB 内敏感字段加密存储。 |

合计 87 个文件、20906 行。
