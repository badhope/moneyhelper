# 实施进度

> 单一进度真源。任何"还剩什么"的问题看这一页，不需要回头读规划文档。
> 计划本身见 [PLAN-DETAILED.md](PLAN-DETAILED.md)，本页只记状态。
>
> 更新规则：每完成一个里程碑就改这一页，并在末尾追加一行变更记录。

最后更新：2026-10-24 · 版本 3.0.0（后端 906 测试 / 前端 111 单测 + 21 e2e）

## 总览

| 里程碑 | 完成度 | 状态 |
|---|---:|---|
| M0 稳固+补课 | 100% | 完成 |
| M1 模块化+文档骨架 | 100% | 完成 |
| M2 协议补课 | 100% | MCP 挂载/鉴权已修；定时产出改由 resource 暴露（Tasks 上游未支持，已有等价方案） |
| M3 财务部门模式 | 100% | 主链可用；工单级工具白名单已生效并有测试 |
| M4 多端 | 66% | Win 单文件实测、CLI 双形态、发版自动化完成；Tauri 壳未做（现为 PyInstaller 单文件，非安装包） |
| M5 可视化+适老 | 85% | 图表/响应式/字号档位/高对比/语音输入完成；后端预聚合完成（SQL GROUP BY + 10s TTL 缓存）；TTS、反事实沙盒未做 |
| M6 生态+获客 | 45% | 审计底稿 HTML 导出完成（可打印 PDF）；50 题模型评测 + 确定性判分 + 排行榜完成；教程三连与 Registry 未做 |

## 2026-10-24 · 3.0.0 投资策略引擎（完成）

| 项 | 结果 |
|---|---|
| 确定性计算 | `calculations/portfolio_risk.py`（年化波动/夏普/索提诺/最大回撤/Calmar/Beta/Alpha/VaR + 基准对比）、`strategy.py`（目标配置漂移 + 整手可执行调仓清单）、`valuation.py`（750 日估值分位 + 定投统计 + FIRE 推演） |
| 组合风险 | 按当前持仓回溯净值曲线，与沪深300 / 上证 / 深成 / 创业板指对比；行情缺失时返回 available=false 与原因，不返回 500 |
| 再平衡 | 目标配置按标的设定容忍带，输出偏离度与买卖金额、约多少股；现金作为可配置目标项（CASH），不假设满仓 |
| 估值分位 | 当前价在近 750 个交易日区间中的位置，分低位/中枢/高位；只描述位置，不预测涨跌 |
| 定投 | 计划增删查 + 每期金额/累计投入/份额/成本线/当前盈亏/下一期扣款日 |
| FIRE | 目标本金（年支出/提取率）、完成度、储蓄率、按复利估算达成年限 |
| 后端接口 | `/api/strategy/*`：risk / allocation（GET+PUT）/ valuation / dca（GET+POST+DELETE）/ fire，共 5 条路径、8 个方法（`routes/strategy.py`） |
| Agent 工具 | 新增 5 个：`get_portfolio_risk` / `get_rebalance_plan` / `get_valuation` / `get_dca_plans` / `get_fire_plan`（财务工具总数 27） |
| MCP 工具 | 同上 5 个同步暴露到 MCP（工具总数 36） |
| 前端 | 新增「投资策略」页（`StrategyPage.tsx`）：风险指标条 + 净值曲线 + 再平衡清单 / 估值温度计双栏 + 定投表 + FIRE 进度，每块可独立降级 |
| 测试 | 新增 67 项策略测试（`test_strategy.py` 纯函数 + `test_strategy_api.py` 接口/租户隔离），后端总数 858 |

## 2026-10-23 · 2.9.3 安全与数据完整性收口

| 项 | 结果 |
|---|---|
| MCP 鉴权 | `/mcp`、`/mcp-sse` 与主 API 共用 `middleware.auth_gate`（口令 + 有账号必须 JWT），消除第二条信任边界 |
| 工具入参校验 | `validate_tool_args` 在 agent 循环 / action 节点 / confirm 三个执行边界统一接线，schema 不再只停留在声明 |
| 备份补表 | 附件、会话摘要、部门呈批件纳入导出与恢复 |
| CSV 列映射 | `generic_csv` 列名候选改为有序元组，跨进程解析结果一致 |

## 2026-10-23 · 2.9.2 收尾

| 项 | 结果 |
|---|---|
| 体检页 | 维度卡不再重复「建议」，只保留现状描述 |
| 启动开关 | `run.py` 支持 `XIAOMAN_NO_BROWSER=1`，端口改读 `PORT` |
| 清理 | 关闭开发/演示进程，移除临时截图与演示库 |

## 2026-10-23 · 2.9.1 对话内富回答块 + 上下文条

