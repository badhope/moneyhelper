# Moneyhelper — 代码规范与工程约定

## 1. 设计原则

| 原则 | 实践 |
|------|------|
| **不重复造轮子** | 能用成熟库/标准协议直接用的，绝不手写。优先复用项目已有依赖。 |
| **确定性计算优先** | 所有金额、收益率、健康评分等数值计算必须是纯代码确定性执行。LLM 只做"叙事解读"。 |
| **协议优先** | 对外接口遵循官方协议：MCP、OAuth 2.0、OpenAI-compatible API、SSE。 |
| **纯函数可测** | 业务核心逻辑拆为纯函数，单测覆盖 ≥95%。 |
| **错误不中断** | 批量操作（导入、批量更新）中单条错误不影响整体，收集到 errors 列表。 |

## 2. 目录结构

```
backend/app/
├── agent_graph.py        # LangGraph 多节点编排（HITL interrupts, Command resume）
├── analysis.py           # 确定性分析内核：持仓/风控/净值/现金流（纯函数）
├── calculations/         # 确定性计算引擎（净值/收益率/健康评分/目标进度）
│   ├── net_worth.py
│   ├── returns.py        # XIRR（牛顿迭代+二分回退）、TWR、简单收益
│   ├── health.py         # 财务健康五维评分（储蓄率/DTI/应急金/集中度/多样性）
│   └── goals.py          # 目标进度确定性计算
├── db.py                 # SQLite + aiosqlite (WAL mode, FK on, incremental migrations)
├── evaluate.py           # 规则驱动的首页评估层（纯函数规则 → EvalItem list）
├── import_parsers/       # 数据导入解析器
│   ├── base.py           # TransactionParser 抽象类 + ParsedTransaction
│   ├── generic_csv.py    # 通用 CSV 自动列名识别
│   ├── wechat.py         # 微信支付账单
│   └── alipay.py         # 支付宝账单
├── mcp_server.py         # MCP Server 双模（嵌入 FastAPI / 独立 stdio）
├── provenance.py         # 审计追踪（环形缓冲区 + SQLite 持久化 + fire-and-forget）
├── quotes.py             # 行情数据（东财 → 新浪 备源 fallback chain）
├── routes/               # FastAPI APIRouter 按业务域拆分
│   ├── budgets.py
│   ├── calculations.py
│   ├── debts_subs.py
│   ├── family.py         # 家庭汇总仪表板
│   ├── goals.py
│   ├── import_routes.py
│   ├── market.py
│   ├── members.py        # 家庭成员管理
│   └── provenance.py
├── scheduler.py          # 定时任务（晨报、订阅到期提醒）
└── tools.py              # Agent 工具集（供 LangGraph + MCP 调用）

frontend/src/
├── components/
│   ├── dashboard/        # Dashboard 子组件（净值/收益率/健康/目标卡片）
│   ├── settings/         # 设置页面子组件
│   ├── ui/               # 通用 UI 组件（Radix 风格 + Tailwind）
│   ├── chat-view-state.ts # ChatView 状态 hook（逻辑与 JSX 分离）
│   └── ChatView.tsx      # 纯 JSX 渲染层
├── lib/
│   ├── calculations.ts   # API hooks (useNetWorth/useHealthScore/...)
│   ├── index.ts          # Barrel export 统一入口
│   └── ...
└── sw-register.ts        # Service Worker 注册（PWA）
```

## 3. Python 风格

- 全部 `from __future__ import annotations`（PEP 604 union types）
- 类型注解全覆盖（mypy-ready）
- 常量全大写，dataclass 做 DTO
- 纯函数命名 `calculate_*` / `list_*` / `get_*`
- 错误类型：`ValueError`（输入不合法）、`LookupError`（实体不存在）
- 避免函数内 import —— 统一在顶部
- DB 迁移幂等：`CREATE TABLE IF NOT EXISTS` + `_migrate_add_columns()` 检测

## 4. TypeScript 风格

- React 19 + hooks 优先
- 大型组件逻辑抽取为 custom hook（`use*`），JSX 组件纯渲染
- 稳定回调用 `useRef` 包裹避免闭包陷阱
- 错误边界：`<ErrorBoundary>` 包裹关键视图
- 加载态：Skeleton / Spinner
- 空状态：统一 `<EmptyState>` 组件 + 场景插图
- 国际化：所有显示文本走 `t()` 函数，zh.ts / en.ts 键完全对齐

## 5. 安全

- 鉴权：`verify_api_token` 共享函数 + JWT (PyJWT)
- 时序安全：`secrets.compare_digest` 对比 token
- 密钥加密：PBKDF2 (100k iters) + Fernet（vault.py）+ asyncio.to_thread
- PBKDF2 异步化：推线程池避免阻塞事件循环
- SQLite WAL + foreign_keys + 事务性写入
- 金融操作审计追踪 (provenance_log)
- 不保存明文 API key（Fernet 加密后入库）

## 6. 测试

- Backend: `pytest`（pytest-asyncio），命名 `test_*.py`，单文件内 `class Test*` 或直接函数
- Frontend: `vitest` + `@testing-library/react`，`src/**/*.test.tsx`
- 覆盖目标：核心业务逻辑 ≥95%，UI 组件 ≥80%
- 纯函数直接断言、DB 相关用临时数据库 fixture

## 7. 协议遵循

| 协议/规范 | 使用场景 |
|-----------|---------|
| MCP (Model Context Protocol) | Agent 工具暴露给 Claude/Codex/Cursor |
| LangGraph | Agent 多节点编排 (StateGraph, interrupts, resume) |
| LiteLLM | 统一多模型访问（OpenAI/DeepSeek/通义/豆包） |
| SSE (Server-Sent Events) | 流式回答推送 |
| FastAPI APIRouter | 路由模块化 |
| PWA / Service Worker | 离线缓存 + 移动端安装 |
| SSE Starlette | 流式响应 |
