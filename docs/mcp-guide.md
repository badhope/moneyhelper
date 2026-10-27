# 把 Moneyhelper 接进你的 AI（MCP）

Moneyhelper 内置 MCP Server，Claude Code / Cursor / Cline / 任何 MCP 客户端都能直接读写你的账本。
数字全部来自本地确定性计算，模型只负责决定"调哪个工具"。

## 两种接入形态

| 形态 | 何时用 | 地址 |
|---|---|---|
| Streamable HTTP（推荐） | Moneyhelper 服务已在运行（Docker / `moneyhelper serve`） | `http://<host>:8788/mcp` |
| stdio | 由 IDE 直接拉起子进程，不需要常驻服务 | `python -m app.mcp_server stdio` |

> 传输层从 2.1.0 起默认 Streamable HTTP（MCP 规范 2025-03 起推荐）。
> 旧的 SSE 端点保留一个版本期，地址是 `http://<host>:8788/mcp-sse/sse`，
> 供已接入的老客户端继续使用。

## Claude Code

Streamable HTTP（服务已在运行）：

```bash
claude mcp add --transport http moneyhelper http://127.0.0.1:8788/mcp
```

stdio（无需常驻服务，由 Claude Code 拉起）：

```bash
claude mcp add moneyhelper -- python -m app.mcp_server stdio
```

设了 `API_TOKEN` 时需带口令：

```bash
claude mcp add --transport http moneyhelper \
  http://127.0.0.1:8788/mcp --header "Authorization: Bearer $API_TOKEN"
```

## Cursor / 其他客户端

在 MCP 配置文件里加（`~/.cursor/mcp.json` 或客户端对应位置）：

```json
{
  "mcpServers": {
    "moneyhelper": {
      "url": "http://127.0.0.1:8788/mcp",
      "headers": { "Authorization": "Bearer <你的 API_TOKEN>" }
    }
  }
}
```

`headers` 在未设 `API_TOKEN` 时可省略。

## 可用工具

工具清单的唯一真源是 `backend/app/tool_schemas.py`，共 31 个：

| 类别 | 工具 |
|---|---|
| 组合与账本 | `get_market_view`、`get_ledger_view`、`get_risk_flags`、`get_budget`、`get_trend`、`get_goals`、`get_health_check` |
| 行情 | `search_symbol`、`get_quote`、`get_kline`、`get_watchlist`、`add_to_watchlist`、`remove_from_watchlist` |
| 记账与持仓 | `record_transaction`、`record_position`、`sell_position`、`import_transactions` |
| 计算 | `get_net_worth`、`get_financial_health`、`get_returns`、`get_goal_progress` |
| 家庭与审计 | `get_family_summary`、`get_provenance` |
| 记忆 | `get_user_memory`、`save_user_memory`、`get_lessons` |
| 设置与产出 | `set_setting`、`trigger_morning_report`、`backup_now` |
| 通用 | `get_now`、`web_search` |

## 验证

对 AI 说：

1. 「帮我记一笔 打车 32 元」→ 应调用 `record_transaction`
2. 「这个月餐饮花了多少」→ 应调用 `get_ledger_view`
3. 「我有什么风险」→ 应调用 `get_risk_flags`

三步都拿到真实数字即接入成功。若工具列表为空，先检查 `/api/health` 是否可达、
以及是否设了 `API_TOKEN` 却没带口令。

## 安全说明

`/mcp` 与 `/mcp-sse` 都经过与 Moneyhelper 主应用同一套鉴权：设了 `API_TOKEN` 时
必须带 `Authorization: Bearer <token>` 或 `?token=`。**不要在没有口令的情况下
把端口暴露到公网**——MCP 暴露的是全量财务工具，包括卖出持仓与备份导出。

## 写操作审批（M2.3）

MCP 暴露的写工具（`record_transaction`、`record_position`、`sell_position`）
与大额阈值联动：超过阈值时通过 MCP 的 elicitation 请用户确认。

```
Web 对话：超阈值 → route=nl_pending，问「确认/取消」
MCP     ：超阈值 → ctx.elicit(...)，客户端弹表单，用户点接受/拒绝
```

