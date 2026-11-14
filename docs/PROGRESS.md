# 实施进度

> 单一进度真源。任何"还剩什么"的问题看这一页，不需要回头读规划文档。
> 计划本身见 [PLAN-DETAILED.md](PLAN-DETAILED.md)，本页只记状态。
>
> 更新规则：每完成一个里程碑就改这一页，并在末尾追加一行变更记录。

最后更新：2026-11-14 · 版本 4.16.0（后端 1719 测试 / 前端 195 单测 / E2E 55 / MCP 63 工具 / 339 路由）

## 总览

| 里程碑 | 完成度 | 状态 |
|---|---:|---|
| M0 稳固+补课 | 100% | 完成 |
| M1 模块化+文档骨架 | 100% | 完成 |
| M2 协议补课 | 100% | MCP 挂载/鉴权已修；定时产出改由 resource 暴露（Tasks 上游未支持，已有等价方案） |
| M3 财务部门模式 | 100% | 主链可用；工单级工具白名单已生效并有测试 |
| M4 多端 | 90% | Win 单文件实测、CLI 双形态（含 `dept run/list/approve`）、发版自动化完成；Tauri 2 桌面壳脚手架就绪（Rust 构建需在目标平台执行） |
| M5 可视化+适老 | 100% | 图表/响应式/字号档位/高对比/语音输入完成；后端预聚合完成；TTS 语音播报（`use-speech` + 设置开关）与反事实沙盒（`calculations/sandbox.py` + `/api/strategy/sandbox`）完成 |
| M6 生态+获客 | 95% | 审计底稿导出、50 题模型评测 + 排行榜完成；教程三连（Claude Code / Cursor / Cline）、MCP Registry manifest、可复核性标准草案、挑战赛错误台账、家庭议会完成 |

## 2026-11-14 · 4.16.0 企业化切片 8-10 + 安全边界（完成）

| 项 | 结果 |
|---|---|
| 采购/应付 | 供应商 → 采购单 → 应付 → 付款闭环；应付审核生成凭证草稿、付款生成银行侧凭证；复用 payments（claim_id=0 + payable_id）与银行流水匹配；7 个权限点；旧库唯一索引迁移为部分索引 |
| 安全边界 | 权限自升、agent-config/settings 敏感键无闸、内置安全 Hook 可停用、parse_invoice 误标只读、备份恢复可写行为配置、独立 MCP 绑 0.0.0.0 —— 6 项真实漏洞修复；新增 pathguard 保护程序自身目录 |
| 长任务引擎 | 阶段化执行 + 断点续跑 + 产物落盘 + 超时压缩重试 + 僵死任务重置；`/api/longtasks/*` + 前端「业务 → 长任务」；真实模型五项任务全 done，总产出 170,756 字 |
| UI 重构 | 设置页两级折叠（24 分区全可达）；财务区拆「业务 / 账务」两层（16 页全可达）；采购页表单折叠；修 ECharts 0 尺寸与模块竞态崩溃、纯日期伪造时分、日志 401 弹口令框 |
| 测试门禁 | 后端 1719 passed / 0 skipped；前端 195；Playwright E2E 55（设置 24 分区全可达 + 其中 22 项配置级验证、财务 16 页遍历）；`scripts/verify-all.sh` 一条命令全量；xdist worker 按 CPU 核数自适应 |
| 发版/推送 | release.sh 不再硬编码 python3；push_via_api.py 支持增量（152 blob）+ tree 内容级校验；gitcode/gitee 确认为 GitHub/badhope 自动同步镜像 |

## 2026-11-09 · 4.15.1 审计第二轮：税负引擎与账单解析（完成）

延续 4.15.0 的筛选标准（**结果错但接口不报错**），这一轮查钱进出的两端：税怎么算、账单怎么读。

