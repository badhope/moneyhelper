# 小满前端代码审计报告

> **历史快照，不代表当前状态**
>
> 记录日期：2026-10-13（入库日；对应 CHANGELOG 1.4.0 时期的代码）。
> 其中绝大多数 P0 已在 2.6–2.9.x 修复（个别更早）：MCP 鉴权（2.9.3）、认证绕过 / MCP 写工具绕过 / 限流 IP 绕过 / ECharts XSS（2.8.3）、Docker 数据目录（2.4.2）。
> 保留原文用于追溯当时的审计依据与修复过程；当前质量与进度以 [PROGRESS.md](PROGRESS.md) 与仓库根 `CHANGELOG.md` 为准。

> 审计范围：`frontend/src` · React 19 + Vite 7 + Tailwind 4 · 静态审计（未运行构建）

---

## 1. 安全

### 1.1 XSS

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 低 | `components/ChatMessageBubble.tsx` | 357 | Markdown 渲染使用 `ReactMarkdown`（默认不含 `dangerouslySetInnerHTML`），但 AI 生成内容中若含 `<script>` 标签仍可能被解析执行（react-markdown v9 默认不执行脚本，但 `remark-gfm` 下自定义组件需确认非白名单节点）。建议使用 `rehype-sanitize` 过滤危险节点。 |

**建议：** 安装 `rehype-sanitize` 并在 `<ReactMarkdown>` 中加入 `rehypePlugins={[rehypeSanitize]}`，确保 AI 生成的不可信内容被清洗。

### 1.2 敏感数据泄露

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 中 | `lib/api.ts` | 12 | Access Token 明文存于 `localStorage`（key: `wo.accessToken`）。若页面引入第三方脚本或被 XSS 攻击，攻击者可读取该 token 直接调用后端 API。 |
| 低 | `lib/ErrorBoundary.tsx` | 25 | `console.error("[ErrorBoundary]", err, info.componentStack)` 在用户控制台打印完整错误堆栈，可能暴露后端路径/版本信息。 |
| 低 | `lib/charts.ts` | 75 | `console.error("ECharts 加载失败", err)` 同上。 |

**建议：** Token 存储可考虑 `sessionStorage`（生命周期更短）或 httpOnly cookie（需后端配合）。控制台输出应在生产环境通过 esbuild rollup 的 `drop_console` 编译选项清除。

### 1.3 Token 硬编码

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 无 | — | — | 未发现硬编码 API Key 或 token。所有访问口令由用户输入，仅存于 localStorage。 |

---

## 2. 数据流与状态

### 2.1 状态管理方案

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 低 | `lib/store.ts` | 29 | 全局 `client` 变量依赖 `setQueryClient` 注入顺序。若模块级代码在 `main.tsx` 之前 import 并调用 `getQueryClient()`，会得到无 Provider 支撑的独立 QueryClient，导致后续 invalidateQueries 无效。当前实际调用时序安全，建议改用 React Context 获取 client 而非模块变量。 |

### 2.2 API 错误处理

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 中 | `components/ChatView.tsx` | 177 | SSE 请求携带 `attachments: attachments.map((a) => a.id)`，但未处理 attachment 已被其他会话删除的场景——后端可能返回 404/409，导致整条消息发送失败却只显示通用错误。 |

### 2.3 SSE 流式响应清理

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 低 | `lib/api.ts` | 134 | `openWhenHidden: true` 使得页面切到后台时 SSE 连接仍保持。用户长时间切走后返回，可能接收到大量积压事件导致 React 状态批量更新抖动。建议后台时降低帧处理频率或断开重连。 |

### 2.4 内存泄漏

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 低 | `components/chat-view-hooks.ts` | 156 | `recogRef` 持有 `SpeechRecognition` 实例。若 `useVoiceInput` 所在组件在语音识别过程中被卸载，`recogRef.current?.stop()` 可能未被调用（依赖 `useEffect` 清理，但当前无此清理逻辑），导致监听未释放。 |
| 低 | `components/ChatView.tsx` | 117 | `locate-flash` 动画定时器清理依赖 `useEffect` 返回函数，但该 effect 依赖项 `[messages, locateRunId]` 变化时旧 timer 是否被清除——若 `locateRunId` 快速变化可能遗留 timer。代码中已处理（`clearTimeout`），但路径不直观。 |

---

## 3. 错误边界

### 3.1 React Error Boundary

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 中 | `lib/ErrorBoundary.tsx` | 36-55 | 错误边界 fallback UI 文案未走 `useI18n`（类组件无法使用 hook），文案以中文/英文硬编码。与当前语言设置可能不匹配——英文用户看到中文错误。 |

**建议：** 将 fallback UI 抽为函数组件并嵌套 `I18nConsumer`，或在 `componentDidCatch` 中读 `localStorage("wo.lang")` 决定文案。

