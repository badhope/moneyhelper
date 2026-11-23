# 产品缺口收口报告（4.16.45）

日期：2026-11-23  
版本：4.16.45  
约束：不新开顶层板块、不新增独立模块；能力全部落在原有聊天、会话头、输入区、回答画布、设置与长任务页。

## 总表

| 缺口 | 原入口内落点 | 状态 | 验证 |
|---|---|---|---|
| 图片只上传、不进模型 | 输入框附件 + 多模态消息 | 已完成 | 真实上传截图，模型答出图内左侧栏、工具栏、工作台、输入区设置 |
| 深度研究只有 2 次联网 | 输入区「深度研究」 | 已完成 | 6 次检索 / 10 轮工具硬上限；五节报告；超限执行层拦截测试 |
| 产物只有 Markdown | 回答画布底栏 + 长任务阶段产物 | 已完成 | Markdown / Word / HTML 三种导出；Word 经 LibreOffice 打开转 PDF 正常 |
| 项目只到单会话 | 会话头「项目资料」弹层顶部 | 已完成 | 两个真实会话绑定同一「ETF 研究」项目，会话头均显示项目名 |
| 设置入口偏重 | 设置顶部分组 | 已完成 | 5 组并为 4 组，模型评测并入「AI 与自动化」 |
| 重复实现 | 分享 / 画布 Markdown 渲染、项目弹层、导出接口 | 已完成 | 分享与画布共用 `artifact_export.py`；项目库复用项目弹层；长任务复用画布导出 |

## 具体交付

### 图片视觉输入

- `qa.py` 从附件对象数组或 id 数组中取 `kind=image` 的原始 base64，最多 4 张、20MB；修复了前端对象数组被 `int(dict)` 静默吞掉的问题。
- `build_turn_context` 生成 OpenAI 兼容 `image_url` 内容块；文本问题保留在同一条 user 消息。
- `run_agent` 新增图片参数与首轮 45 秒探测超时；端点拒绝或超时后自动去图重试，并发出 thinking 说明。
- 通用问答分支也贯通图片：`agent_graph.general → service._run_general → agent.run_agent`，避免「看图」问题被通用模板抢答。
- 上传接口返回 `kind / mime`，前端附件胶囊下直接显示视觉提示。

### 深度研究

- `DEEP_RESEARCH_INSTRUCTION`：3 个不同角度、最多 6 次联网、工具轮次下限 10。
- 达到 6 次后从工具 schema 摘掉 `web_search`，执行层也拦截第 7 次。
- `qa.py` 深研提示同步改成「结论 / 依据 / 风险与不确定性 / 后续观察点 / 来源」五节。

### 成品导出

- 新增内部纯函数模块 `artifact_export.py`：安全链接、行内 Markdown、HTML 文档、标准库 DOCX。
- 新增 `POST /api/canvas/export`，支持 `md / html / docx`；正文上限 20 万字符，中文文件名走 RFC 5987。
- 画布底栏新增格式下拉与「导出文档」；长任务阶段产物新增「导出 Word」，复用同一接口。
- 分享页改为复用 `artifact_export`，删除本地重复渲染函数。

### 跨会话项目库

- 新表 `chat_projects(id,user_id,name,instructions,attachments_json,memories_json,created_at,updated_at)`；`thread_projects` 增加 `project_id`，旧库自动补列。
- 项目更新同步刷新所有绑定线程的副本；显式解绑退回「仅本会话」；删除项目后线程保留最后副本。
- 前端项目弹层顶部新增「跨会话项目」选择、内联新建与绑定；会话头显示「项目资料 · 项目名」。
- 项目指令 / 记忆提示从「仅本会话」改为「绑定项目后跨会话共享」。

### 设置与收敛

- `sections.ts` 把 `eval` 并入 `groupAi`，删除独立 `groupEval`；顶部 4 组。
- 项目库复用原项目资料弹层；长任务导出复用画布接口；`artifact_export.py` 只是内部复用模块，不是新功能板块。

## 验证记录

- 后端定向：`test_vision_research.py` 6 项、`test_deep_research_budget.py` 1 项、`test_thread_share.py` 5 项，全部通过。
- 后端全量：`1904 passed / 4 failed`，4 项均为既有基线失败，非本轮引入：
  - `tests/test_agent.py::test_agent_calls_tool_then_answers`
  - `tests/test_studio_api.py::test_primary_role_tool_allowlist_filters_tools`
  - `tests/test_studio_api.py::test_tool_allowlist_also_filters_mcp_tools`
  - `tests/test_tools.py::test_web_search_fallback_on_search_failure`
- 前端：`npx tsc --noEmit` 通过；`npm test` 34 文件 / 241 项通过；`npm run build` 成功。
- 浏览器：
  - 上传 `137-answer-length.png` 后提问，模型回答出图内左侧栏、顶部工具栏、右侧工作台与输入区设置项，未回退文字。
  - 两个会话绑定同一「ETF 研究」项目，会话头均显示项目名；项目弹层显示「ETF 研究 · 1/1」。
  - 画布导出 `.docx` 与 `.html` 均完成下载；DOCX 经 LibreOffice 转 PDF，标题、正文、列表正常。
  - 设置顶部 4 组；「模型评测」位于「AI 与自动化」下。
- 截图：`docs/screenshots/138`–`143`。

## 明确不做

- 假温度 / 最大 token 滑杆：没有同时穿透工具决策与最终回答前不做「设置不生效」的假功能。
- 多人协作分享权限：当前仍是单用户只读快照。
- 画布反向改写原消息：画布产物独立。
- 新增顶层项目管理页：项目库入口仍在会话头「项目资料」弹层。

## 结论

上一轮产品审计列出的五个缺口已在 4.16.45 全部收口，且没有再长出一个新页面。聊天壳仍是原来的聊天壳，变化在附件、回答、会话头和设置里，用户不需要重新学习入口。