| 项 | 结果 |
|---|---|
| 实发口径 | `payroll(months=N)` 的 `income_tax` 是累计预扣口径，`net_pay` 却把它减在一个月工资上：月薪 3 万、months=3 时实发报 **20295**，正确值 **21425**。现拆成 `income_tax`（累计）/ `current_month_tax`（当月）/ `net_pay`（单月实发）/ `period_net_pay`（期间合计），months>1 补 note；前端面板补 `months` 输入（此前写死 1） |
| 公积金基数 | 与社保共用 `base_max`，与自身 docstring「常见上限高于社保」矛盾：传 `housing_base=50000`、`base_max=35000` 实际按 35000 计。新增 `housing_base_min/max`（默认沿用社保口径，不传行为不变），路由与 MCP 同步暴露 |
| 基数区间倒置 | `base_min > base_max` 时 `min(max(...))` 静默退化，提示文案与基数互相矛盾。改为 ValueError |
| 返回结构 | `vat()` 免征分支缺 `surcharge_detail`，消费方必须为免征单开分支。补齐三项 0.0 |
| 月份校验 | `month_end_checklist` 放过 `2026-13` / `2026-00`，清单挂在不存在的月份上、按月查询永远查不到。补范围校验 |
| 金额符号 | `_parse_amount` 只认前导负号：会计负数 `(1,234.56)` → **+1234.56**、尾随减号 `100.00-` → **+100.00**，银行对账单的支出导入后变成收入。现支持括号（半/全角）与尾随减号；欧式小数逗号 `1.234,56` 由 **1.234** 修正为 1234.56 |
| 静默 0 笔 | 微信/支付宝缺「收/支」列时每行落进空值跳过分支：导入"成功"、0 笔、0 错误。现缺列报错回话，方向值无法识别的行单独计数进 errors |
| 报错行号 | 解析前过滤空行导致行号整体前移，微信/支付宝还多加一次 1（首条数据行报成表头 +3）。现保留原始行 + `enumerate(start=header_idx+2)`，三个解析器口径一致 |
| 0 元流水 | `generic_csv` 在金额列取到 0 时就认定有值，银行「金额列恒为 0 + 借贷分列」排版会塞一堆 0 元流水。现 0 视为无值，继续走借贷分列 |
| 验证 | 后端 **1618 tests**（新增 40 项）、前端 **189 tests**、ruff 零错、tsc 零错、vite build 成功，全量 0 failed |

## 2026-11-09 · 4.15.0 全量审计：修掉 9 个「算错但不报错」的缺陷（完成）

本轮不加功能，只做定向审计。筛选标准是**结果错但接口不报错**——崩溃会被
测试和用户发现，算错只会安静地给出一个看起来很专业的错误数字。