| 项 | 结果 |
|---|---|
| 富回答块 | 持仓概览 / 本月收支 / 需要注意三类，可展开走势、可跳转处理 |
| 去重 | 同一信息不再在风险块、SummaryBlock、Action 按钮重复三遍 |
| 上下文条 | 对话顶部显示数据范围与更新时间 |

## 2026-10-23 · 2.9.0 四类能力补齐 + Agent harness 加固

| 项 | 结果 |
|---|---|
| 系统提示词 | 设置页可编辑 `instructions.md`，留空回落默认，即时生效 |
| 插件（MCP） | 增删外部 MCP 服务器、测试连接、显示已发现工具；URL 凭据打码，写工具仍禁止 |
| 知识库 | 上传文档 → 切片 → BM25 检索 → 注入 system 消息，可逐个开关 |
| harness | 工具循环检测（连续 3 次同参中断）、输出上限 2048、非流式重试 2 次 + 60s 超时 |


## 2026-10-21 · 2.7.0 可安装性 + 多平台 + MCP 资源

| 项 | 结果 |
|---|---|
| pip 安装 | wheel 从 15KB（缺 app）修到 320KB/102 文件；实测任意目录导入 + CLI 可用 |
| 多平台产物 | desktop.yml 三平台矩阵 + 启动冒烟测试 |
| MCP 定时产出 | 两个 resource 替代上游未支持的 Tasks |
| 文档站 | 16 条导航全存在、0 坏链（静态校验） |

## 2026-10-21 · 2.6.0 测试整改 + 权限 + 适老 + 桌面端

| 项 | 结果 |
|---|---|
| 测试真实性 | 揪出 7 个 mock 掉被测逻辑的部门和 3 个渲染型假测试；新增 6 项真实 agent 循环测试 |
| 权限模型 | 方案 B：严格租户隔离 + 管理员只读条数概览；越权测试 4 项 |
| 适老化 | 字号三档 + 高对比；390px 下特大字号无溢出 |
| 语音 | 识别语言跟随界面语言；5 项 hook 测试 |
| 桌面端 | 144MB 单文件实测可跑（健康检查/前端/写入/MCP 全通） |

## 2026-10-20 · 2.5.0 家庭账本 + 升级实证

| 项 | 结果 |
|---|---|
| 家庭账本界面 | 成员/借贷/汇总三块接入设置页，e2e 覆盖全流程 |
| 升级演练 | upgrade_drill.py：旧库 12 表数据完整、复合主键共存、幂等、旧路径搬迁全通过 |
| 迁移安全 | 动结构前自动整库备份 `.pre-mt-<时间戳>`，内容为迁移前状态 |

## 2026-10-20 · 2.4.2 部署修复

| 项 | 结果 |
|---|---|
| Docker 数据丢失 | 库/备份/checkpoint 统一到 `XIAOMAN_DATA_DIR`（默认 `backend/data`），与卷一致；实测容器重建后数据保留 |
| 旧数据迁移 | 首次启动自动把旧 `backend/app/data` 搬到新位置（连带 -wal/-shm），升级不丢账本 |
| 镜像验证 | 实机构建 + 运行：健康检查 healthy、首页 200、MCP 200、非 root(1000) 运行 |

## 2026-10-20 · 2.4.0 多租户

| 项 | 结果 |
|---|---|
| 多租户 | 业务表加 user_id；四类业务主键表改复合主键；sessions/summary 唯一约束按租户拆分 |
| 迁移 | 启动时自动升级旧库（幂等）；历史数据归默认租户 |
| 护栏 | check_tenant_coverage 静态扫描 + 11 个隔离测试（数据层 7 / HTTP 4） |
| 健康分 | 统一为五维加权，补 grade 字段 |
| 部门工单 | tools_allowed 在执行阶段真正收窄工具面 |
| MCP 清仓 | 清仓按持仓市值计算并触发审批 |

## 2026-10-20 · 2.3.0 完成

| 项 | 结果 |
|---|---|
| 工具调用链路 | 修复 LiteLLM×mcp 版本冲突，模型可真实调用工具（已用真实模型验证） |
| MCP 部署 | `/mcp` 与 `/mcp/` 均可用；不再遮蔽前端；鉴权与来源校验对齐主站 |
| 设置持久化 | 新增保存栏，账本假设/晨报时间真正落库 |
| 数据一致性 | 备份补全 5 类数据；成员删除与撤回不再触发外键失败 |
| 安全 | 确认接口原子抢占；移除 health-check 免鉴权；根 `.env` 纳入忽略 |
| 长记忆 | 移除 mem0/chromadb，改本地 BM25，零外网外发 |
| 响应式 | 可拖拽侧栏/面板、手机底部导航、设置分组折叠、懒加载 |
| 界面范式 | 2.8.0：侧栏/主区/对话列按 ChatGPT 结构重排，Markdown 排版规范，移除重复 Agent 侧栏 |
| 界面审查 | 2.8.1：数据页改整页工作区（原 440px 抽屉挤坏表格）；修命令面板/K线/行情搜索/口语路由等 8 个真实缺陷 |
| 安全审计 | 2.8.3：认证绕过（Critical）、MCP 写工具绕过（High）、限流 IP 绕过、ECharts XSS 全部修复并加回归；README 截图重做 |
| 股票软件化 | 2.8.2：持仓/行情改双栏（明细 + 分析、列表 + 详情 + 迷你走势），记账改单行表格，体检重排；EXE 实打包并运行验证 |
| 跨平台 | 全部脚本自动适配 Windows/macOS/Linux |
| 代码清理 | 删规则引擎、11 个未用 UI、7 个依赖 |

