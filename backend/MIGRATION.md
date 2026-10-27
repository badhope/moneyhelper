# Moneyhelper · 反重复造轮子迁移路线图

> 原则：**凡是业界有成熟开源方案的，一律直接用，不在自家仓库里手写第二遍**。
> 垂直领域（记账/持仓/行情）才是我们的壁垒；agent harness、上下文工程、长记忆、观测这些通用层，全部站在巨人肩膀上。

---

## 一、已经在用的成熟库（保持，别再自研）

| 层 | 方案 | 状态 |
|---|---|---|
| 编排 | LangGraph 1.x（StateGraph + checkpointer + interrupt） | ✅ 已用 |
| LLM 统一接入 | LiteLLM（DeepSeek/豆包/通义/Claude/OpenAI 一家一个 SDK） | ✅ 依赖已加，`llm.py` 切换中 |
| MCP Server/Client | 官方 `mcp` + `fastmcp` | ✅ 已用 |
| 行情缓存 | `cachetools` TTL | ✅ 已用 |
| 检索 | `rank_bm25` | ✅ 已用（分词仍自写，见 P1） |
| 定时任务 | `APScheduler` | ✅ 已用 |
| 搜索 | `duckduckgo_search` | ✅ 已用 |
| 中文数字 | `cn2an` | ✅ 已用 |

## 二、还在手写、必须换掉的（按优先级）

### P0 · 本周换

#### 1. `agent.py` 手写 function-calling 多轮循环（456 行）
- **现状**：自己写 `MAX_TURNS=5` 循环、tool 白名单、结果截断、错误重试。
- **换成**：`langgraph.prebuilt.create_react_agent` + `ToolNode`。
  - 工具循环、最大轮次、错误恢复、中间步骤事件全是 prebuilt 给的；
  - 我们只需要把 `tools.py` 里的 17 个工具包成 `@tool`，然后 `create_react_agent(model, tools)` 一行搞定。
  - HITL（买卖确认）用 LangGraph 原生 `interrupt()`，不要再自己写 `_HITL_THREADS` 字典。
- **收益**：`agent.py` 从 456 行缩到 ~80 行；`agent_graph.py` 里手写的 supervisor/条件路由能直接用 `create_supervisor` prebuilt 代替。

#### 2. `llm.py` 手写 OpenAI SDK 直连（455 行）
- **现状**：自己封装 chat completion、streaming、JSON mode、国产端点预设、故障转移。
- **换成**：LiteLLM 的 `litellm.acompletion(model=..., messages=..., stream=True)`。
  - 国产端点预设 LiteLLM 全有（`deepseek/deepseek-chat`、`doubao/...`、`qwen/...`）；
  - 故障转移/重试/成本统计 LiteLLM 自带；
  - 我们只留一层薄封装：读 `.env` 里的 `LLM_*`，翻译成 LiteLLM model string。
- **收益**：`llm.py` 从 455 行缩到 ~60 行；新增模型端点不用改代码。

### P1 · 下个迭代换