| 项 | 结果 |
|---|---|
| RSI 边界 | `avg_loss=0` 时旧实现按 RS=0 计算，单边上涨 60 根得出 RSI **0.00** 并触发「深度超卖」买入信号。现按口径给 100（无下跌）/ 0（无上涨）/ 50（全平盘）。本轮最严重的一处：不是精度问题，是把最强行情判成最该抄底 |
| 信号截断 | `sort(重要度升序)[-12:]` 留下的是**最不重要**的 12 条，实测 MA_CROSS / MACD_CROSS / KDJ_CROSS / BOLL_BREAK 全被丢弃，`bias` 由噪声决定（同一行情判 bear，实为 bull）。改为按「重要度 + 新近度」选取，输出保持时间升序 |
| 残缺 K 线 | `kdj()` 直接 `float(p["high"])`，行情层只保证 close 非空（停牌/新股的 high/low 是 `"-"` 占位）→ TypeError → 投研接口 500。现跳过残缺行并保留上一根 K/D |
| 序列错位 | closes 过滤了 None、dates/volumes 没过滤，有残缺行时所有 `ma[i]`/`dates[i]` 整体错开一格且无提示。新增 `clean_points()` 统一清洗；回测侧新增 `series_from_points()`（research / paper / MCP 工具共 6 处改用） |
| 放量判据 | 5 日均量把当天算了进去，实际阈值被抬到「前四日均量 × 2.67」，与文案不符。改为只用当日之前 5 根 |
| 盈亏比符号 | 分母是负收益率之和 → 恒为负（实测胜率 80% 报 `profit_factor = -1.82`）。改为 Σ盈利 ÷ \|Σ亏损\| |
| 除零 500 | 基准以 `closes[0]` 作分母，首价为 0（停牌/退市/脏数据）时 ma_cross 与 dca 抛 ZeroDivisionError。新增 `prepare_series()` 剔除非正价格；`strategies.py` 三处基准曲线收口到 `_benchmark_curve()`（此前 `_benchmark()` 已挡 0、曲线裸除，同一份数据一半 None 一半 500） |
| 参数语义 | `fast >= slow` 时「多头排列」判据反向，跑的其实是均值回归，但输出与正常回测无异。引擎抛 ValueError、路由 400、MCP 返回可读错误；前端输入框联动 + 非法参数不发请求 |
| 债务幻影预算 | `balance=0` 的负债（已结清车贷/已销卡）从第 1 个月起把月供当成「释放额度」灌进还款池：1 万元 18% 信用卡月供 300，加一条 balance=0/月供 2000 后还清时间从 **47 个月变成 5 个月**，而 `monthly_budget` 仍写 300。现只统计「起始就欠着、后来结清」的债，雪球效应不受影响 |
| 警告码同源 | 只要 warnings 非空就一律打 `negative_amortization`，「跑满 50 年未还清」被前端 i18n 翻成「月供不足以覆盖利息」，界面与后端结论互相矛盾（前端只认 code）。改为文案与 code 成对写入 |
| 日志降级 | `read_log_lines()` 的尾部随机读在文件被 truncate、或底层 FS 不支持越过 EOF 的随机读（FUSE/网络盘返回 EINVAL）时抛 OSError，把 `/api/logs`、看门狗自检、`/api/studio/diagnostics` 全打成 500——与 watchdog「监控自身不得成为故障源」的设计原则冲突。现降级为空 + `_scan_logs()` 兜底。这也是 `test_endpoint_health` 4 个用例在部分环境必红、本地与 CI 结论不一致的根因 |
| 定投笔数 | `trade_count` 数的是「计划投入次数」，跳过非正价格日时与 `total_invested ÷ invest_amount` 对不上。改为实际成交笔数 |
| 验证 | 后端 **1574 tests**（新增 32 项审计回归）、前端 **189 tests**（新增 5 项）、ruff 零错、tsc 零错、vite build 成功；全量套件 0 failed（此前 4 个环境相关失败一并修掉） |

## 2026-11-06 · 4.14.0 债务清偿规划 + 仓库收口（完成）

| 项 | 结果 |
|---|---|
| 债务清偿引擎 | `calculations/debt_payoff.py`：雪崩法（按年利率降序）/ 雪球法（按余额升序）/ 自定义顺序，逐月摊还模拟。输出还清顺序、月数、还清日期、总利息、相对「只付最低月供」的可省利息、逐月明细与结清里程碑 |
| 口径写死 | 月复利（余额 × 年利率 ÷ 12，ROUND_HALF_UP）；已结清负债的月供并入额外还款池（雪球效应）；月供大于余额的差额当期转投（不丢弃）；负摊还按「当月总余额是否上升」判定（不是「还款 vs 利息」，后者在某笔当月结清时误报）；基线为「只付最低且不重投」，与排序方法无关 |
| 端点 | `GET /api/finance/debts/payoff`（按账本负债）/ `POST` 同路径（试算 + 两方法对比）。输入非法返回 400 与具体字段，不吞成 500 |
| MCP 工具 | `debt_payoff_plan`（第 63 个工具），agent 侧同步注册 |
| 前端 | 新增「还债规划」页（`DebtPayoffPage.tsx`）：结论四卡、两方法对比、逐笔明细表、还清时间线；移动端两列摘要保证结论在首屏 |
| 防抖 | 新增 `useDebouncedValue`，额外还款额输入停 400ms 才查询；对比查询与主计划分开，改参数不出现旧结果 |
| 默认主题 | 首次打开改为亮色（原为跟随系统）；「跟随系统」仍是设置里的可选项 |
| 仓库收口 | 删除误提交的空文件 `Response` 与 `.monkeycode/` 工具产物；删除 CHANGELOG 中重复的 4.13.2 段落 |
| 文档 | README 改为英文主版（`README.md`）+ 中文版（`README.zh.md`），`README.en.md` 保留为重定向；截图全集重拍至 `docs/screenshots-v4.14/`（22 张，含新增还债页） |
| 验证 | 后端 **1540 tests**（新增 52 债务测试：引擎口径/输入卫生/端点契约）、前端 **184 tests**（新增 14）、tsc 零错、build 成功、22 张截图零溢出 |
| 版本漂移修复 | `server.json` 从 4.8.0 对齐到 4.14.0（此前 MCP Registry 清单落后 6 个 minor） |

