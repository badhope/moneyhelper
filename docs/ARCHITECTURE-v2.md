# Moneyhelper v2.0 · Agent 技术栈全景图（2022-2026 盘点）

> 原则：**通用层全部站在开源巨人肩膀上，垂直层（财务/记账/行情）才是我们写的**。
> 凡是 2026 年还有人在自己手写的 harness / 记忆 / 观测 / UI，都是在重复造轮子。
> 本文盘点 2022 年以来整个 agent 生态成熟方案，点名 Moneyhelper 该接哪个、为什么、怎么接。

---

## 一、编排层（Orchestration）——我们选对了

| 框架 | 维护方 | 定位 | Moneyhelper 态度 |
|---|---|---|---|
| **LangGraph** | LangChain | 生产级状态图，checkpoint/interrupt 原生 | ✅ **已用，保持**。2026 年 #1，复杂有状态 agent 首选 |
| OpenAI Agents SDK | OpenAI | v0.18，provider-agnostic via LiteLLM，100+ 模型 | 备选。我们已用 LangGraph，不迁 |
| CrewAI | CrewAI Inc. | 角色制 multi-agent，最快原型 | 不迁。我们的编排复杂度用不上角色制 |
| AutoGen → Microsoft Agent Framework | Microsoft | 对话式 multi-agent | AutoGen 已维护模式，不碰 |
| Pydantic AI | Pydantic | 类型安全 agent | 不迁 |
| Mastra | Mastra.ai | TS 团队首选 | 不迁（我们 Python） |
| Google ADK | Google | 2026.4 发布，GCP 原生 | 不迁 |

**升级点**：`agent.py` 手写的 tool loop 换成 LangGraph prebuilt 的 `create_react_agent` + `ToolNode` + 原生 `interrupt()`。不再自己写 `MAX_TURNS=5`、不再自己维护 `_HITL_THREADS` 字典。

---

## 二、MCP 协议——必须升到 2026-07-28 新规

2026-07-28 MCP 规范是 launch 以来最大改版：

- **无状态协议核心**：server 不再持有 session，水平扩展像普通 HTTP 服务
- **Multi Round-Trip Requests**：一次发多个请求
- **Extensions 一等公民**：reverse-DNS 命名，独立版本，独立维护仓
- **MCP Apps**：server-rendered UI（MCP server 可以直接返回 UI 组件给客户端渲染）
- **Tasks extension**：长时任务（不用一直挂着连接）
- **Authorization 硬化**：OAuth/OIDC 对齐，`iss` validation、Dynamic Client Registration、credential binding

**Moneyhelper 行动**：
- 依赖升到 `mcp>=1.10`、`fastmcp>=3.0`（2026-07-28 SDK）
- 把 17 个财务工具用 fastmcp 暴露成标准 MCP server（已有，继续）
- **新增**：MCP Apps——让"持仓表 / 体检报告"这些 UI 直接由 MCP server 渲染，Claude Code/Cursor 打开就能看到结构化卡片，不只是文本
- **新增**：接 1-2 个公共 MCP server（比如行情、新闻）当外部工具，证明我们是 MCP client 不是只有 server

---

## 三、长记忆（Long-term Memory）——别再自己写

2026 年三强：

| 方案 | 哲学 | 适合 |
|---|---|---|
| **Mem0**（62k★） | 轻量提取+去重+更新，drop-in，Python/TS SDK | ✅ **Moneyhelper 选这个**。我们是 local-first，mem0 支持 SQLite/chroma 本地后端，零外部服务 |

> **2026-10 变更**：mem0 已移除。原因是它的 embedder 默认走 OpenAI，记忆内容会离开本机，与"数据 100% 本地"的承诺冲突；同时它引入了 chromadb 这一重依赖。现改为 `backend/app/mem.py` 直接用本地 BM25（rank-bm25）检索 `user_memory` 表，接口 `remember/recall` 保持不变。
| Letta（原 MemGPT） | 自编辑记忆块，完整 agent runtime | 不选。太重，我们不需要 agent 自己编辑内存 |
| Zep | temporal knowledge graph，企业级 bi-temporal | 不选。个人理财用不上 temporal graph |