#### 3. 长记忆（`memory` 表 + `reflections` + BM25 自写检索，约 300 行）
- **现状**：自己存长期记忆、自己写反思生成、自己 BM25 检索、自己决定遗忘。
- **换成**：[mem0](https://github.com/mem0ai/mem0)（local-first，SQLite 后端，零外部服务）。
  - mem0 自带：记忆抽取、去重、更新、向量/BM25 混合检索、按用户隔离；
  - 我们只需要 `mem0.add(user_id, text)` / `mem0.search(user_id, query)` 两个调用；
  - 不想引向量库就开 `vectordb='chromadb'` 本地模式，或者继续用 BM25 后端。
- **备选**：[Letta](https://github.com/letta-ai/letta)（原 MemGPT），适合要"自我编辑记忆"的 agent，但比 mem0 重。
- **收益**：`memory_retrieve`、`reflections` 相关代码全删，记忆质量由 mem0 的成熟 pipeline 保证。

#### 4. 上下文压缩（`SUMMARY_TRIGGER_TURNS=8` 手写摘要）
- **现状**：自己数轮次、自己 prompt 摘要、自己落库。
- **换成**：
  - LangGraph 自带的 `SummarizationNode`（`langgraph.prebuilt`）；
  - 或 `langchain_core.messages.trim_messages`，按 token 窗口自动截断旧消息；
  - 长会话摘要落库用现有 checkpointer 就够，不用自己写表。
- **收益**：`service.py` 里那段 summary 逻辑（约 50 行）删掉。

#### 5. 观测/审计（`_audit_logger` middleware + `audit_logs` 表，自写 200 行）
- **现状**：自己记每次工具调用、自己写查询接口、自己做审计页面。
- **换成**：[Langfuse](https://github.com/langfuse/langfuse) 自托管（Docker 一条命令）。
  - Langfuse 自带：trace 树、token 用量、成本、每次工具调用延迟、用户反馈打分、prompt 版本管理；
  - 我们只需要 `langfuse_context.update_current_observation(...)` 几个 hook；
  - 审计页面前端可以整个删了，直接嵌 Langfuse iframe。
- **备选**：LangSmith（如果接受 SaaS）。
- **收益**：审计 middleware、audit_logs 表、审计 UI 全删；观测能力反而是现在的 10 倍。

### P2 · 按需换

#### 6. 评估（`evaluate.py` 331 行自写）
- **换成**：[promptfoo](https://github.com/promptfoo/promptfoo) 或 LangSmith Evaluations。
  - 回归测试集、A/B prompt、准确率打分全是现成的；
  - CI 里跑 `npx promptfoo eval` 就行。

#### 7. 未来如果加"代码执行/沙箱"工具
- **不要自己写 docker exec**。直接用：
  - [E2B](https://e2b.dev)（云沙箱，按秒计费）；
  - [Daytona](https://github.com/daytonaio/daytona)（开源自托管）；
  - 本地就用 `jupyter-kernel` 隔离，别裸跑 `subprocess`。

#### 8. 提示词版本管理
- 现在 system prompt 散在 `agent.py` / `service.py` / `agent_graph.py` 三个文件里。
- **换成**：Langfuse Prompt Management 或 `promptfoo` 的 prompt registry——每个 prompt 有版本号、有 diff、能回滚。

---

## 三、不要动的部分（这是我们的壁垒）

- `analysis.py`（819 行确定性财务计算内核）——**这是核心壁垒，绝不交给 LLM**。
- `quotes.py` 行情三级降级——垂直领域积累。
- `nlparse.py` 一句话记账规则——中文记账领域规则，不是通用 harness。
- `backup.py` 加密备份、`vault.py` 密钥管理——安全相关，自己写可控。
- 17 个财务工具的业务逻辑——垂直工具，不是通用轮子。

---

## 四、本轮（v1.5.0）已落地的改造

1. **前端三区布局**：删 tab 思维，左会话栏 / 中对话 / 右产物面板（ContextPanel）。
2. **配色中性化**：米黄橙绿 → ChatGPT 式 `#f7f7f8` 中性灰 + 单一墨绿主色。
3. **SSE 加 card 事件**：`finalize` 节点推送结构化数据卡，前端渲染成对话内嵌小卡 + "在右侧面板打开"按钮。
4. **后端语法/import 验证通过**；`agent_graph.py` 的 card 事件向后兼容（前端不认识就忽略）。

## 五、下一步 commit 顺序建议

1. 先切 `llm.py` → LiteLLM（风险最低，不碰图结构）；
2. 再切 `agent.py` → `create_react_agent`（先在一个分支跑 269 测试）；
3. 接 mem0 替换手写记忆；
4. 自托管 Langfuse，删自写审计；
5. 对话内嵌数据卡从"占位"升级成真·4 宫格 + mini 环形图。
