# 配置说明（环境变量 + 应用设置项）

Moneyhelper 分两层配置：**环境变量**（启动前，`backend/.env`，复制自 `.env.example`）与**应用设置**（运行时，设置页，落库到 SQLite `settings` 表，立即生效）。

## 1. 环境变量（backend/.env）

全部可选；不配置也能完整运行（确定性模板兜底，无 AI 也能记账/分析/出晨报）。

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容端点。国产推荐：DeepSeek / 豆包（火山方舟）/ 通义千问 / 云知声（详见下方「AI 端点速查」） |
| `LLM_API_KEY` | 空 | 模型密钥；也可不配，启动后在设置页填 |
| `LLM_MODEL` | `deepseek-chat` | 模型名 |
| `LLM_TIMEOUT` | `60` | 单次模型调用超时（秒，夹在 5-600）。自托管小模型跑在 CPU 上时，7k token 的 prefill 就要几分钟，写死 60s 会把"正在算"误判成"模型不可用"、整轮降级成模板 |
| `LLM_TOOL_LIMIT` | `0` | 单轮暴露给模型的工具数上限（0 = 不限制）。2B 级模型在 40 个工具的 schema 下会放弃选择、直接凭上下文编答案；压到个位数（如 `6`）能稳定命中正确工具 |
| `LLM_EXTRA_BODY` | 空 | 透传给端点的额外请求体（JSON）。不同推理框架的模板开关不同，例如 MiniCPM5 需要 `{"chat_template_kwargs":{"enable_thinking":false}}` 才会直接输出 tool_call，而不是把 token 全花在 `<think>` 里 |
| `API_TOKEN` | 空 | 访问口令。空 = 不鉴权（仅限本机/内网）；设置后 `/api/*` 需 Bearer/`?token=`，前端弹口令框 |
| `ALLOWED_HOSTS` | 空 | 未设口令时额外放行的 Host（逗号分隔）。默认只放行本机 |
| `MCP_ENABLE` | `1` | 是否挂载 MCP Server。`/mcp` 提供 Streamable HTTP，`/mcp-sse/sse` 兼容旧客户端；鉴权与来源校验与主应用一致 |
| `MONEYHELPER_DATA_DIR` | `backend/data` | 运行期数据目录（数据库 / 备份 / LangGraph checkpoint）。Docker 镜像内置为 `/app/backend/data`，与数据卷一致 |
| `MONEYHELPER_DB_PATH` | 空 | 数据库文件路径，优先级高于 `MONEYHELPER_DATA_DIR`；空值忽略 |
| `MONEYHELPER_DISABLE_RATE_LIMIT` | 空 | `1` 关闭限流（默认 200 次/分钟/IP）；仅测试与本地调试使用 |
| `MONEYHELPER_SLOW_MS` | `5000` | 慢操作告警阈值（毫秒），超过即写 WARNING 日志 |
| `MONEYHELPER_TRUST_PROXY` | 空 | `1` = 部署在可信反代后，登录限流按 `X-Forwarded-For` 取真实客户端 IP。直连暴露端口时不要开（该头可伪造） |

> 兼容性：旧前缀 `XIAOMAN_*` 仍可读（`MONEYHELPER_*` 优先），便于从旧版本平滑升级；新部署请直接用新前缀。
| `JWT_SECRET` | 随机生成 | 多用户登录令牌签名密钥。**不设置时每次启动随机生成，重启后所有登录失效**；生产务必显式配置 |
| `JWT_EXPIRE_HOURS` | `168` | 登录令牌有效期（小时） |
| `CORS_ALLOW_ALL` | 空 | 调试用：仅放行前端开发源（`1` 开启）。生产同域托管无需改动 |

> 提示：AI 配置以**应用内设置页为准**（`ai_base_url` / `ai_api_key` / `ai_model` / `ai_enabled`），落库后优先级高于环境变量，重启不丢。

## 2. 应用设置项（设置页，落库）