## 2026-10-24 · 3.0.0 投资策略引擎（完成）

| 项 | 结果 |
|---|---|
| 确定性计算 | `calculations/portfolio_risk.py`（年化波动/夏普/索提诺/最大回撤/Calmar/Beta/Alpha/VaR + 基准对比）、`strategy.py`（目标配置漂移 + 整手可执行调仓清单）、`valuation.py`（750 日估值分位 + 定投统计 + FIRE 推演） |
| 组合风险 | 按当前持仓回溯净值曲线，与沪深300 / 上证 / 深成 / 创业板指对比；行情缺失时返回 available=false 与原因，不返回 500 |
| 再平衡 | 目标配置按标的设定容忍带，输出偏离度与买卖金额、约多少股；现金作为可配置目标项（CASH），不假设满仓 |
| 估值分位 | 当前价在近 750 个交易日区间中的位置，分低位/中枢/高位；只描述位置，不预测涨跌 |
| 定投 | 计划增删查 + 每期金额/累计投入/份额/成本线/当前盈亏/下一期扣款日 |
| FIRE | 目标本金（年支出/提取率）、完成度、储蓄率、按复利估算达成年限 |
| 后端接口 | `/api/strategy/*`：risk / allocation（GET+PUT）/ valuation / dca（GET+POST+DELETE）/ fire，共 5 条路径、8 个方法（`routes/strategy.py`） |
| Agent 工具 | 新增 5 个：`get_portfolio_risk` / `get_rebalance_plan` / `get_valuation` / `get_dca_plans` / `get_fire_plan`（财务工具总数 27） |
| MCP 工具 | 同上 5 个同步暴露到 MCP（工具总数 36） |
| 前端 | 新增「投资策略」页（`StrategyPage.tsx`）：风险指标条 + 净值曲线 + 再平衡清单 / 估值温度计双栏 + 定投表 + FIRE 进度，每块可独立降级 |
| 测试 | 新增 67 项策略测试（`test_strategy.py` 纯函数 + `test_strategy_api.py` 接口/租户隔离），后端总数 858 |

## 2026-10-23 · 2.9.3 安全与数据完整性收口

| 项 | 结果 |
|---|---|
| MCP 鉴权 | `/mcp`、`/mcp-sse` 与主 API 共用 `middleware.auth_gate`（口令 + 有账号必须 JWT），消除第二条信任边界 |
| 工具入参校验 | `validate_tool_args` 在 agent 循环 / action 节点 / confirm 三个执行边界统一接线，schema 不再只停留在声明 |
| 备份补表 | 附件、会话摘要、部门呈批件纳入导出与恢复 |
| CSV 列映射 | `generic_csv` 列名候选改为有序元组，跨进程解析结果一致 |

## 2026-10-23 · 2.9.2 收尾

| 项 | 结果 |
|---|---|
| 体检页 | 维度卡不再重复「建议」，只保留现状描述 |
| 启动开关 | `run.py` 支持 `MONEYHELPER_NO_BROWSER=1`，端口改读 `PORT` |
| 清理 | 关闭开发/演示进程，移除临时截图与演示库 |

## 2026-10-23 · 2.9.1 对话内富回答块 + 上下文条