两条路径共用 `backend/app/approval.py` 里的阈值与摘要文案，判据完全一致。
阈值取自 `app/agents/default_config.json` 的 `defaults.approval_threshold`
（默认 5000 元），可在设置页调整。

**fail-closed 行为**：客户端不支持 elicitation（老客户端、无 UI 的自动化场景）
时，大额写操作**直接被拒绝**，返回「已取消：用户未确认」。宁可失败也不静默写入。

小额写操作不受影响，不会多一次点击。

## 关于 Tasks（长任务）

MCP 规范里的 Tasks 适合承载"跑很久、要轮询进度"的操作（如晨报生成）。
当前实现情况：

- `mcp` SDK 1.30 把它放在 `mcp.server.experimental`（`TaskSupport` /
  `ServerTaskContext`），标记为 experimental
- `fastmcp` 2.12 完全没有透传这套能力（源码里搜不到 task 相关实现）

因此晨报目前仍是同步调用（`trigger_morning_report`，几秒内返回）。
把长任务暴露为 MCP Task 需要绕开 fastmcp 直接用 lowlevel server，
引入的风险大于当前收益。等 fastmcp 正式支持后再做，届时只在
`mcp_server.py` 里换装饰器，工具的业务实现不变。

## AG-UI 协议接入（M2.4）

Moneyhelper 的问答流同时支持两种事件协议：

| 端点 | 事件形态 | 消费者 |
|---|---|---|
| `POST /api/ask` | 内部契约（`start` / `step` / `agent_step` / `text` / `final`） | Moneyhelper 自己的前端 |
| `POST /api/ask/agui` | AG-UI 标准（`RUN_STARTED` / `TEXT_MESSAGE_*` / `TOOL_CALL_*` / `RUN_FINISHED`） | 任何 AG-UI 客户端（CopilotKit 等） |

两个端点共用同一套业务逻辑（同一个 runner），差别只在事件形态。映射是流式的，
逐事件翻译不缓冲整轮，实时体验一致。

```bash
curl -N -X POST http://127.0.0.1:8788/api/ask/agui \
  -H 'Content-Type: application/json' \
  -d '{"question":"这个月花了多少","thread_id":"demo"}'
```

映射规则（完整表见 `backend/app/agui.py` 的模块文档）：

- `text` → `TEXT_MESSAGE_START` + `CONTENT`* + `END`（自动配对）
- `thinking` → `REASONING_MESSAGE_*`，与正文互斥不交叉
- `agent_step` → `TOOL_CALL_START` + `ARGS` + `END`（每次调用独立 toolCallId）
- `step` → `STEP_STARTED` / `STEP_FINISHED`；只发 done 的会补发 start
- `final` → `RUN_FINISHED`，业务字段（flags / actions / pending_token）保留在 `result`
- `card` / `plan` → `CUSTOM`（AG-UI 无对应类型，原样透传不丢信息）

## 部门呈批（M3.5）

部门模式跑完会产出一份呈批件，并**落库**（老板离开页面再回来仍能批）。

| 端点 | 用途 |
|---|---|
| `POST /api/department/run` | 跑一轮，返回呈批件与事件（自动落库） |
| `POST /api/department/stream` | 同上，边跑边推 SSE（实况看板） |
| `GET /api/department/reports` | 列出呈批件（`?status=pending` 只看待批） |
| `GET /api/department/reports/{id}` | 查看单份呈批件 |
| `POST /api/department/reports/{id}/decide` | 审批 |

审批动作三种：

| decision | 语义 | 要求 |
|---|---|---|
| `approve` | 批准，结论被采纳 | 无 |
| `reject` | 驳回 | **必须附理由**（写进审计与记录） |
| `inquire` | 追问 | **必须附追问内容**，会重跑一轮并产生**新**呈批件 |

`inquire` 不覆盖原记录：原呈批件标记为 `inquired` 保留为历史，新呈批件是
`pending`。审批链完整可查。

状态机：`pending → approved / rejected / inquired`。同一份呈批件只能被审批一次
（条件 UPDATE 保证），重复提交返回 409。每次决策都写 provenance
（`dept_report_approve` / `_reject` / `_inquire`），老板的决策与数字产出在同一条审计链上。