### 3.2 异步错误

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 低 | `components/chat-view-hooks.ts` | 91-94 | 历史加载失败被静默吞掉（`catch(() => {})`）。用户无法感知网络异常或权限失效，可能看到空白对话区却无任何提示。 |

### 3.3 降级 UI

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 无 | `main.tsx` | 39-45 | SW 注册失败静默忽略；ECharts 加载失败有 console.error；Markdown 加载失败有 Suspense fallback。整体降级策略合理。 |

---

## 4. 性能

### 4.1 长列表虚拟化

| 严重级 | 文件 | 行号 | 行号 | 描述 |
|--------|------|------|------|------|
| 中 | `components/FinishedMessages.tsx` | 50-64 | 消息列表无虚拟化——全部消息以 `Array.map` 渲染 DOM 节点。当对话历史达到几百条（如设置 limit=50 每条包含 Markdown 解析与语法高亮），滚动性能显著下降。 |

**建议：** 引入 `@tanstack/react-virtual` 或 `react-window` 做虚拟化渲染，或在前端实现“折叠较早消息 + 仅展开最近 N 条”策略。

### 4.2 ECharts 懒加载

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 无 | `lib/charts.ts` | 19-41 | ECharts 按需异步导入 + 模块注册 + 失败重试 + StrictMode 复用已有实例，实现完整。 |

### 4.3 重复渲染

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 低 | `components/ChatView.tsx` | 231-240 | 每次 render 重新赋值的 useRef（如 `sendRef.current = send`）本身不会触发重渲染，属于稳定化回调的标准做法。 |
| 无 | `components/chat-view-hooks.ts` | 244-348 | `streamEventPatch` 纯函数设计良好，通过 `patchMsg(replace)` 确保引用更新可被 memo 捕获。 |

### 4.4 PWA / Service Worker

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 中 | `public/sw.js` | 9 | Cache 版本号 `wo-shell-1791133992969` 看似为构建脚本替换，但 fetch handler 中 `refresh` 变量始终为 pending——若用户离线时访问未缓存的静态资源（如某 chunk 文件），`hit` 为 undefined 直接返回 pending Promise，UI 无响应。应回退到 `caches.match("/index.html")`。 |

---

## 5. i18n

### 5.1 key 一致性

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 中 | `lib/lang/en.ts` | — | `chat.toolWatch` key 在 `zh.ts`（行 221）存在但 `en.ts` 缺失。切换英文后该文案回退显示 key 原文 `chat.toolWatch`。 |

**建议：** 在 `en.ts` 中补齐 `"chat.toolWatch": "Add to watchlist"`。推荐引入 CI 脚本检测 zh/en key 一致性。

### 5.2 完整性

| 项 | 值 |
|----|-----|
| zh.ts key 数 | 639 |
| en.ts key 数 | 638 |
| 缺失 | `chat.toolWatch` (en.ts) |

其余 key 完全一致，i18n 框架设计合理（fallback 链：lang → en → key 本身）。

---

## 6. 组件职责

### 6.1 单组件过长

| 严重级 | 文件 | 行数 | 描述 |
|--------|------|------|------|
| 中 | `components/EntryView.tsx` | 898 行 | 组件超过 500 行，承载记账表单、CSV 导入、负债/订阅/目标管理等多个独立功能域。建议拆分为 `<TransactionForm>` / `<CsvImporter>` / `<DebtManager>` / `<SubscriptionManager>` / `<GoalManager>` 子组件。 |
| 低 | `components/Dashboard.tsx` | 712 行 | 包含 QuickLedgerBar、TopHoldings、RiskBanner、DueSoonStrip、AssetMix、SpendingMix、TrendChart 等多个内嵌函数组件。建议将各 block 抽为独立文件。 |

### 6.2 逻辑复用

| 严重级 | 文件 | 行号 | 描述 |
|--------|------|------|------|
| 低 | `lib/format.ts` | 1-8 | `moneyLocale` 为模块级可变状态。若 SSR 场景或多实例并行调用 `setMoneyLocale` 会互相覆盖。当前为 SPA + 无 SSR，风险低，但建议依赖注入或改为 Context 传递。 |

---

## 审计摘要

| 严重级 | 数量 | 关键问题 |
|--------|------|----------|
| 严重 | 0 | — |
| 高 | 0 | — |
| 中 | 5 | Token 本地化存储、Markdown 无 sanitize、错误边界无 i18n、长列表无虚拟化、SW 离线回退缺失 |
| 低 | 7 | 多处控制台泄露、语音识别未清理、历史加载静默失败等 |

**整体评价：** 代码质量良好，SSE 流式处理、AbortController、内存清理、React 性能优化（memo + useMemo + useCallback 稳定化回调）均有完整实现。建议优先修复 i18n key 缺失（chat.toolWatch）、添加 rehype-sanitize 防护、对长消息列表引入虚拟化。