| 项 | 结果 |
|---|---|
| 富回答块 | 持仓概览 / 本月收支 / 需要注意三类，可展开走势、可跳转处理 |
| 去重 | 同一信息不再在风险块、SummaryBlock、Action 按钮重复三遍 |
| 上下文条 | 对话顶部显示数据范围与更新时间 |

## 2026-10-23 · 2.9.0 四类能力补齐 + Agent harness 加固

| 项 | 结果 |
|---|---|
| 系统提示词 | 设置页可编辑 `instructions.md`，留空回落默认，即时生效 |
| 插件（MCP） | 增删外部 MCP 服务器、测试连接、显示已发现工具；URL 凭据打码，写工具仍禁止 |
| 知识库 | 上传文档 → 切片 → BM25 检索 → 注入 system 消息，可逐个开关 |
| harness | 工具循环检测（连续 3 次同参中断）、输出上限 2048、非流式重试 2 次 + 60s 超时 |


## 2026-10-21 · 2.7.0 可安装性 + 多平台 + MCP 资源

| 项 | 结果 |
|---|---|
| pip 安装 | wheel 从 15KB（缺 app）修到 320KB/102 文件；实测任意目录导入 + CLI 可用 |
| 多平台产物 | desktop.yml 三平台矩阵 + 启动冒烟测试 |
| MCP 定时产出 | 两个 resource 替代上游未支持的 Tasks |
| 文档站 | 16 条导航全存在、0 坏链（静态校验） |

## 2026-10-21 · 2.6.0 测试整改 + 权限 + 适老 + 桌面端

| 项 | 结果 |
|---|---|
| 测试真实性 | 揪出 7 个 mock 掉被测逻辑的部门和 3 个渲染型假测试；新增 6 项真实 agent 循环测试 |
| 权限模型 | 方案 B：严格租户隔离 + 管理员只读条数概览；越权测试 4 项 |
| 适老化 | 字号三档 + 高对比；390px 下特大字号无溢出 |
| 语音 | 识别语言跟随界面语言；5 项 hook 测试 |
| 桌面端 | 144MB 单文件实测可跑（健康检查/前端/写入/MCP 全通） |

## 2026-10-20 · 2.5.0 家庭账本 + 升级实证

| 项 | 结果 |
|---|---|
| 家庭账本界面 | 成员/借贷/汇总三块接入设置页，e2e 覆盖全流程 |
| 升级演练 | upgrade_drill.py：旧库 12 表数据完整、复合主键共存、幂等、旧路径搬迁全通过 |
| 迁移安全 | 动结构前自动整库备份 `.pre-mt-<时间戳>`，内容为迁移前状态 |

## 2026-10-20 · 2.4.2 部署修复

| 项 | 结果 |
|---|---|
| Docker 数据丢失 | 库/备份/checkpoint 统一到 `MONEYHELPER_DATA_DIR`（默认 `backend/data`），与卷一致；实测容器重建后数据保留 |
| 旧数据迁移 | 首次启动自动把旧 `backend/app/data` 搬到新位置（连带 -wal/-shm），升级不丢账本 |
| 镜像验证 | 实机构建 + 运行：健康检查 healthy、首页 200、MCP 200、非 root(1000) 运行 |

## 2026-10-20 · 2.4.0 多租户

| 项 | 结果 |
|---|---|
| 多租户 | 业务表加 user_id；四类业务主键表改复合主键；sessions/summary 唯一约束按租户拆分 |
| 迁移 | 启动时自动升级旧库（幂等）；历史数据归默认租户 |
| 护栏 | check_tenant_coverage 静态扫描 + 11 个隔离测试（数据层 7 / HTTP 4） |
| 健康分 | 统一为五维加权，补 grade 字段 |
| 部门工单 | tools_allowed 在执行阶段真正收窄工具面 |
| MCP 清仓 | 清仓按持仓市值计算并触发审批 |

## 2026-10-20 · 2.3.0 完成