**Moneyhelper 现在的手写轮子**：
- `memory` 表 + `reflections` 表 + BM25 自写检索 + 自写遗忘策略 = ~300 行
- `service.py` 里 `MEMORY_VERBS = ("记住", "记得")` 规则
- `agent.py` 里 `save_user_memory` / `get_user_memory` 工具

**换成**：
```python
# backend/app/mem.py
from mem0 import Memory
client = Memory.from_config({
    "vector_store": {"provider": "chroma", "config": {"path": "./data/mem0"}},
})
client.add(text, user_id="default")
results = client.search(query, user_id="default")
```
- 记忆抽取、去重、更新、rerank、metadata filtering 全是 mem0 的成熟 pipeline
- 旧 `memory` 表保留读兼容，新写入走 mem0，双写过渡期后删旧表

---

## 四、上下文工程（Context Engineering）

2026 年共识：

- **不要自己写摘要压缩**。LangGraph 自带 `SummarizationNode`；`langchain_core.messages.trim_messages` 按 token 窗口自动截
- **不要自己数轮次**。checkpointer + store 原生持久化，每轮消息自动落盘
- **reranker**：检索完加一道 Cohere/BGE rerank，mem0 自带
- **metadata filtering**：记忆按 user/时间/标签过滤

**Moneyhelper 行动**：
- 删 `service.py` 里 `SUMMARY_TRIGGER_TURNS=8` 自写压缩
- 换 `trim_messages(model=..., max_tokens=6000)`
- 多轮上下文回看从硬编码 4 轮改成按 token 窗口算

---

## 五、可观测性（Observability）——别再自己写 audit_log

2026 年自托管三强：

| 方案 | 协议 | Moneyhelper 选择 |
|---|---|---|
| **Langfuse** | MIT core，自托管最成熟，trace/prompt/eval/数据集一体 | ✅ **选它** |
| Arize Phoenix | OpenInference/OTel 原生，RAG 诊断强 | 备选 |
| OpenLLMetry | OTel drop-in | 备选 |

**Moneyhelper 现在的手写轮子**：
- `_audit_logger` middleware（main.py ~30 行）
- `audit_logs` 表 + 查询接口 + 审计 UI（~200 行）

**换成**：
```python
# backend/app/observability.py
from langfuse import Langfuse
lf = Langfuse()  # 读 LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY，没配就 no-op
# 每次 LLM 调用包一层 @lf.observe()
# 每次工具调用包一层
```
- trace 树、token 用量、成本、延迟、用户反馈打分、prompt 版本全有
- 审计前端整个删了，嵌 Langfuse iframe
- 自托管一条 docker compose：Postgres + ClickHouse + Redis + S3

---

## 六、前端 Agent UI——借鉴范式，不重写

2026 年前端 agent UI 三强：

| 方案 | 特点 | Moneyhelper 态度 |
|---|---|---|
| **CopilotKit** | Fortune 500 在用，AG-UI 协议发起者，Google/AWS/Microsoft/LangChain/Mastra 都采用 | 📚 **借鉴范式**：generative UI、tool call 卡、shared state、HITL 审批流 |
| **assistant-ui** | React 全家桶，多平台（RN/Web），ChatModelAdapter | 📚 借鉴：消息流 + tool call 折叠卡 |
| **Vercel AI SDK AI Elements** | 20+ 生产级组件，`useChat` 原生 | 📚 借鉴：streaming state machine |

**AG-UI 协议**（Agent-User Interaction）是 2026 年事实标准——agent 和 UI 之间的通信协议，Google/AWS/Microsoft/LangChain/Mastra 全采用。Moneyhelper 的 SSE 事件（start/step/agent_step/text/final/card）本质是自研的 AG-UI 子集。

**Moneyhelper 行动**：
- 不重写前端（迁移成本太大），但把 SSE 事件字段对齐 AG-UI 命名
- 借鉴 CopilotKit 的 **generative UI**：AI 返回的数据直接渲染成可交互组件（图表/表格/按钮），不是纯 markdown
- 借鉴 **shared state**：agent 能读前端当前选中的标的/账本月份
- 借鉴 **HITL 审批 UI**：买卖确认、备份确认做成标准化卡片，不是散落在各处的 modal

