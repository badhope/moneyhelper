# 剩余路线统一完成报告（4.16.42 → 4.16.44）

日期：2026-11-23  
版本：4.16.44  
约束：不新开顶层板块、不新增独立模块；所有入口落在聊天、对话头、回答操作条与输入区。

## 总表

| 路线 | 落点 | 状态 | 验证 |
|---|---|---|---|
| 回答依据 + 质量反馈 | 回答下方「依据」、赞/踩、设置里的反馈汇总 | 已完成（4.16.42） | 浏览器点踩/原因/汇总、历史回看；后端全量 1892 passed / 4 已知失败 |
| `@` 引用工作台文件 | 输入框 `@` 面板、引用胶囊 | 已完成（4.16.43） | 浏览器引用后回答 510880 / 3.429 元；工作台文件数不变；前端 241 项通过 |
| 会话项目卡 | 会话头「项目资料」、空会话引导 | 已完成（4.16.44） | 固定文件自动进入回答、项目指令生效应验、跨会话/跨用户隔离测试 |
| 只读分享 | 会话头「分享」、`/s/{token}` | 已完成（4.16.44） | 生成/复制/打开/撤销；撤销与过期 404；HTML 转义与 noindex 测试 |
| 回答画布 | 回答操作条「画布」 | 已完成（4.16.44） | 编辑/预览/下载/存入工作台；工作台 2 → 3 |
| 深度研究 | 输入区开关 | 已完成（4.16.44） | 浏览器输出「结论/依据/风险与不确定性/来源」四节；强制联网 |
| 回答长度三档 | 输入区下拉 | 已完成（4.16.44） | 简洁模式生效、localStorage 记住；后端参数贯通测试 |
| 生成参数全链贯通 | `run_question → run_graph → AgentState → run_agent → build_turn_context` | 已完成（4.16.44） | 单元测试捕获 `session_context/deep_research/llm_options` |

## 4.16.44 具体交付

### 数据层

- `thread_projects`：`user_id / thread_id / instructions / attachments_json / memories_json / updated_at`，唯一键按用户+线程。
- `shares`：`token / user_id / thread_id / title / payload_json / created_at / expires_at / revoked`。
- 上限定死：指令 2000 字、附件 10、记忆 10 条（单条 200 字）；附件只接受当前用户自己的。

### 接口

```text
GET/PUT/DELETE /api/threads/{thread_id}/context
POST           /api/shares
DELETE         /api/shares/{token}
GET            /s/{token}
```

### 生成链路

- `qa.py` 读取项目卡，合并固定附件，拼 `session_context`；
- `deep_research=True` 时强制 `web_search=True`，工具轮次下限 8；
- `answer_mode` 只写系统指令，不改路由、不改模型；
- `build_turn_context` 以 system 消息注入，截断 2600 字；
- 联网搜索兜底加 10 秒超时，网络受限时明确写数据局限。

### 分享安全

- token `secrets.token_urlsafe(24)`，默认 7 天，最长 30 天；
- 快照固化，不含 token 用量、模型参数、账本；
- 公网路径绕过 `/api` 鉴权，但只读；
- 所有内容先转义，只允许 `http/https` 来源链接；
- `Cache-Control: no-store`、`X-Robots-Tag: noindex,nofollow`。

## 验证记录

- 后端定向：`tests/test_thread_share.py` 4 项通过；`test_api.py + test_agent.py` 124 passed / 1 已知基线失败；`test_agent_graph.py` 12 项通过。
- 后端全量：`1896 passed / 4 已知基线失败`（4.16.42 的 1892 项 + 本轮 4 项新测试）。
- 前端：`tsc --noEmit` 通过；全量 34 文件 / 241 项通过；`npm run build` 成功。
- 浏览器：
  - 项目卡：指令、固定文件、记忆保存后计数 3；回答以「项目口径：」开头并引用固定资料。
  - 画布：编辑、预览、下载、存入工作台；工作台文件 2 → 3。
  - 分享：生成链接、打开只读页、撤销后 404。
  - 深研：四节报告 + 真实来源；无持仓/无估值数据时明确写「数据局限」。
  - 长度：简洁模式回答收短，选择被记住。
- 截图：`docs/screenshots/130`–`137`。

## 已知基线失败（非本轮引入）

- `tests/test_agent.py::test_agent_calls_tool_then_answers`
- `tests/test_studio_api.py::test_primary_role_tool_allowlist_filters_tools`
- `tests/test_studio_api.py::test_tool_allowlist_also_filters_mcp_tools`
- `tests/test_tools.py::test_web_search_fallback_on_search_failure`

## 明确不做

- **假温度 / 最大 token 滑杆**：没有同时穿透工具决策与最终回答两条路径前不做，避免「设置没生效」。
- **多人协作分享权限**：当前是单用户只读快照；成员权限、评论、过期后续签不在本轮。
- **画布反向改写消息**：画布产物独立，不覆盖原回答。

## 结论

此前列出的可落地剩余路线已在 4.16.42–4.16.44 内收口，入口全部留在原有聊天界面。4.16.44 的核心不是再加一个页面，而是把「这个会话记得什么、能给谁看、回答能否二次编辑、研究是否真的多轮」四件事做实。
