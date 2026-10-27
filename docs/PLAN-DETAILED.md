# moneyhelper 详细实施计划（步骤版 · 可直接照做）
> 2026-10-17 · 上游文档：08 总规划 / 09 头脑风暴 · 本文把所有"概念"展开成"步骤"
> 约定：每步都有【改动点】【做法】【验证】；做完一步提交一次（conventional commit）

## 〇、多视角检查表（防漏网，每个里程碑开工前过一遍）
| 视角 | 每次必问 |
|---|---|
| 架构 | 这个改动属于 core 还是壳？会不会让壳偷看 core 内部？ |
| 数据 | schema 变了怎么迁移？旧数据用户升级后第一秒会不会崩？ |
| 兼容/迁移 | 老版本前端连新后端？MCP 老客户端？→ 都要兼容一个版本期 |
| 安全 | 新端点鉴权了吗？新输入校验了吗？日志里有没有泄漏密钥/账目？ |
| 性能 | 新查询会不会全表扫？新前端 chunk 会不会拖首屏？ |
| 测试 | 新行为有没有测试？改动后 546 基线还绿吗？ |
| 可观测 | 新链路有没有 span/日志？出问题 5 分钟能定位吗？ |
| UX/i18n/无障碍 | 中英文都有吗？适老模式下能看清/听懂吗？ |
| 合规 | 涉及账单/身份的数据存储位置？云端形态的个人信息保护合规？ |
| 成本 | 这步烧多少 LLM token？有没有平价路由？ |
| 回滚 | 这步上线后能单独回滚吗？feature flag？ |

## 一、M0 稳固+补课（步骤级）
### M0.1 修 P1-1：litellm_chat 键名
- 【改动点】backend/app/llm.py L491 附近
- 【做法】`cfg.get("api_key")` → `cfg.get("key")`；顺手加单测：伪造 cfg={"key":"sk-x"} 断言传给 litellm 的 api_key 正确
- 【验证】pytest tests/test_llm.py 全绿；真实模型一次 chat 冒烟
### M0.2 修 P1-2：多段记账原子性
- 【改动点】service.py `_try_nl_add()`；db.py 新增 `add_transactions_batch()`
- 【做法】db 层加批量函数：单连接 `async with conn.execute("BEGIN")` 循环 insert 后 commit，异常 rollback；service 只调它
- 【验证】新单测：构造第 2 条必失败（非法日期），断言第 1 条未入库
### M0.3 修 P1-3：402→400
- 【改动点】main.py batch_undo 校验分支 status_code=402→400；test_input_guards 补断言
### M0.4 mem.remember 阻塞
- 【改动点】agent_graph.py supervisor 节点调用处
- 【做法】`await asyncio.to_thread(mem.remember, q)`；评估路径同理；加 WARN 日志记录耗时
- 【验证】fake mem0 慢 2s，测事件循环不卡（并发 ping 延迟不变）
### M0.5 tiktoken 声明
- requirements.txt 加 `tiktoken>=0.8,<1`（与 litellm 版本对齐核查）
### M0.6 P2 批处理（同模式小修）
- 限流器：cachetools.TTLCache(maxsize=10000, ttl=60) 替换裸 dict，首请求计数修正
- /api/metrics 移出免鉴权白名单（或加只读 token）
- provenance 带真实 username（agent 工具循环透传当前用户）
### M0.7 逐行通读补完（防漏承诺）
- 顺序：db.py→analysis→quotes→mcp_server→scheduler→nlparse→evaluate→vault→backup→auth→mem→csvimport→react_agent→其余
- 前端：App.tsx 起全部组件逐个过
- 【产出】每文件一行"职责+风险+发现"追加进 02 文档；新发现 bug 进 M0.8
### M0.8 zcode / deepseed harness 专项调研
- 【做法】各出一份 1 页纸：架构图/工具面/上下文管理/沙箱/审批/可抄清单 → 并入 07 报告
### M0.9 仓库瘦身
- 【做法】①`git rm -r doc-fetch-resources` ②README 收敛（README.md=中，README.en.md=英，删兼容指针）③docs 报告移 docs/archive/ ④视频动图改外链（README 用 release 资产 URL）⑤.gitignore 加规则 ⑥CI 加 1MB 文件检查
- 【验证】clone 体积 <5MB；`git count-objects -vH`
- 【回滚】纯文件移动，无风险

