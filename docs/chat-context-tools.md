# 项目资料、视觉输入、分享、画布与深度研究

4.16.44 把项目卡、分享、画布、深度研究与回答长度放进原有聊天；4.16.45 继续在原入口内补齐跨会话项目库、图片视觉输入、成品导出与检索深度。没有新顶层页面，也没有新导航分组。

## 会话项目资料与跨会话项目库

入口：会话头部的「项目资料」。

一次性资料仍是三项：

- **项目指令**：最多 2000 字，每次提问前作为 system 消息注入；
- **固定文件**：最多 10 个，从工作台已有附件里选；每轮自动加入本轮附件 id，不复制、不再上传；
- **项目记忆**：最多 10 条、每条 200 字。

4.16.45 起，弹层顶部增加「跨会话项目」：可以选「仅本会话」，也可以选择已有项目或内联新建并绑定。绑定后，同一项目的会话共享指令、固定文件与记忆；会话历史仍各自独立。

隔离规则：数据按 `user_id + thread_id` 落库；项目库按 `user_id + project_id` 落库；附件 id 只接受当前用户自己的附件。项目更新会同步刷新所有绑定线程的副本；显式解绑后线程退回「仅本会话」；项目删除后线程保留最后一次资料，不会突然清空。

接口：

```text
GET    /api/threads/{thread_id}/context
PUT    /api/threads/{thread_id}/context      # 可带 project_id 绑定/解绑
DELETE /api/threads/{thread_id}/context

GET/POST       /api/chat-projects
GET/PUT/DELETE /api/chat-projects/{project_id}
```

## 图片视觉输入

入口：输入框附件。上传 PNG / JPG / WEBP / GIF 后，图片不只是工作台文件，会随本轮问题真正送进模型：

- `qa.py` 从附件中取 `kind=image` 的原始 base64，最多 4 张、base64 总量不超过 20MB；
- `build_turn_context` 把图片转成 OpenAI 兼容 `image_url` 内容块，和文字问题组成多模态 user 消息；
- 系统提示要求只读图中真实可见信息，看不清或被裁掉的部分必须说明，不得猜数字、文字或人物；
- 模型端点不接受图片、或首轮 45 秒内没有结果时，自动去掉图片按文字重试，并明确说明「当前模型不接受图片，已改按文字回答」；
- 前端在附件下方提示「图片会随本轮问题一起送给模型；模型不支持视觉时会明确回退文字」。

同一轮最多 4 张，避免相册把请求拖死。图片不参与知识库正文检索，避免把 base64 当文本切片。

## 只读分享

入口：会话头部「分享」。

- 创建时固化该 `thread` 最多 100 条 run 的 `question / answer / sources / created_at`；不含 token 用量、模型参数或账本。
- token 由 `secrets.token_urlsafe(24)` 生成；有效期 1–30 天，默认 7 天。
- 公网路径 `/s/{token}` 不带 `/api` 前缀，不要求登录；返回 `Cache-Control: no-store` 与 `X-Robots-Tag: noindex,nofollow`。
- 撤销或过期后返回 404。
- 分享页与画布共用 `artifact_export.py` 的安全 Markdown 渲染，避免两套转义规则各说各话。

接口：

```text
POST   /api/shares
DELETE /api/shares/{token}
GET    /s/{token}
```

## 回答画布与成品导出

入口：回答操作条的「画布」。

- 编辑：直接改 Markdown 正文；
- 预览：复用 `MarkdownPreview` 的 sanitize；
- 导出：底栏格式下拉支持 Markdown / Word `.docx` / HTML，统一走 `POST /api/canvas/export`；
- 存入工作台：新增一个 `.md` 附件，原回答不变。

`artifact_export.py` 是内部纯函数模块：`safe_url / inline / body_text / body_html / html_document / docx_bytes`。DOCX 用标准库 zip + OOXML 生成，不引入 python-docx / reportlab 运行时依赖；支持标题、正文、标题层级、列表、代码块。长任务阶段产物复用同一接口，只把标题改成「任务标题 · 阶段名」。

接口：

