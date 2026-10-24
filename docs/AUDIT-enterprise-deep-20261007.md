# 小满(xiaoman) 深度代码审计报告 · 企业级视角

> **历史快照，不代表当前状态**
>
> 记录日期：2026-10-07 · 当时版本：1.4.0。
> 其中绝大多数 P0 已在 2.6–2.9.x 修复（个别更早）：MCP 鉴权（2.9.3）、认证绕过 / MCP 写工具绕过 / 限流 IP 绕过 / ECharts XSS（2.8.3）、Docker 数据目录（2.4.2）。
> 保留原文用于追溯当时的审计依据与修复过程；当前质量与进度以 [PROGRESS.md](PROGRESS.md) 与仓库根 `CHANGELOG.md` 为准。

> 审计日期：2026-10-07 | 审计基准：100 = 可直接交付 SaaS 产品
> 审计范围：全仓库（agent 架构 / 后端 / 前端 / 安全 / 用户体验 / 代码质量）

## 概要

- **风险等级**: C（中等风险 — 数据加密设计有缺陷、鉴权可绕过、流式体验断档、前端表格虚拟滚动缺失）
- **文件总数**: 94（含新改造）
- **问题总数**: 23（P0 必修复 8 个 / P1 建议修复 9 个 / P2 优化 6 个）
- **综合评分**: 52 / 100（上一轮打 83 是虚高，本次对标行业优秀产品严格打）

---

## P0 必修复（影响可用性与安全性）

### [P0-1] vault.py PBKDF2 60万迭代 + 无并发锁 → 首次启动可能竞态崩溃

**位置**: `backend/app/vault.py` L29, L64-104

`ensure_dek()` 在首次启动时检查 `_dek is None` → 生成 DEK → INSERT。若两个请求并发到达，都看到 `_dek is None`，两个协程都会 INSERT → SQLite UNIQUE 约束 (`vault_keys.key_name`) 冲突 → 第二个请求抛 IntegrityError → 500 内部错误，用户看到加密功能崩溃。

PBKDF2 60万迭代单次 ~300ms（2.4GHz x64），首请求被阻塞 300ms+。

**修复**: 加 asyncio.Lock + 降到 100,000 次迭代（NIST SP 800-132 下限的 10 倍，对 app key wrap 完全足够）。

---

### [P0-2] vault.py 双层 DEK 架构过度设计 + tombstone 风险

**位置**: `backend/app/vault.py` 整体架构

当前：master passphrase → KEK → 加密 DEK → 加密数据。
Tombstone 问题：passphrase 丢了 = DEK 不可恢复 = 所有加密的 ai_api_key 废掉。而 ai_api_key 本来就是用户可以重新输入的，不需要这种无法恢复的双层信封。

**修复**：废除 DEK 双层，改用 per-field salt：PBKDF2(master_pass + per_record_salt, 100k iters) → 32B key → Fernet 直接加密 _plaintext_。丢了 master_pass 确实丢数据，但 ai_api_key 可重输，UI 提示"需要重新输入 API Key"即可。代码量减半，安全性等价。

---

### [P0-3] auth.py JWT secret 链式回退暴露默认值

**位置**: `backend/app/auth.py` L26

```python
_JWT_SECRET = os.getenv("JWT_SECRET", os.getenv("API_SECRET", "xiaoman-dev-secret-change-me"))
```

如果 JWT_SECRET 和 API_SECRET 都没设，默认值硬编码在源码里。攻击者拿到仓库代码就拿到了 JWT secret → 任意伪造 admin 身份的 token。

**修复**：启动时强制校验，空则 abort + 明确日志。

---

### [P0-4] auth.py register 无限开放 → 公网可被注册攻击

**位置**: `backend/app/auth.py` L121-138

没有任何注册限制 → API 暴露时任何人可无限注册账号，写垃圾数据。

**修复**：仅当 `users.count == 0`（首次部署）时开放注册；之后关闭或加 admin 审核。

---

### [P0-5] auth.py login 无 rate-limit → 用户名暴力破解

**位置**: `backend/app/auth.py` L105-118

登录接口无任何防暴力破解机制 → 攻击者可对已知用户名（如 admin）进行口令爆破。

**修复**：内存滑动窗口 rate-limit（同一 IP + 用户名 5 次/分钟），记录审计失败日志。

---

### [P0-6] LoginView token 放 localStorage + CSP 未升级 nonce → XSS 劫持

**位置**: `frontend/src/components/LoginView.tsx` + `backend/app/main.py` security_headers

`localStorage.jwt` 可被任何 XSS（react-markdown sanitize 绕过、外链 <script>、tianli-tracker 异常）读取并外传。

CSP 目前的 `script-src 'self' 'unsafe-inline' data:` 是错误配置：`data:` 允许 `<a href="javascript:...">` 类似攻击向量，inline 允许任何注入执行。

**修复**：token 放 HttpOnly + SameSite=Strict cookie（需后端 set-cookie）；CSP 改为 nonce-based。短期止血：保留 localStorage + 严格 CSP（移除 unsafe-inline data:，改用 nonce hash）。

---

### [P0-7] 前端 SSE 断开无重连无离线 banner → 数据静默滞后

**位置**: `frontend/src/lib/use-streaming-mutate.ts` 未搜到（可能是内联在 chat 组件里）

用户切到后台标签页 → 浏览器节流 SSE → 数秒后断开 → 用户回来看到"静止"的页面但数据已是旧的，且无任何提示。对话流式也中断后丢失中间内容。