## 二、M1 模块化 + 文档骨架（步骤级）
### M1.1 包骨架建立
- 【做法】建 core/server/mcp/cli 空包 + pyproject 分包（单仓库多包，uv/pip -e 安装）；旧 `backend.app.*` 保留 import 兼容层 3 个月（`from core.ledger import X` re-export）
### M1.2 db.py 拆分（最重的一步，分 5 次提交）
- 顺序：users→transactions→positions→settings→sessions，每次：函数搬移+旧路径 re-export+全量 pytest
- 【做法】`db/__init__.py` 门面 `from .users import *`；事务边界集中在 ledger/connection.py
### M1.3 连接池（为 M3 铺路）
- 【做法】aiosqlite 读写分离：1 写连接（串行）+N 读连接（WAL 允许并发读）；`db.execute_read/execute_write` 两族 API；批量导入走写连接事务
- 【验证】并发 100 读+写混合压测脚本，无 "database is locked"
### M1.4 main.py 拆薄
- settings/qa-sse 路由迁 routes/；lifespan/中间件进 server/app_factory.py；main.py 只留装配（目标 <300 行）
### M1.5 文档站骨架（提前，按用户强调）
- 【做法】mkdocs-material + 目录：index/quickstart/self-host/mcp-guide/roadmap/adr/；.env.example 全量键位+中文注释；deploy/one-click.sh（docker compose up 全链路）
- 【验证】`mkdocs serve` 本地跑通；新人按 quickstart 15 分钟跑起全栈（找非开发者实测）

## 三、M2 协议补课（步骤级）
### M2.1 工具 schema pydantic 化
- 【做法】tools.py 每个工具定义 `class XInput(BaseModel)`；注册表统一产出 JSON Schema（MCP inputSchema 与 function calling 复用同一 schema 源）
### M2.2 MCP 全量暴露 + Streamable HTTP
- FastMCP 挂全部工具；传输层 streamable-http；旧 SSE 保留一个版本期
- 【验证】Claude Code 实测：记账→查询→报表三件套走通
### M2.3 HITL 迁 Elicitation；晨报迁 Tasks
- 大额审批 interrupt 改 MCP elicitation 形态（保留内部事件契约，外层映射）
### M2.4 AG-UI 映射层
- 【做法】SSE 事件 → AG-UI RunAgentInput/事件流适配器（独立模块 server/agui.py），前端加开关双协议
### M2.5 官方 saver 替换
- agent_graph `_HITL_THREADS`/`_savers` → langgraph.checkpoint.sqlite aiosqlite saver；pending 动作落库逻辑对齐

## 四、M3 财务部门模式（步骤级 · 核心差异化）
### M3.1 工单 schema（pydantic）
```python
class WorkOrder(BaseModel):
    id: str; dept: Literal["bookkeeping","accounting","risk","invest"]
    task: str; tools_allowed: list[str]; budget_tokens: int
    status: Literal["pending","running","done","failed","rejected"]
```
### M3.2 supervisor 升级为"派工"
- LLM 一次结构化输出产出工单数组（instructor 风格校验，失败走规则模板）；并行用 LangGraph `Send(dept_agent, order)` map-reduce
### M3.3 各部门 agent（复用 run_agent）
- 每部门 = 独立 instructions.md + 工具白名单 + 独立 thread_id（断点续跑）+ token 预算（超支自动收尾）
### M3.4 秘书（aggregate）节点
- 汇总各部门产出；数字交叉对账（同口径字段不一致→标红并回查 provenance）；产出《呈批件》：结论/发现/建议/证据索引
### M3.5 老板呈批（HITL）
- interrupt 阻塞等待：批准/追问（转单某部门）/驳回（附理由重跑）；审批结果落 provenance
### M3.6 部门实况看板（前端）
- 事件流：每个工单状态变更 emit SSE；前端工位图（四工位+秘书台）实时滚动工作日志
- 【验证】演示脚本：一句"盘一下上季度"→30 秒出呈批件（验收口径 #1）