| 项 | 结果 |
|---|---|
| 工具调用链路 | 修复 LiteLLM×mcp 版本冲突，模型可真实调用工具（已用真实模型验证） |
| MCP 部署 | `/mcp` 与 `/mcp/` 均可用；不再遮蔽前端；鉴权与来源校验对齐主站 |
| 设置持久化 | 新增保存栏，账本假设/晨报时间真正落库 |
| 数据一致性 | 备份补全 5 类数据；成员删除与撤回不再触发外键失败 |
| 安全 | 确认接口原子抢占；移除 health-check 免鉴权；根 `.env` 纳入忽略 |
| 长记忆 | 移除 mem0/chromadb，改本地 BM25，零外网外发 |
| 响应式 | 可拖拽侧栏/面板、手机底部导航、设置分组折叠、懒加载 |
| 界面范式 | 2.8.0：侧栏/主区/对话列按 ChatGPT 结构重排，Markdown 排版规范，移除重复 Agent 侧栏 |
| 界面审查 | 2.8.1：数据页改整页工作区（原 440px 抽屉挤坏表格）；修命令面板/K线/行情搜索/口语路由等 8 个真实缺陷 |
| 安全审计 | 2.8.3：认证绕过（Critical）、MCP 写工具绕过（High）、限流 IP 绕过、ECharts XSS 全部修复并加回归；README 截图重做 |
| 股票软件化 | 2.8.2：持仓/行情改双栏（明细 + 分析、列表 + 详情 + 迷你走势），记账改单行表格，体检重排；EXE 实打包并运行验证 |
| 跨平台 | 全部脚本自动适配 Windows/macOS/Linux |
| 代码清理 | 删规则引擎、11 个未用 UI、7 个依赖 |

## M0 稳固+补课 · 完成

| 项 | 产出 |
|---|---|
| M0.1 litellm 键名 | `llm.py` 用 `cfg.get("key")` |
| M0.2 多段记账原子性 | `db.add_transactions_batch` + 写锁串行化 |
| M0.3 402→400 | 校验失败返回 400 |
| M0.4 mem.remember 阻塞 | `asyncio.to_thread` |
| M0.5 tiktoken 声明 | requirements 显式声明 |
| M0.6 P2 批处理 | 限流首请求计数、metrics 移出白名单、审计归属 ContextVar |
| M0.7 逐文件通读 | `docs/module-map.md`（脚本生成，81 模块） |
| M0.8 harness 调研 | `docs/planning/11-agent-harness-专项调研.md` |
| M0.9 仓库瘦身 | 已删 doc-fetch-resources；CI 大文件检查 ≤1MB |

后续补修（审计发现计划里声称完成但有缺口）：
- litellm `retry_policy.retry_timeout` 是无效字段 → 改顶层 `timeout`
- DeepSeek `reasoning_content` 声称支持但未实现 → 按 `reasoning` 来源单列
- `.env.example` 缺 7 个在用变量 → 补齐

## M1 模块化+文档骨架 · 完成

| 项 | 产出 |
|---|---|
| M1.1 包骨架 | `moneyhelper/{core,server,cli,mcp}` 分层门面 + CLI（add/ls/report/balance/ask/serve） |
| M1.2 db 拆分 | `app/db/` 14 个域模块 + `_schema.py`；`_core.py` 793→471 行 |
| M1.3 连接池 | 1 写连接 + 3 读连接（WAL 只读）；`get_write_lock()` 串行化写事务 |
| M1.4 main.py 拆薄 | 1827→222 行；`system.py` 再拆 9 个域模块；70 端点零差异 |
| M1.5 文档站 | mkdocs-material + strict 构建；`deploy/one-click.sh`；CI hygiene job |

## M2 协议补课 · 80%