## M0 稳固+补课 · 完成

| 项 | 产出 |
|---|---|
| M0.1 litellm 键名 | `llm.py` 用 `cfg.get("key")` |
| M0.2 多段记账原子性 | `db.add_transactions_batch` + 写锁串行化 |
| M0.3 402→400 | 校验失败返回 400 |
| M0.4 mem.remember 阻塞 | `asyncio.to_thread` |
| M0.5 tiktoken 声明 | requirements 显式声明 |
| M0.6 P2 批处理 | 限流首请求计数、metrics 移出白名单、审计归属 ContextVar |
| M0.7 逐文件通读 | `docs/module-map.md`（脚本生成，81 模块） |
| M0.8 harness 调研 | `docs/planning/11-agent-harness-专项调研.md` |
| M0.9 仓库瘦身 | 已删 doc-fetch-resources；CI 大文件检查 ≤1MB |

后续补修（审计发现计划里声称完成但有缺口）：
- litellm `retry_policy.retry_timeout` 是无效字段 → 改顶层 `timeout`
- DeepSeek `reasoning_content` 声称支持但未实现 → 按 `reasoning` 来源单列
- `.env.example` 缺 7 个在用变量 → 补齐

## M1 模块化+文档骨架 · 完成

| 项 | 产出 |
|---|---|
| M1.1 包骨架 | `xiaoman/{core,server,cli,mcp}` 分层门面 + CLI（add/ls/report/balance/ask/serve） |
| M1.2 db 拆分 | `app/db/` 14 个域模块 + `_schema.py`；`_core.py` 793→471 行 |
| M1.3 连接池 | 1 写连接 + 3 读连接（WAL 只读）；`get_write_lock()` 串行化写事务 |
| M1.4 main.py 拆薄 | 1827→222 行；`system.py` 再拆 9 个域模块；70 端点零差异 |
| M1.5 文档站 | mkdocs-material + strict 构建；`deploy/one-click.sh`；CI hygiene job |

## M2 协议补课 · 80%

| 项 | 状态 | 说明 |
|---|---|---|
| M2.1 工具 schema pydantic 化 | 完成 | `app/tool_schemas.py` 31 个模型为单一真源；修两侧参数漂移 |
| M2.2 MCP 全量 + Streamable HTTP | 完成 | 31 工具；`/mcp` 无斜杠可用；SSE 保留至 `/mcp-sse/sse` |
| M2.3 HITL 迁 Elicitation | 完成 | `app/approval.py`；MCP 写工具 fail-closed 审批 |
| M2.3 晨报迁 Tasks | **阻塞** | mcp SDK 只有 experimental；fastmcp 2.12 未透传。见下 |
| M2.4 AG-UI 映射层 | 完成 | `app/agui.py` + `POST /api/ask/agui`；流式翻译，双协议共存 |
| M2.5 官方 saver 替换 | 完成 | `AsyncSqliteSaver` + `WeakKeyDictionary` 按 loop 缓存；pending 表加 TTL 清理 |

M2.3 Tasks 阻塞细节：`mcp` 1.30 把 Tasks 放在 `mcp.server.experimental`
（`TaskSupport` / `ServerTaskContext`），标 experimental；`fastmcp` 2.12 源码里
搜不到 task 实现。要落地需绕开 fastmcp 直接用 lowlevel server，风险大于收益。
fastmcp 支持后只换装饰器，业务实现不动。

## M3 财务部门模式 · 100%