---

## 七、大厂编程工具的范式，我们直接偷

### OpenAI Codex（2026 现状）
- **目标模式（Goal Mode）**：用户定义成功标准，agent 朝目标持续工作，不是一问一答
- **并行 agent 管理**：多 agent 并行跑，用户看进度条
- **浏览器标注**：对前端改动直接截图反馈
- **Guided setup**：agent 反问用户配置

### ChatGPT Workspace Agents
- 团队共享 agent、权限管控、长期运行工作流
- 语音输出：agent 直接生成音频回复

### 阿里通义灵码
- Agentic 模式：自主用工程感知 + 网络检索工具
- Lingma IDE：行间会话、行间建议预测

### 千问 Go!（2026.10 刚发布）
- Personal Agent：执行现实任务（汽车保养、运动预约、购物比价）
- 基于阿里生态的购物/打车/快递/理财能力

**Moneyhelper 偷过来的范式**：
1. **目标模式**：加一个"盯盘模式"——用户说"茅台跌破 1400 提醒我"，agent 后台定时检查，触发就推消息。不是一问一答，是长时目标。
2. **并行 agent**：同时跑"体检 + 账本分析 + 持仓诊断"，三个流并行出结果
3. **guided setup**：首启 agent 反问"你有股票还是基金？大概月结余多少？"，自动建账本
4. **语音输出**：晨报生成后可选"念给我听"（TTS）

---

## 八、沙箱执行（未来如果加代码执行工具）

不要自己写 docker exec。2026 年方案：

- **E2B**：云沙箱，按秒计费，Python/Node 隔离
- **Daytona**（开源自托管）：开发环境即服务
- **Microsandbox**：Rust 写的轻量沙箱

Moneyhelper 现在没代码执行工具，**本轮不接**。未来如果加"让 agent 跑个财务模型计算"，直接用 E2B。

---

## 九、评估与 Prompt 工程

- **评估**：`promptfoo` 或 LangSmith Evals——CI 里跑回归测试集，A/B prompt，LLM-as-judge
- **Prompt 版本管理**：Langfuse Prompt Management——每个 prompt 有版本号、diff、回滚
- **现在的问题**：system prompt 散在 `agent.py` / `service.py` / `agent_graph.py` 三个文件里

**Moneyhelper 行动**：
- 把所有 system prompt 抽到 `prompts/` 目录，YAML 格式
- 接 Langfuse Prompt Management，上线前在 Langfuse playground 测
- CI 加 `promptfoo eval`

---

## 十、数据库与存储

| 层 | 现状 | v2.0 |
|---|---|---|
| 关系型 | SQLite（aiosqlite + WAL） | 保持。LibSQL 备选（远程同步） |
| 向量检索 | rank_bm25（关键词） | 加 chroma 本地模式（mem0 自带） |
| Checkpoint | AsyncSqliteSaver | 保持 |
| 加密备份 | PBKDF2+Fernet | 保持 |

---

## 十一、v2.0 落地顺序（commit 顺序）

1. **llm.py 切 LiteLLM**（风险最低，先做）
2. **接 Langfuse**（加 observability.py，配置了就 trace）
3. **接 mem0**（新记忆层，双写过渡）
4. **agent.py 切 create_react_agent**（开分支跑 269 测试）
5. **SSE 事件对齐 AG-UI**（重命名 + 加 shared state 字段）
6. **MCP Apps**（让财务工具返回结构化 UI 给 Claude Code）
7. **目标模式 / 盯盘模式**（借鉴 Codex Goal Mode）
8. **删自写审计页**（整个换 Langfuse iframe）

---

## 十二、明确不做的

- 不换 LangGraph（我们选对了）
- 不用 CrewAI/AutoGen（角色制对话式编排不适合财务垂直）
- 不自建向量库（chroma 本地模式够了）
- 不自写沙箱（未来要加用 E2B）
- 不重写前端换 CopilotKit/assistant-ui（借鉴范式即可，重写成本远大于收益）