| 设置项 | 键 | 取值 | 说明 |
|---|---|---|---|
| 默认首页 | `default_tab` | `chat`（默认）/ `overview` / `holdings` / `market` / `ledger` | 启动/刷新后落地的页签 |
| 涨跌颜色 | `color_scheme` | `cn`（红涨绿跌，默认）/ `us`（绿涨红跌） | 全局涨跌色即时切换 |
| 语言 | `lang` | `zh` / `en` | 界面双语（含空态、能力清单、设置项） |
| 数字格式 | `compact_numbers` | `on` / `off` | 大额显示为 1.3万 / 5000 |
| 快捷建议 | `show_suggestions` | `on` / `off` | 问答输入框下方快捷指令 chips |
| 自动刷新 | `auto_refresh` / `auto_refresh_seconds` | `on`/`off` / 秒数（默认 300） | 总览行情自动轮询 |
| 展示导出 | `show_export` | `on` / `off` | 是否显示导出入口 |
| 过程展开 | `expand_process` | `on` / `off` | 问答中 agent 工具调用过程默认展开/折叠 |
| 语音输入 | `voice_input` | `on` / `off` | 语音输入开关 |
| 月收入 | `monthly_income` | 数字 | 预算/储蓄率/应急金计算基准 |
| 应急金目标 | `emergency_target_months` | 数字（默认 6） | 覆盖月数目标 |
| 必要支出类别 | `essential_categories` | 逗号分隔（默认 居住,餐饮,交通） | 预算/超支分析口径 |
| 本月预算 | `budgets`（API） | 数组 `[{category,amount}]`，`__total` 为总预算 | 设置页 → 预算；总览实时进度 |
| 财务目标 | `goals`（API） | `{name, target, note}` | 设置页 → 账本规则 → 目标 |
| 晨报时间 | `report_time` | `HH:MM`（默认 08:00） | 每日晨报生成时间 |
| 行情来源 | `quote_source_mode` | `auto`（默认）/ `eastmoney` / `sina` / `snapshot` | 三级降级；`snapshot` 只用组合库快照价 |
| 访问口令 | — | 见 `API_TOKEN` | 设置页 → 访问口令（Bearer 鉴权 + 401 弹窗） |
| 长期记忆 | `memory`（API） | 文本条目 | 设置页 → 长期记忆；问答优先参考 |

## 3. AI 端点速查（国产优先）

| 服务商 | Base URL | 模型示例 | 备注 |
|---|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` | 默认预设 |
| 豆包（火山方舟） | `https://ark.cn-beijing.volces.com/api/v3` | 推理接入点 ID | 需先开通接入点 |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | |
| 云知声 | `https://maas-api.unisound.com/v1` | `u2-flash` | 实测流式回答 + 工具循环正常 |

模型能力要求：OpenAI 兼容 `/chat/completions`，支持 **流式（SSE）** 与 **function calling**（工具循环场景必需）。不满足时 app 自动降级确定性路径，服务不中断。

## 4. 变更校验

- 设置写入经 `PUT /api/settings` 校验：数值区间、on/off 枚举、`HH:MM` 格式、行情源枚举、URL 前缀等，非法项逐条报错、合法项逐条生效。
- 备份口令不落库、不进入导出包明文；导出明文有强提示。

## 多租户说明

一个实例支持多个独立账本：登录用户各自的数据互不可见。

- 未登录请求（或只配了 `API_TOKEN`）落在**默认租户 0**，即本机单用户模式。
- 登录后（JWT）读写自动限定在 `sub` 对应的租户，业务表按 `user_id` 过滤。
- 备份导出/恢复只涉及当前租户；恢复不会清空其他用户的数据。
- 旧库升级：首次启动自动补 `user_id` 列并把历史数据归到租户 0，幂等可重跑。
- 数据层有静态护栏（`backend/scripts/check_tenant_coverage.py`），新增 SQL 漏加租户过滤会直接报错。

### 升级与备份

- 多租户迁移（2.4.0 起）在**动表结构前**自动整库备份：`wealth.db.pre-mt-<时间戳>`，
  与数据库同目录。确认升级正常后可手动删除。
- 想先演练升级，不碰真实库：`cd backend && python scripts/upgrade_drill.py`
  （用旧版 schema 造库 → 迁移 → 校验 12 张表数据完整 / 幂等 / 旧路径搬迁）。

## 设置页分区（2.9.0）