| 项 | 状态 | 说明 |
|---|---|---|
| M2.1 工具 schema pydantic 化 | 完成 | `app/tool_schemas.py` 31 个模型为单一真源；修两侧参数漂移 |
| M2.2 MCP 全量 + Streamable HTTP | 完成 | 31 工具；`/mcp` 无斜杠可用；SSE 保留至 `/mcp-sse/sse` |
| M2.3 HITL 迁 Elicitation | 完成 | `app/approval.py`；MCP 写工具 fail-closed 审批 |
| M2.3 晨报迁 Tasks | **阻塞** | mcp SDK 只有 experimental；fastmcp 2.12 未透传。见下 |
| M2.4 AG-UI 映射层 | 完成 | `app/agui.py` + `POST /api/ask/agui`；流式翻译，双协议共存 |
| M2.5 官方 saver 替换 | 完成 | `AsyncSqliteSaver` + `WeakKeyDictionary` 按 loop 缓存；pending 表加 TTL 清理 |

M2.3 Tasks 阻塞细节：`mcp` 1.30 把 Tasks 放在 `mcp.server.experimental`
（`TaskSupport` / `ServerTaskContext`），标 experimental；`fastmcp` 2.12 源码里
搜不到 task 实现。要落地需绕开 fastmcp 直接用 lowlevel server，风险大于收益。
fastmcp 支持后只换装饰器，业务实现不动。

## M3 财务部门模式 · 100%

| 项 | 状态 |
|---|---|
| M3.1 工单 schema | 完成：`dept_models.py` pydantic 模型（dept/status 枚举、budget_tokens、metrics） |
| M3.2 LLM 派工 | 完成：`dept_dispatch.py`，schema 校验 + 工具白名单过滤 + 失败回落规则 |
| M3.3 部门 agent | 完成：`dept_agent.py`，独立 instructions + 工具白名单 + 独立 thread_id + token 预算；模型不可用退回确定性 |
| M3.4 秘书交叉对账 | 完成核心：按结构化 metrics 比对，冲突指明部门；呈批件含结论/冲突/发现 |
| M3.5 老板呈批 HITL | 完成：`dept_reports` 表 + 三个审批端点；approve/reject/inquire，审计落 provenance |
| M3.6 部门实况看板 | 完成：`DepartmentPanel` 四工位实时状态 + 秘书台 + 审批；e2e 覆盖全流程 |

这是计划里的"核心差异化"，也是当前最大缺口。

## M4 多端 · 90%

| 项 | 状态 |
|---|---|
| M4.1 CLI | 完成：argparse（add/ls/report/balance/ask/serve）+ `dept run/list/approve/reject/inquire`，本地与远程双形态；12 项 CLI 测试 |
| M4.2 Tauri 桌面 | 脚手架就绪：`desktop/src-tauri`（tauri 2 + sidecar + updater 配置 + bundle 五目标）；产物需目标平台构建，本机未出包（见 desktop/README.md 阻塞表） |
| M4.3 发版自动化 | 完成：`scripts/release.sh` 从提交推导版本 + `release.yml` 自动建 Release |

## M5 可视化+适老 · 100%

| 项 | 状态 |
|---|---|
| M5.1 适老模式 | 完成：字号三档 + 高对比，服务端持久化，390px 无溢出 |
| M5.2 ECharts 图表 | 完成：现金流瀑布/支出树图/订阅时间线/健康五维雷达 + 部门看板 |
| M5.3 后端预聚合 | 完成：`db.month_cashflow` SQL 聚合 + `/api/dashboard` 10s TTL 缓存，10 条写路径统一失效 |
| M5.4 语音闭环 | 完成：语音输入（Web Speech）+ 语音播报（`lib/use-speech.ts`，`voice_output` 开关、朗读按钮、超长截断、代码块跳过），4 项前端测试 |
| M5.5 反事实沙盒 | 完成：`calculations/sandbox.py` 四类情景（少花/多存/改定投/一次性），`/api/strategy/sandbox`，前端 `SandboxCard`；9 项引擎 + 4 项 API 测试 |

## M6 生态+获客 · 95%

