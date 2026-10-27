# Moneyhelper — 系统架构文档

## 一句话定位

开源、本地优先的个人理财 AI Agent：用 LangGraph 多 Agent 编排驱动记账 / 持仓 / 风控 / 洞察，以 MCP 协议对外暴露完整工具集，同时提供独立的 React Web 前端和 Claude/Codex 等 IDE 直连能力。

## 技术栈分层

```
┌─────────────────────────────────────────────────────┐
│ 交互层                                                │
│  ├─ React 19 + Tailwind 4 (Web 前端, PWA)             │
│  ├─ MCP Client (Claude Code / Cursor / Windsurf)      │
│  └─ REST API (OpenAI-compatible, 供第三方集成)          │
├─────────────────────────────────────────────────────┤
│ 协议层                                                │
│  ├─ SSE (流式问答)                                    │
│  ├─ MCP (FastMCP, 工具暴露)                           │
│  ├─ JWT + API Token (鉴权)                            │
│  └─ CORS / Host Guard / Rate Limiter (安全中间件)      │
├─────────────────────────────────────────────────────┤
│ Agent 编排层 (LangGraph)                               │
│  ├─ StateGraph 多节点 (supervisor → executor → evaluator)│
│  ├─ HITL (Human-in-the-Loop) interrupts              │
│  ├─ Command resume (审批流)                            │
│  └─ tools.py (Agent 工具注册表, 60+ tools)             │
├─────────────────────────────────────────────────────┤
│ 确定性分析层 (纯函数)                                   │
│  ├─ calculations/ (净值/收益率/健康评分/目标进度)        │
│  ├─ analysis.py (持仓分析/风控规则/集中度)               │
│  ├─ evaluate.py (首页评估, rule → action items)         │
│  └─ import_parsers/ (CSV/微信/支付宝解析)               │
├─────────────────────────────────────────────────────┤
│ 数据层                                                 │
│  ├─ SQLite + aiosqlite (WAL mode, FK on)               │
│  ├─ PBKDF2 + Fernet (vault 加密)                       │
│  ├─ Provenance log (审计追踪)                           │
│  └─ LiteLLM (多模型统一访问 + fallback chain)            │
├─────────────────────────────────────────────────────┤
│ 定时任务层                                              │
│  ├─ APScheduler / 自研 scheduler.py                     │
│  ├─ 晨报生成                                           │
│  └─ 订阅到期提醒                                       │
└─────────────────────────────────────────────────────┘
```

## 数据流

### 提问 / 对话
```
User → React ChatView (useChatView hook)
     → POST /api/ask (SSE stream)
     → LangGraph StateGraph
       → supervisor node (意图识别 + 规划)
       → executor node (工具调用: tools.py → db.py / calculations / quotes)
       → evaluator node (确定性规则 → 行动项)
     → SSE 流式 token → React 实时渲染
```

### 数据导入
```
CSV File / 微信 / 支付宝
     → POST /api/import/csv (parse 预览)
     → import_parsers.get_parser(source) → ParsedTransaction[]
     → 用户确认 → POST /api/import/csv/confirm
     → db.add_transaction() ← owner_id + is_shared
     → provenance.record_provenance() (异步审计)
```

### MCP 工具调用
```
Claude Code / Cursor
     → MCP Protocol (stdio / SSE)
     → FastMCP Server (mcp_server.py)
     → tools.py / calculations.py / db.py
     → JSON string response
```

## 关键设计决策

### 1. 代码算数 + LLM 叙述 分离
所有数字（净值、收益率、风险指标）由确定性 Python 计算，LLM 只负责把结果"讲成人话"。同源 FinRobot 的设计范式。

### 2. 双模部署
- **Web 模式**：独立 React 前端，完整 UI 体验
- **MCP 模式**：作为 MCP Server 接入任意 AI IDE（Claude Code、Cursor、Windsurf）

### 3. 协议优先
- 工具暴露走 **MCP 协议**（不用自定义 RPC）
- 流式推送走 **SSE**（不用 WebSocket）
- 鉴权走 **JWT**（不用自研 token 算法）
- LLM 访问走 **LiteLLM 统一协议**（不用每个模型一套 SDK）

### 4. 单一共享连接 + asyncio.Lock
SQLite 全局单连接 + asyncio.Lock 保护关键写操作。在个人/中小商户场景下足够，避免引入 PostgreSQL 的运维复杂度。

### 5. 增量迁移
数据库 schema 升级通过 `_migrate_add_columns()` 幂等执行，不破坏现有数据。

## 功能覆盖

| 模块 | 状态 | 关键能力 |
|------|------|---------|
| 对话 Agent | ✅ | LangGraph 多节点, HITL 审批, 流式输出, 多模型路由 |
| 记账 | ✅ | 语音/文字/CSV/微信/支付宝导入, 智能分类 |
| 持仓管理 | ✅ | 多标的/多行业, 实时行情, K线, 盈亏分析 |
| 风控 | ✅ | 集中度/应急金/DTI/储蓄率/高息负债 多维告警 |
| 预算 | ✅ | 分类/总预算, 实时进度, 超支预警 |
| 目标 | ✅ | 储蓄/还债/投资目标, 进度追踪, on_track 判断 |
| 净值追踪 | ✅ | 实时净值, 资产/负债组成拆解 |
| 收益率 | ✅ | XIRR, TWR, 简单收益率 |
| 健康评分 | ✅ | 五维评分 0-100 + A/B/C/D/F 等级 |
| 家庭共享 | ✅ | 多成员, 权限分级, 成员间借贷, 汇总仪表板 |
| 定时任务 | ✅ | 晨报, 订阅提醒 |
| 数据导入 | ✅ | 通用 CSV, 微信支付, 支付宝 |
| 行情 | ✅ | 东财+新浪双源, 自选, K线, 搜索 |
| PWA | ✅ | 离线缓存, 移动端安装, Service Worker |
| MCP Server | ✅ | 完整工具集暴露, 独立进程或嵌入模式 |
| 审计追踪 | ✅ | Provenance log, 环形缓冲区 + SQLite |