| 项 | 状态 |
|---|---|
| M3.1 工单 schema | 完成：`dept_models.py` pydantic 模型（dept/status 枚举、budget_tokens、metrics） |
| M3.2 LLM 派工 | 完成：`dept_dispatch.py`，schema 校验 + 工具白名单过滤 + 失败回落规则 |
| M3.3 部门 agent | 完成：`dept_agent.py`，独立 instructions + 工具白名单 + 独立 thread_id + token 预算；模型不可用退回确定性 |
| M3.4 秘书交叉对账 | 完成核心：按结构化 metrics 比对，冲突指明部门；呈批件含结论/冲突/发现 |
| M3.5 老板呈批 HITL | 完成：`dept_reports` 表 + 三个审批端点；approve/reject/inquire，审计落 provenance |
| M3.6 部门实况看板 | 完成：`DepartmentPanel` 四工位实时状态 + 秘书台 + 审批；e2e 覆盖全流程 |

这是计划里的"核心差异化"，也是当前最大缺口。

## M4 多端 · 66%

| 项 | 状态 |
|---|---|
| M4.1 CLI | 可用（argparse；add/ls/report/balance/ask/serve；本地+远程双形态）。缺：typer+rich、`xm dept run` |
| M4.2 Tauri 桌面 | 未做 |
| M4.3 发版自动化 | 完成：`scripts/release.sh` 从提交推导版本 + `release.yml` 自动建 Release |

## M5 可视化+适老 · 85%

| 项 | 状态 |
|---|---|
| M5.1 适老模式 | 完成：字号三档（normal/large/xlarge）+ 高对比，服务端持久化，390px 无溢出 |
| M5.2 ECharts 图表 | 完成：新增现金流瀑布/支出树图/订阅时间线/健康五维雷达；部门看板已有实时状态 |
| M5.3 后端预聚合 | 完成：`db.month_cashflow` SQL 聚合 + `/api/dashboard` 10s TTL 缓存（键含 DB 路径与租户），10 条写路径统一失效 |
| M5.4 语音闭环 | 部分：语音输入完成（Web Speech，识别语言跟随界面）；TTS 未做 |
| M5.5 反事实沙盒 | 未做（计划标注"若排期允许"） |

## M6 生态+获客 · 45%

| 项 | 状态 |
|---|---|
| M6.1 审计底稿 | 完成：`GET /api/audit-report` 输出可归档 HTML（浏览器打印为 PDF），before/after 只列变化字段，CSP 禁外部资源 |
| M6.2 挑战赛+错误台账 | 未做 |
| M6.3 模型招聘 eval | 完成：`eval_bank.py` 50 题 + `model_eval.py` 确定性判分 + `/api/eval/*` 四端点 + 设置页评测面板 |
| M6.4 家庭议会 | 未做（有成员管理，无多人审批链） |
| M6.5 教程三连+MCP Registry | 未做 |
| M6.6 可复核性标准草案 | 未做 |

## 下一步顺序

1. M4.2 Tauri 桌面壳（当前为 PyInstaller 单文件，无安装器与自动更新）
2. M5.4 TTS 语音播报与 M5.5 反事实沙盒
3. M6.5 教程三连 + MCP Registry 上架
4. 3.0.0 投资策略引擎收尾：估值分位与 FIRE 的空状态/边界用例补齐，截图与 README 同步
5. M4.2 Tauri 桌面壳（当前只有 PyInstaller 单文件，没有安装器与自动更新）

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-18 | 建立本页；M0/M1 完成，M2 达 80% |
| 2026-10-18 | M2.4 AG-UI 映射层完成，M2 达 90% |
| 2026-10-18 | M2.5 完成，M2 收官；pending 表补 TTL 清理 |
| 2026-10-19 | M3.1 工单模型 + 结构化对账 + 部门 SSE 流完成，M3 达 40% |
| 2026-10-19 | M3.2 LLM 派工 + M3.3 部门 agent 完成，M3 达 70% |
| 2026-10-19 | M3.5 呈批 HITL 完成，M3 达 85% |
| 2026-10-19 | M3.6 前端部门看板完成，M3 收官 |
| 2026-10-19 | 移动端适配：抽屉导航、动态视口、安全区、触摸目标、IME 防误发 |
| 2026-10-19 | M4.3 发版自动化 + 版本号统一到单一真源，M4 达 66% |
| 2026-10-19 | M5.2 新增 4 个图表（瀑布/树图/时间线/雷达），M5 达 55% |
| 2026-10-21 | 前端重构（2.8.0）：ChatGPT 式布局；修正本页 M4/M5 完成度与明细不一致（M4 66%、M5 60%） |
| 2026-10-21 | 界面审查（2.8.1）：财务页整页化 + 逐页截图修复 8 个真实缺陷；新增 ui-audit 截图脚本 |
| 2026-10-23 | 2.9.0–2.9.3 补记：Skill/Prompt/Plugin/知识库、富回答块、MCP 鉴权收口；测试基线 858 / 111 / 21 |
| 2026-10-23 | 3.0.0 投资策略引擎（进行中）：5 个新 agent 工具 + 5 个 MCP 工具、`/api/strategy/*`（5 条路径 / 8 个方法）、投资策略页 |