## 五、M4 多端（步骤级）
### M4.1 CLI（typer+rich）
- 命令：`xm add <NL>` / `xm ls` / `xm report [月]` / `xm ask <问题>` / `xm dept run <任务>` / `xm serve`；`--json` 管道输出
- 直调 core（零网络），远程模式 `--url --token` 走 API（同一 CLI 两种形态）
### M4.2 Tauri 桌面（EXE/DMG/AppImage）
- sidecar 打包 server（PyInstaller 单文件）+ web 静态资源内嵌；tauri.conf 产物三平台；updater 自动更新；首跑向导（选模式：本地/连云端）
- 【验证】干净 Windows 虚拟机双击安装→语音/文字问"钱花哪了"出图（验收口径 #2）
### M4.3 发版自动化
- conventional commits + semantic-release：tag→GitHub Release 附三平台产物→Actions 镜像同步（badhope 系）→changelog 自动化

## 六、M5 可视化+适老（步骤级）
### M5.1 设计稿先行
- 适老模式 token：字号 20px+ 档/高对比主题/信息密度减半；图表三层结构规范（结论→图表→明细）
### M5.2 ECharts 接入（动态 import）
- 图表清单：净资产长周期（主视图）/现金流瀑布/支出树图/订阅时间线/健康五维雷达/预算进度环/部门实况看板
### M5.3 后端预聚合
- /api/dashboard 返回聚合结果（SQL GROUP BY + TTL 缓存），前端不算数
### M5.4 语音闭环
- 语音输入（Web Speech/Sherpa-NCNN 本地）→ NL 记账/提问 → TTS 汇报（可选）；全程可不开屏键盘
### M5.5 反事实沙盒（时间旅行，若排期允许）
- fork 账本（事件流导出副本）→ 场景参数（收入/支出/大额决策）→ 确定性引擎推演 36 个月 → 对比视图 → merge 或丢弃

## 六、M6 生态+文档+获客（步骤级）
### M6.1 审计底稿导出（3 天）
- provenance 数据 → 模板渲染 → PDF（reportlab/weasyprint）；回答页一键下载
### M6.2 挑战赛+错误台账（零开发启动）
- README 挂"挑战 Moneyhelper"入口；GitHub Issue 模板"数字挑战"；每周《错误台账》post（公开复盘+修复 commit 链接）
### M6.3 模型招聘 eval（1 周）
- evaluate.py 扩展："会计上岗考题"50 题（记账/对账/风控判断）+ 自动评分 →《上岗考核报告》页（模型对比排行）
### M6.4 家庭议会（1 周）
- 大额阈值触发多人审批链（成员角色+票权）；通知（站内/PWA push）
### M6.5 文档站内容填充 + 教程三连
- "把 Moneyhelper 接进 Claude Code/Cursor/Cline"三篇（真实截图）；MCP Registry 上架流程走一遍
### M6.6 可复核性标准草案
- provenance spec v0.1（数据模型/校验规则/展示要求）→ 开源仓库+讨论区；先自证再邀请

## 七、新功能的多视角核查（逐个过表）
| 功能 | 最大风险 | 对策 |
|---|---|---|
| 部门并行 | 撞库/成本失控 | 读写连接池 + token 预算 + 平价模型路由 |
| 审计底稿 | 含敏感账目 | 导出前脱敏开关 + 水印 |
| 挑战赛 | 恶意刷 | 限每账号每周 N 次 + 公开数据集限流 |
| 模型招聘 | 评分主观 | 题库公开+评分规则公开+可复现 seed |
| 时间旅行 | 存储翻倍 | fork 副本懒创建+自动过期 |
| 家庭议会 | 骚扰通知 | 静默时段 + 聚合通知 |
| 语音 | 隐私（声纹） | 本地 ASR 优先，云端需明示开关 |

## 八、执行节奏（每步一提交，每里程碑一 tag）
- M0 每步独立 commit：`fix(llm): ...` / `fix(ledger): ...` …；M0 完打 `v2.1.0`
- 分支策略：main 保护 + feature 分支 PR（自审自合，但留审阅痕迹）；CI（现有 ci.yml）+ mirror（badhope 系）全绿才算完