| 项 | 状态 |
|---|---|
| M6.1 审计底稿 | 完成：`GET /api/audit-report` 输出可归档 HTML |
| M6.2 挑战赛+错误台账 | 完成（软件侧）：`POST /api/eval/ledger` 把判错题沉淀进 `reflections`，`GET /api/eval/ledger` 可查；4 项测试。社区运营（Issue 模板、周报）属人工动作 |
| M6.3 模型招聘 eval | 完成：50 题题库 + 确定性判分 + `/api/eval/*` + 设置页面板 |
| M6.4 家庭议会 | 完成：`family_motions` / `family_votes` 表，法定人数 2/3 + 严格多数，状态机 voting→approved/rejected/withdrawn；`/api/family/motions*` 六个端点 + 设置页 `MotionsPanel`；8 项测试 |
| M6.5 教程三连+Registry | 完成：`docs/mcp-guide.md` 覆盖 Claude Code / Cursor / Cline 三平台；`server.json` MCP Registry manifest |
| M6.6 可复核性标准 | 完成草案：`docs/reviewability-standard.md`（五条硬性要求 + 第三方复核流程 + 诚实清单） |

## 下一步顺序

1. M4.2 Tauri 桌面壳（当前为 PyInstaller 单文件，无安装器与自动更新）
2. M5.4 TTS 语音播报与 M5.5 反事实沙盒
3. M6.5 教程三连 + MCP Registry 上架
4. 3.0.0 投资策略引擎收尾：估值分位与 FIRE 的空状态/边界用例补齐，截图与 README 同步
5. M4.2 Tauri 桌面壳（当前只有 PyInstaller 单文件，没有安装器与自动更新）

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-18 | 建立本页；M0/M1 完成，M2 达 80% |
| 2026-10-18 | M2.4 AG-UI 映射层完成，M2 达 90% |
| 2026-10-18 | M2.5 完成，M2 收官；pending 表补 TTL 清理 |
| 2026-10-19 | M3.1 工单模型 + 结构化对账 + 部门 SSE 流完成，M3 达 40% |
| 2026-10-19 | M3.2 LLM 派工 + M3.3 部门 agent 完成，M3 达 70% |
| 2026-10-19 | M3.5 呈批 HITL 完成，M3 达 85% |
| 2026-10-19 | M3.6 前端部门看板完成，M3 收官 |
| 2026-10-19 | 移动端适配：抽屉导航、动态视口、安全区、触摸目标、IME 防误发 |
| 2026-10-19 | M4.3 发版自动化 + 版本号统一到单一真源，M4 达 66% |
| 2026-10-19 | M5.2 新增 4 个图表（瀑布/树图/时间线/雷达），M5 达 55% |
| 2026-10-21 | 前端重构（2.8.0）：ChatGPT 式布局；修正本页 M4/M5 完成度与明细不一致（M4 66%、M5 60%） |
| 2026-10-21 | 界面审查（2.8.1）：财务页整页化 + 逐页截图修复 8 个真实缺陷；新增 ui-audit 截图脚本 |
| 2026-10-23 | 2.9.0–2.9.3 补记：Skill/Prompt/Plugin/知识库、富回答块、MCP 鉴权收口；测试基线 858 / 111 / 21 |
| 2026-10-23 | 3.0.0 投资策略引擎（进行中）：5 个新 agent 工具 + 5 个 MCP 工具、`/api/strategy/*`（5 条路径 / 8 个方法）、投资策略页 |
| 2026-11-06 | 4.14.0：债务清偿规划（雪崩/雪球/自定义）+ 63 个 MCP 工具；README 英文主版化；截图全集重拍 |
| 2026-11-09 | 4.15.0：全量审计，修掉 9 个「算错但不报错」的缺陷（RSI 边界反向、信号截断取到最不重要项、盈亏比符号、零余额负债幻影预算、警告码与文案不同源、日志尾部读取 500 等）；新增 37 项回归测试 |

| 2026-11-09 | 4.15.1：审计第二轮（税负 + 账单解析），修 9 处「算错但不报错」：工资实发把累计税减在单月工资上、公积金基数被社保上限压住、会计负数导入后变收入、缺方向列静默导入 0 笔、报错行号错位、0 元流水入库等；新增 40 项回归测试 |
