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
| 模块 | 行数 | 函数 | 类 | 职责 |
|---|---:|---:|---:|---|
| `app\__init__.py` | 23 | 0 | 0 | Moneyhelper · 个人理财多智能体后端。 |
| `app\agent.py` | 664 | 8 | 1 | Agent 编排层：LLM function calling 多轮工具循环（真正的垂直 agent）。 |
| `app\agent_config.py` | 266 | 12 | 0 | Agent 配置系统：角色 / skills / 工具开关。 |
| `app\agent_graph.py` | 1346 | 31 | 1 | LangGraph 多智能体编排图 —— 主执行路径（service.run_question 的图化替代）。 |
| `app\agents\bookkeeping\tools.py` | 17 | 0 | 0 | Bookkeeping agent 专属工具：记账、账本、预算、趋势。 |
| `app\agents\portfolio\tools.py` | 27 | 0 | 0 | Portfolio agent 专属工具：持仓、行情、K线、自选。 |
| `app\agents\supervisor\tools.py` | 31 | 0 | 0 | Supervisor agent 专属工具：风险、目标、健康检查、记忆、通用动作。 |
| `app\agui.py` | 241 | 6 | 1 | AG-UI 映射层（M2.4）：把内部 SSE 事件翻译成 AG-UI 协议事件流。 |
| `app\analysis.py` | 896 | 13 | 0 | 确定性分析内核：持仓、现金流、负债、应急金、风控规则。 |
| `app\approval.py` | 75 | 4 | 0 | 写操作审批：Web 对话与 MCP 共用的门槛判定与提示文案（M2.3）。 |
| `app\audit_report.py` | 160 | 4 | 0 | 审计底稿导出（M6.1）：把 provenance 链路渲染成一份可归档的 HTML 底稿。 |
| `app\auth.py` | 302 | 13 | 3 | 用户认证：JWT + bcrypt + 快依赖注入。 |
| `app\backup.py` | 81 | 4 | 0 | 本地加密备份：口令派生密钥 + Fernet 对称加密（cryptography）。 |
| `app\calculations\__init__.py` | 115 | 0 | 0 | 确定性金融计算引擎：所有数值计算纯代码执行，LLM 只做叙述解读。 |
| `app\calculations\backtest.py` | 294 | 6 | 0 | 策略回测引擎（股票投研 · 纯函数确定性计算）。 |
| `app\calculations\financial_statements.py` | 396 | 11 | 0 | 财报分析引擎（企业财务表深度分析 · 纯函数确定性计算）。 |
| `app\calculations\forecast.py` | 230 | 7 | 0 | 股票价格预测引擎（v4.1）：确定性统计预测，非 AI 猜测。 |
| `app\calculations\goals.py` | 181 | 3 | 1 | 目标进度确定性计算：每个状态的 on_track 纯代码判断，不涉及 LLM。 |
| `app\calculations\health.py` | 285 | 8 | 2 | 财务健康评分：五维 0-100 分确定性评估。 |
| `app\calculations\net_worth.py` | 109 | 2 | 1 | 净值追踪：持仓市值 + 现金 - 负债 = 净值。 |
| `app\calculations\paper.py` | 193 | 8 | 0 | 团队模拟盘引擎（v4.2）：事件溯源式纯函数计算，团队炒股核心。 |
| `app\calculations\portfolio_risk.py` | 294 | 13 | 1 | 组合风险与业绩归因：净值曲线、波动率、夏普、索提诺、最大回撤、Beta、VaR。 |
| `app\calculations\returns.py` | 242 | 7 | 0 | 收益率计算模块：XIRR（内部收益率）、TWR（时间加权收益率）、简单收益率。 |
| `app\calculations\strategy.py` | 255 | 5 | 2 | 再平衡与目标配置：漂移计算、带内容忍、可执行调仓清单。 |
| `app\calculations\technical.py` | 392 | 12 | 0 | 技术指标与信号引擎（股票投研 · 纯函数确定性计算）。 |
| `app\calculations\valuation.py` | 210 | 6 | 1 | 估值温度计与定投计划：位置分位、定投成本线、下一期日期。 |
| `app\compat_env.py` | 26 | 1 | 0 | 环境变量兼容层。 |
| `app\context.py` | 86 | 4 | 0 | 上下文工程 —— 用 tiktoken（OpenAI 官方）精确管理上下文窗口。 |
| `app\csvimport.py` | 175 | 8 | 0 | 账单 CSV 解析与列映射：解析常见平台导出格式（微信/支付宝/银行 CSV、Excel 另存的 UTF-8 CSV）。 |
| `app\db\__init__.py` | 349 | 0 | 0 | db 门面：保持 `from . import db` / `db.X` 旧用法 100% 兼容（M1 拆分，见 docs/PLAN-DETAILED.md M |
| `app\db\_core.py` | 1053 | 43 | 0 | 组合库 + 运行历史持久化（aiosqlite，单连接串行，不阻塞事件循环）。 |
| `app\db\_schema.py` | 438 | 0 | 0 | 数据库 schema 与种子数据（从 _core.py 拆出）。 |
| `app\db\audit.py` | 161 | 9 | 0 | 审计与附件域：审计日志 + 附件元数据。 |
| `app\db\backup.py` | 378 | 5 | 0 | 数据可移植域：全量导出/导入/月度趋势。 |
| `app\db\budgets.py` | 201 | 7 | 0 | 预算域：月度预算设置与用量统计。 |
| `app\db\debts.py` | 118 | 4 | 0 | 负债与订阅域。 |
| `app\db\dept_reports.py` | 144 | 7 | 0 | 部门呈批件存储（M3.5）：呈批件的落库与审批状态流转。 |
| `app\db\family.py` | 338 | 13 | 0 | 家庭域：成员/成员间借贷/家庭汇总。 |
| `app\db\goals.py` | 119 | 4 | 0 | 财务目标域 CRUD。 |
| `app\db\history.py` | 485 | 24 | 0 | 历史域：问答 runs/会话 sessions/会话摘要/待确认动作。 |
| `app\db\ledger.py` | 339 | 5 | 0 | 流水域：入账（单笔/批量原子）/改删/合并。 |
| `app\db\memory.py` | 260 | 14 | 0 | 记忆域：user_memory + reflections。 |
| `app\db\paper.py` | 162 | 11 | 0 | 团队模拟盘持久化（v4.2）：账户 / 交易 / 快照三表存取。 |
| `app\db\portfolio.py` | 267 | 8 | 0 | 持仓域：持仓 CRUD/合并 + 自选股。 |
| `app\db\statements.py` | 100 | 5 | 0 | 财报分析域持久化：标准化三表 JSON 的存取（v4.0）。 |
| `app\db\strategy.py` | 141 | 5 | 0 | 策略域：目标配置（再平衡）与定投计划的持久化。 |
| `app\db\tenant.py` | 52 | 6 | 1 | 租户上下文：当前请求属于哪个用户。 |
| `app\db\undo.py` | 250 | 6 | 0 | 撤销域：快照记录/恢复/应用（供 main 的 undo 端点与各写入口使用）。 |
| `app\db\users.py` | 124 | 10 | 0 | 用户体系：注册/查询/密码校验/登录时间。 |
| `app\department.py` | 419 | 12 | 0 | M3 财务部门模式：一句话 → 工单分解 → 四部门并行 → 秘书交叉对账 → 呈批件。 |
| `app\dept_agent.py` | 242 | 6 | 0 | 部门 agent（M3.3）：每个部门跑一轮独立的 agent 工具循环。 |
| `app\dept_dispatch.py` | 179 | 4 | 0 | LLM 派工（M3.2）：让模型把老板一句话拆成工单，而不是关键词匹配。 |
| `app\dept_models.py` | 133 | 5 | 3 | 财务部门模式的工单模型（M3.1）。 |
| `app\eval_bank.py` | 489 | 4 | 2 | 财务能力评测题库（M6.3）：50 道可判分的中文财务问答题。 |
| `app\evaluate.py` | 331 | 13 | 1 | 规则驱动的"首页评估层"：聚合预算/订阅/债务/目标/现金流信号，生成结构化行动项。 |
| `app\import_parsers\__init__.py` | 58 | 2 | 0 | 交易数据导入解析器包：按不同来源（通用 CSV / 微信 / 支付宝）提供统一解析接口。 |
| `app\import_parsers\alipay.py` | 202 | 5 | 1 | 支付宝账单 CSV 解析器。 |
| `app\import_parsers\base.py` | 185 | 12 | 4 | 导入解析器抽象基类与数据类。 |
| `app\import_parsers\generic_csv.py` | 222 | 8 | 1 | 通用 CSV 交易解析器：自动识别列名（中英文）、收支方向、编码。 |
| `app\import_parsers\wechat.py` | 182 | 5 | 1 | 微信支付账单 CSV 解析器。 |
| `app\knowledge.py` | 119 | 4 | 0 | 知识库：把上传的文档切成片段，按 BM25 检索后注入回答。 |
| `app\llm.py` | 626 | 19 | 3 | LiteLLM 统一模型接入——替掉自研 openai SDK 直连 + 手写路由 + 手动重试。 |
| `app\logging_utils.py` | 123 | 6 | 1 | 统一日志：RotatingFileHandler 落 backend/logs/moneyhelper.log，控制台输出。 |
| `app\main.py` | 323 | 9 | 0 | FastAPI 入口（薄装配层，M1.4 拆分后）：中间件注册 + 路由装配 + lifespan + 静态托管。 |
| `app\mcp_client.py` | 319 | 14 | 0 | MCP 客户端：基于官方 `mcp` SDK（StreamableHTTP 传输），不自研协议实现。 |
| `app\mcp_server.py` | 937 | 71 | 5 | MCP Server：把 Moneyhelper 所有工具暴露为标准 MCP 协议。 |
| `app\mem.py` | 81 | 4 | 0 | 长记忆层：完全本地，零外部服务、零网络外发。 |
| `app\middleware.py` | 482 | 21 | 0 | 全局中间件栈：异常兜底 / 限流 / 鉴权 / Host 防护 / 安全响应头 / 观测计数 / 审计。 |
| `app\model_eval.py` | 250 | 7 | 0 | 模型评测执行器（M6.3）：跑题库、确定性判分、出排行榜。 |
| `app\nlparse.py` | 323 | 8 | 0 | 自然语言记账解析：规则引擎优先（本地秒回），AI 兜底（歧义/未知分类）。 |
| `app\observability.py` | 79 | 5 | 0 | 可观测性：零依赖的耗时统计与慢请求记录。 |
| `app\provenance.py` | 370 | 14 | 1 | 审计追踪：每个金额变动操作的完整来龙去脉。 |
| `app\quotes.py` | 644 | 19 | 0 | 行情层：异步、可插拔、失败降级。 |
| `app\routes\__init__.py` | 47 | 0 | 0 | Route modules: each subpackage registers CRUD + query routes on the main app's r |
| `app\routes\agentcfg.py` | 162 | 8 | 0 | Agent 配置：角色 / skills / 工具开关；技能立即触发；AI 一键生成。 |
| `app\routes\attachment.py` | 88 | 4 | 0 | 附件：上传（multipart）/ 列出 / 删除。 |
| `app\routes\audit.py` | 28 | 2 | 0 | 审计日志（provenance 之外的 audit_log 表）：查询与清空。 |
| `app\routes\auth.py` | 93 | 7 | 0 | 用户认证路由：注册 / 登录 / 当前用户 / 用户数。 |
| `app\routes\budgets.py` | 234 | 6 | 0 | 预算路由：查询 + 更新月度预算设置。 |
| `app\routes\calculations.py` | 310 | 6 | 0 | 金融计算引擎路由：净值 / 收益率 / 健康评分 / 目标进度。 |
| `app\routes\debts_subs.py` | 93 | 4 | 0 | 负债与订阅路由：CRUD 操作（db 层 undo 快照由调用方经由 undo endpoint 触发）。 |
| `app\routes\evaluation.py` | 76 | 4 | 0 | 能力评测路由（M6.3）：题库 / 判分 / 排行榜。 |
| `app\routes\export.py` | 102 | 4 | 0 | 数据导出 / 备份恢复 / CSV 导出。 |
| `app\routes\family.py` | 15 | 1 | 0 | 家庭共享仪表板：整体汇总。 |
| `app\routes\goals.py` | 74 | 4 | 0 | 财务目标路由：目标 CRUD + 进度计算。 |
| `app\routes\import_routes.py` | 231 | 6 | 2 | 交易数据导入路由：CSV 上传 → 解析预览 → 确认入账。 |
| `app\routes\ledger.py` | 522 | 24 | 0 | 数据录入域路由：仪表盘 / 持仓 / 流水 / 一句话记账 / CSV 入账 / 撤回 / 体检。 |
| `app\routes\logs.py` | 36 | 2 | 0 | 运行日志查看与清空。 |
| `app\routes\market.py` | 133 | 10 | 0 | 行情 / 自选路由：K 线、趋势、报价、搜索、自选股管理。 |
| `app\routes\members.py` | 181 | 11 | 0 | 家庭成员管理路由：CRUD + 成员间借贷 + 成员汇总。 |
| `app\routes\memory.py` | 145 | 10 | 0 | 长期记忆与经验库（reflections）：列出 / 新增 / 删除 / 清空 / 遗忘 / AI 归纳。 |
| `app\routes\paper.py` | 153 | 6 | 0 | 团队模拟盘路由（v4.2）：开户 / 下单 / 估值 / 排行 / 净值曲线。 |
| `app\routes\provenance.py` | 99 | 3 | 0 | 审计追踪路由：查询操作来龙去脉 + 导出可归档的审计底稿。 |
| `app\routes\qa.py` | 635 | 33 | 1 | 问答域路由：SSE 流式问答（ask）+ HITL 确认（confirm）+ 历史/会话管理。 |
| `app\routes\reports.py` | 72 | 4 | 0 | 晨报 / 调度器状态 / 定时产出收件箱。 |
| `app\routes\research.py` | 167 | 5 | 0 | 股票投研路由（v4.0 财务工作台）：技术面研报 + 策略回测。 |
| `app\routes\settings.py` | 205 | 3 | 0 | 设置路由：GET/PUT /api/settings（原 main.py 设置域，M1.4 拆出）。 |
| `app\routes\statements.py` | 86 | 5 | 0 | 财报分析路由（v4.0 财务工作台）：三表分析 / 保存 / 列表 / 详情 / 删除。 |
| `app\routes\status.py` | 87 | 5 | 0 | 健康检查与指标：/api/health、/api/metrics、/api/bootstrap、模型目录。 |
| `app\routes\strategy.py` | 296 | 12 | 0 | 投资策略路由：风险指标 / 再平衡 / 估值温度计 / 定投计划 / FIRE。 |
| `app\routes\studio.py` | 621 | 32 | 0 | Studio 路由：资产 CRUD / 导入 / AI 生成 / 市场 / 权限 / 诊断 / 模板。 |
| `app\routes\system.py` | 111 | 0 | 0 | 系统域聚合入口（M1.4 收尾拆分后的门面）。 |
| `app\scheduler.py` | 429 | 18 | 0 | 定时任务（APScheduler）：每日晨报 + 订阅到期巡检。 |
| `app\service.py` | 831 | 20 | 0 | 问答服务：把用户的提问跑成一份可复核的财务回答。 |
| `app\studio\__init__.py` | 8 | 0 | 0 | Agent Studio：角色 / 技能 / 提示词 / 约束 / Hook / 内置工具 / 市场。 |
| `app\studio\commands.py` | 311 | 11 | 0 | 对话内配置：用自然语言在对话里增删改 Studio 资产。 |
| `app\studio\importer.py` | 286 | 10 | 1 | Studio 导入器：把官方格式的文件解析成 Studio 资产。 |
| `app\studio\installer.py` | 281 | 10 | 0 | Studio 安装器：从内置市场 / 远程 URL 安装资产，以及组装 MCP 配置。 |
| `app\studio\internal_tools.py` | 612 | 13 | 0 | 内置科研工具：确定性计算，不联网、不依赖第三方库。 |
| `app\studio\market.py` | 677 | 3 | 0 | 市场目录：内置可一键安装的开源 skill / agent / MCP 预设。 |
| `app\studio\store.py` | 551 | 35 | 0 | Studio 配置存储：提示词 / 约束 / Hook / 权限 / 内置科研工具 / 市场安装记录。 |
| `app\studio\watchdog.py` | 136 | 6 | 0 | 运行时看门狗：周期性检查服务健康、日志错误与配置完整性，产出可读告警。 |
| `app\tool_schemas.py` | 436 | 4 | 44 | 工具入参的 pydantic 模型 —— schema 的单一真源（M2.1）。 |
| `app\tools.py` | 1577 | 45 | 0 | Agent 工具层：把确定性分析内核暴露成 LLM 可调用的工具（function calling）。 |
| `app\vault.py` | 145 | 10 | 0 | 加密密钥管理系统：DB 内敏感字段加密存储。 |
| `app\version.py` | 23 | 0 | 0 | 版本号单一真源。 |

合计 116 个文件、31814 行。