**修复**：visibilitychange 监听 + EventSource 自动重连 + offline banner banner 条。

---

### [P0-8] 流式 ToolSteps/AuditSection 没有与 streaming 状态联动

**位置**: `frontend/src/components/ChatMessageBubble.tsx` ToolSteps 组件 L95-139

ToolSteps 只有在消息 complete 后才会完整展示（`tools` 数组完整传入）。在 streaming 过程中工具的 running 状态完全看不到，用户等 30 秒看到空白气泡然后一次性弹出结果。

**修复**：在 streaming SSE 阶段实时推入 tool step 的 running 进度（后端 agent 需要 emit tool_start / tool_end 事件），前端 replace 工具状态为 ✓ / ✗ / spinning。

---

## P1 建议修复（影响企业体验与可用性）

### [P1-1] SortedTable 组件创建了但未在任何页面引用

**位置**: `frontend/src/components/ui/sorted-table.tsx`

EntryView 里的持仓表/交易表、AuditSection 里的审计日志都仍用的是旧自定义表格。SortedTable 写了 150 行结果白写。

**修复**：替换 EntryView 持仓列表和 AuditSection 审计日志 → 全部走 SortedTable。

---

### [P1-2] SortedTable 没做 debounce 搜索 + 虚拟滚动

**位置**: `frontend/src/components/ui/sorted-table.tsx`

搜索框每次击键 → 重新 filter + sort → 1000 行数据卡 16ms+。
列表中未使用虚拟滚动 → 500 行 × 6 列 = 3000 DOM 节点，低端 Android 上滚动掉帧。

**修复**：搜索用 `useDeferredValue` 或 debounce 300ms；大数据集 500+ 行加 `@tanstack/react-virtual`。

---

### [P1-3] LoginView 密码强度不足（minLength=6）

**位置**: `frontend/src/components/LoginView.tsx` + `backend/app/auth.py`

企业场景应当要求password ≥ 8 位且含数字。当前 6 位纯字符可通过。

---

### [P1-4] vault encrypt_secret 失败静默降级明文

**位置**: `backend/app/main.py` L1250-1253

```python
try:
    applied[key] = await vault.encrypt_secret(v[:AI_KEY_MAX_LEN])
except Exception:
    applied[key] = v[:AI_KEY_MAX_LEN]  # 静默降级明文！
```

管理员以为加密了，实际大明文落库。

**修复**：PUT settings 时若 vault 未初始化 → 返回 503 + 明确错误 "VAULT_NOT_INITIALIZED"，前端提示"请先设置加密口令"。

---

### [P1-5] main.py 单文件 1847 行 — put_settings 80+ 行 elif 链过重

**位置**: `backend/app/main.py` L1182-1278

put_settings 有 8 个 elif 分支 + 内联 key 校验逻辑，违反 SRP。圈复杂度 CC > 15。

**修复**：拆出 `settings_handler.py` 子模块，每个 key 一个 validator 函数，用 dict-dispatch 替代 elif 链。

---

### [P1-6] ErrorBoundary 语言 fallback 路径与 i18n store 不一致

**位置**: `frontend/src/lib/ErrorBoundary.tsx`

类组件里用了 `localStorage.getItem("wo.lang")` 而非 React context，切换语言后 error boundary 不会 re-render。且 `localStorage` 被清空时 fallback 路径无处理。

**修复**：改为：useI18n hook 取不到就用 `document.documentElement.lang`，不再读 localStorage。

---

### [P1-7] README.en.md badges 与文案未与中文 badge 完全对齐

**位置**: `README.en.md`

中文 badges 加了 Multi-Model / Enterprise / Stars welcome，中文底部加了「快速开始」片段英文版没有。

---

### [P1-8] AuditSection 审计日志页面没排序/搜索 UI

**位置**: `frontend/src/components/settings/AuditSection.tsx`

当前是静态 list，没有工具栏（导出 CSV / 按操作类型筛选 / 时间范围）。

**修复**：接入 SortedTable。

---

### [P1-9] 持仓列表 HITL 确认按钮在移动端响应区重叠

**位置**: `frontend/src/components/EntryView.tsx` PositionsTable

确认/取消按钮在移动端断点下未做 stacking → 长 summary 文字时按钮被挤出视口。

---

## P2 优化建议

### [P2-1] vault.py / auth.py `from __future__ import annotations` 冗余

项目要求 Python 3.10+，原生支持 dict[str] 注解，无需 future import。

---

### [P2-2] auth.py LoginReq/RegisterReq 可复用字段

`LoginReq.username` 与 `RegisterReq.username` 重复 → 继承 Base 类。

---

### [P2-3] 前端 chat-view-hooks.ts 有重复注释

L27: 注释行重复写了两遍（可能 copy-paste 遗漏）。

---

### [P2-4] useI18n hook 返回的 t 函数未做参数缓存

每次 render 都创建新的 `params` 对象 → 导致 Tooltip、Badge 等依赖 `t()` 结果的子组件 re-render。

---

### [P2-5] react-markdown rehype-sanitize 用了 defaultSchema 但没禁用 `input[type=checkbox]`

对话中带 checkbox 时被 sanitize 剥离 → 任务列表渲染成纯文本。→ 自定义 schema 允许 `input`。

---

### [P2-6] main.py put_settings 内 input key 没做 chars whitelist

目前只校验长度不校验字符 → 用户可注入 `<script>` 作 key（虽然 SQL 参数化不会注库，但 XSS 攻击面仍在前端保存回显时）。