```text
POST /api/canvas/export
body: { title, body, format: "md" | "html" | "docx" }
```

正文上限 20 万字符；中文文件名走 RFC 5987。HTML 输出先转义 `<script>`，Word 输出在 LibreOffice 中可正常打开。

## 深度研究与回答长度

- **深度研究**：开启后强制 `web_search=True`，最多 6 次联网、工具轮次下限 10 轮；系统指令要求拆 3 个角度检索，并按「结论 / 依据 / 风险与不确定性 / 后续观察点 / 来源」五节输出。达到 6 次后不仅从工具 schema 摘掉 `web_search`，执行层也拦截第 7 次调用。来源只列工具实际返回或正文真实出现的链接。
- **回答长度**：简洁 / 标准 / 详尽三档写进 `session_context`，不改模型、不改路由、不写全局设置；浏览器 localStorage 记住选择。
- 联网搜索 DDGS 兜底加 10 秒超时：网络受限时明确写「联网搜索超时」，不把整轮问答卡死，也不补造来源。

## 设置分组

设置顶部分组从 5 个并为 4 个：基础设置、AI 与自动化、Agent 能力、数据与安全。「质量与评测」并入「AI 与自动化」下的「模型评测」，功能没有删，只是不再单独占一个顶层分组。

## 任务可观测性（4.16.46）

### 聊天工具轨迹

- 聚合行显示工具数、失败数与总耗时；展开后每步显示状态、耗时、参数与结果摘要。
- 轨迹随 `runs.steps_json` 落库，刷新与换端后仍能回看，不再只剩一句“调用了 N 个工具”。
- 实时流里同一次调用会同时收到 `tool` 与兼容用的 `agent_step`，前端对内容一致的紧邻事件去重，避免 1 个工具显示成 2 个。

### 长任务阶段

- 阶段记录 `attempts` 与 `duration_ms`，成功、失败、取消三路都落盘；详情页显示完成数、失败数、重试次数，单阶段显示耗时。
- 尝试次数在模型调用前写入磁盘，取消后不会显示“重试 0 次”。
- 任务仍支持后台执行、真实取消、失败阶段再次执行续跑，以及 `success_criteria` 进入每阶段提示词。

## 长任务单阶段控制（4.16.47）

- 阶段失败、被取消或跳过后，可在详情页点“重跑此阶段”；只执行目标阶段，其他已完成产物不动。
- `POST /api/longtasks/{id}/run` 新增 `stage_index`，与 `max_stages` 二选一；阶段运行中拒绝重复启动。
- 任务状态语义修正：只有后台协程在跑时才是 `running`；部分执行结束后回到 `pending`，并返回 `active` 供前端判断是否继续轮询。
- 进程重启残留的 `running` 在读取时归一为 `pending`，下次执行时把残留 running 阶段重置为待重跑。

## 边界

- 会话项目卡默认只作用于当前会话；绑定项目库后才跨会话共享。清会话不会自动删项目库行。
- 图片视觉输入依赖模型端点支持 `image_url`；不支持或超时会回退文字，不会伪装成已读图。
- 分享是快照，不随会话继续更新；不含任何账户或模型信息。
- 画布只编辑这一条回答，不反向改写消息。
- 没有做真实温度 / 最大 token 滑杆：参数没有同时穿透工具决策与最终回答两条路径时，宁可不做，也不做「设置不生效」的假功能。

## 验证

- 后端：`test_vision_research.py` 6 项、`test_deep_research_budget.py` 1 项、`test_thread_share.py` 5 项通过；4.16.46 全量 `1914 passed`。
- 前端：`tsc --noEmit` 通过；34 个文件 / 243 项测试通过；`npm run build` 成功。
- 真实浏览器：上传截图后模型回答出图内左侧栏、顶部工具栏、工作台与输入区设置；两个会话绑定同一「ETF 研究」项目后会话头均显示项目名；画布导出 Word / HTML 下载成功，Word 经 LibreOffice 打开正常；设置顶部为 4 组；长任务显示 `1/2 · 19.9s`，工具轨迹显示 `1 个工具 · 810ms`。
- 截图：`docs/screenshots/138`–`151`。