| 分组 | 分区 | 说明 |
|---|---|---|
| 基础设置 | 偏好 / 账本规则 / 预算 / 家庭账本 | 本机行为与账本口径 |
| AI 与自动化 | AI 回答 / Agent 与技能 / 插件（MCP）/ 系统提示词 / 知识库 / 每日晨报 / 长期记忆 | 模型、技能、外部工具、人格、文档检索 |
| 数据与安全 | 数据与状态 / 访问口令 / 日志 / 审计日志 / 溯源链 | 备份、鉴权、可复核性 |

### 插件（MCP）

外部 MCP 工具服务器，与 Claude Code / Cursor 同一协议。配置存于 `backend/data/mcp.json`，
也可在设置页增删与测试连接。URL 中的凭据在回显时会打码为 `***`。

写操作保护：`mcp__` 前缀的写工具（记账、买卖、改设置等）一律被拒绝，
模型只能通过外部工具读数据。

### 知识库

上传 `.txt / .md / .csv / .json / .log / .pdf` 后标记「加入知识库」，问答时会用本地 BM25
检索最相关的片段注入 system 消息。PDF 只抽取文本层，扫描件会明确提示未抽取；
图片没有可检索正文，不能入库。检索完全在本机完成，不上传任何内容到外部服务。
开关：设置 → 知识库（也可通过 `/api/settings` 的 `knowledge_enabled` 控制）。

与「长期记忆」的区别：记忆是你主动记住的短句（偏好、家庭背景）；
知识库是长文档（保单、合同、产品说明），必须切片检索。

### 连接中心的账号接入

连接中心把外部平台分成五种控制级别，级别由接入方式决定，不是界面上的装饰：

| 级别 | 含义 | 典型平台 |
|---|---|---|
| 只读 | 后台直连公开接口，只拉行情/净值 | 东方财富、天天基金 |
| 导入 | 用户导出 CSV/PDF，收件箱扫描入账 | 微信支付、银行流水 |
| 配对回传 | 用户在官方页面登录，一次性配对码回传当前页 | 支付宝、云闪付 |
| 手动导出 | 只给官方入口，用户自己导出 | 招商/工商/建设/中国银行 |
| 逐笔确认 | 模型只能起草交易指令，实盘出交接单 | 券商 |

边界：不保存平台密码、不模拟登录、不绕过风控、不代转账。支付宝个人账号没有面向第三方的完整控制 API，系统只做官方账单导出与配对回传；任何声称“完整接管支付宝”的实现都依赖爬虫或模拟登录，不进入本产品。

### 本地模型（离线）

设置 → AI 回答 →「本地模型入口」内置四个 OpenAI 兼容端点，填入后无需云端 Key：

| 推理端 | 默认 Base URL | 说明 |
|---|---|---|
| Ollama | `http://127.0.0.1:11434/v1` | 安装后 `ollama pull` 模型 |
| LM Studio | `http://127.0.0.1:1234/v1` | 图形界面下载，启动 Local Server |
| llama.cpp | `http://127.0.0.1:8090/v1` | `llama-server --jinja -fa on` |
| vLLM | `http://127.0.0.1:8000/v1` | 有独显时吞吐更高 |

精选 6 个 2B–4B 小模型（MiniCPM5 2B / Qwen3 4B Instruct / Gemma 3 4B / Llama 3.2 3B / Phi-4 mini 3.8B / Qwen2.5 3B Instruct）各自给出官方下载页与四端模型名。应用不代下大文件；点「检测本机」会真实请求 `/models`，把返回的模型 id 列出来，并标注当前模型是「已安装」还是「未安装」。未检测、服务不可达时只显示未连接或错误，不显示假的安装状态。Ollama 模型卡可直接复制 `ollama pull …` 命令。

### 演示账本

演示数据独立存放在保留租户，不写入真实账本。设置 → 数据与状态可一键切换：
进入演示前重建演示区，失败则留在真实数据并报错；切回真实只清前端标记。
演示数据不参与真实账本的备份/导出。

### 系统提示词

设置 → 系统提示词可覆盖 `backend/app/agents/supervisor/instructions.md` 的内置默认值。
留空 = 使用文件默认；最多 4000 字；保存后立即生效，无需重启。
只影响财务问答分支，通用闲聊与部门看板不受影响。
