# Changelog

项目版本号与发布历史。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，版本语义遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [4.3.1] - 2026-10-28（Agent Studio 深度审计修复）

第二轮审计修掉 10 处真实缺陷（详见下方「修复（第二轮深度审计）」），并把设置导航重组为
五组、补导入格式示例面板、MCP 批量启停与失败可视化。后端 1053 测试、前端 111 单测、
28 条 E2E 全通过。

### 新增：Agent Studio（设置中心从「配置项」升级为「能力工坊」）

- **角色 / 技能 / 提示词 / 约束 / Hook 全部可编辑并真正运行时生效**：
  主角色指令、提示词（按优先级）、约束（must/should/may × all/finance/research）、
  pre_prompt 注入统一进入系统提示；pre_tool Hook 可拦截/告警工具调用，post_answer Hook 做审计
- **默认包非空**：8 个角色、9 个技能、4 份提示词、7 条约束、7 个 Hook、8 个内置科研工具，
  首次启动即启用；用户可关闭/删除，重启不会复活（`marketplace.seeded` 只执行一次）
- **四条添加通道**（每个分区都有）：对话内说一句、拖拽/上传（SKILL.md、md、json/yaml、zip）、
  模板手写、AI 一键生成（生成后二次校验，未接入模型时明确报错）
- **插件市场**：内置 42 个开源条目（Anthropic Skills 精选、学术论文/审稿/文献综述/引用管理/
  EDA/科研绘图、科研与工程角色、Cursor 规则、官方 MCP 参考实现 + DeepWiki/GitMCP
  + 科研 MCP（arXiv / Zotero / Paper Search）），
  一键安装；支持粘贴 GitHub/任意 URL 安装单个文件；MCP 安装只写配置、默认停用
- **权限模型**：全面放开 / 标准 / 严格三档；核心项（审批阈值下限、密钥、访问口令、
  内置工具可见性、破坏性操作确认）在任何模式都锁定，`/api/studio/core-guard` 给出拒绝理由
- **内置优势工具（不对外）**：科研大纲、引用格式化（GB/T 7714 / APA / MLA / Chicago）、
  检索式构造、CSV 数据画像、统计摘要、敏感性分析、实验设计核查、来源可信度评分；
  纯标准库、离线可用，只进内部工具面，不进 MCP 对外清单，逐个可开关
- **运行时看门狗**：每 15 分钟检查日志错误、配置完整性、MCP 状态，设置页可立即检查并展示发现项
- **CLI 对等**：`moneyhelper studio list/show/add/remove/toggle/import/market/ai`，
  与设置页共用同一存储与校验（远程模式走同一 HTTP API）
- **MCP 增强**：支持 stdio 传输（command + args）、逐台启用/停用；市场安装的 MCP 默认停用

### 修复（第二轮深度审计，均为真实缺陷）

- **内置科研工具全部不可用**：agent 执行层统一 `await impl(args)`，而 8 个内置工具是同步纯函数，
  `await` 一个 str 会抛 `TypeError: object str can't be used in 'await' expression`；
  改为包一层协程（`_make_internal_runner`），并加端到端测试（模型调用 → 工具结果含「样本量」）
- **删除的内置项会复活**：默认包补齐只看「缺不缺」，用户删掉的内置提示词/约束/Hook/角色/技能
  下次读配置又回来。改为按租户持久化墓碑（`removed` 字段），并补「删除后重建同 id」测试
- **审批阈值下限只是文案**：`core-guard` 声称下限 100 元，但改 `defaults.approval_threshold`
  仍能设成 0；`approval.threshold()` 现在钳制到 ≥100，保存配置时低于下限会被钳制并回报 warning
- **角色「工具白名单 / 温度」只存不用**：模型永远 0.2 温度、永远拿到全量工具；
  现在白名单真正裁剪工具面，温度进入模型调用参数
- **MCP 发现串行且无失败记忆**：一台离线服务器 15s 超时会串成 N×15s；改为并发 4 路 +
  失败退避 30 分钟 + 失败原因回传设置页（红灯 badge）
- **备份漏 MCP 配置**：`data/mcp.json` 不在 settings 表里，恢复后市场装的 MCP 全丢；
  export/import 增加 `mcp_servers`（URL 凭据打码）
- **CLI 与对话权限耦合**：CLI 走 chat 开关，关掉对话管理后 CLI 也被禁；改为独立通道判定
- **市场条目被标成「内置」**：导致删除时走 force 分支、语义混乱；市场安装不再标记 builtin
- **远程 MCP 默认停用不符合「默认配置好」**：远程 HTTP（deepwiki/gitmcp）改为默认启用，
  stdio 仍默认停用（依赖 npx/uvx），并加「全部启用/全部停用」
- **设置导航**：新旧两套「Agent 与技能」重复，旧页面（AgentSection/ai-generate）已删除；
  导航重组为「基础设置 / AI 与自动化 / AGENT 能力 / 数据与安全 / 评测」五组
- 死代码：`routes/studio.py::_apply_entries`、`market._SKILLS_MP`、`watchdog` 空分支、
  `default_studio.permissions.max_tool_turns`、32 个旧 Agent 页孤儿 i18n 键

### 修复（第一轮）

- 设置页新增分区原先会挤在一屏：改为左侧分组导航 + 移动端横向滚动条，14 个入口可达
- 默认角色/技能升级后老库看不到新内置项：启动时按「只补缺失、不覆盖用户改动」合并
- 技能定时动作在 Studio 侧编辑后不生效：写操作后自动 `sync_skill_jobs()`
- 打包版缺 Studio 默认包（JSON 非 Python 模块，PyInstaller 静态分析发现不了）：spec 与 pyproject 同步收录

### 变更：品牌更名 Moneyhelper

- 项目名、包名、CLI 命令、Docker 服务/数据卷、PyInstaller 产物、环境变量前缀统一为 Moneyhelper；
  旧前缀 `XIAOMAN_*` 由 `backend/app/compat_env.py` 兼容读取（新名优先），旧部署升级不会切到空库
- 仓库内所有对外品牌文案（README / docs / 页面标题 / PWA manifest / 双语 i18n）同步更名
- Logo 重绘为「M 折线 + 增长箭头」钱币标，重出 icon.svg / 192 / 512 / apple-touch-icon / app.ico
- 品牌 slogan 改为「算清每一笔，攒稳每一步」并在登录页展示；页面 theme-color / manifest 主色对齐品牌绿 `#0f8a73`
- 新增 `tests/test_brand.py`：旧品牌零残留成为可执行约束（兼容层与升级说明白名单除外）

### 修复

- `paper_trade` / `paper_overview` agent 工具因缺少 `validate_trade` / `fee_for` / `estimate` /
  `ranking` / `team_summary` 导入，调用即 `NameError`；补测试覆盖开户→下单→总览全链路
- `calculations` 门面中 `paper.build_equity_curve` 被 `portfolio_risk` 同名函数覆盖，
  两种签名互相踩；paper 版改名 `build_snapshot_curve` 显式导出
- `docs/ARCHITECTURE.md` 与 `docs/architecture.md` 仅大小写不同，Windows 克隆后互相覆盖且
  mkdocs `--strict` 失败；详版重命名为 `docs/ARCHITECTURE-detail.md`
- `docs/promo.html` 引用了 6 张不存在的截图；改为实际存在的文件
- README 的页签数量（八个 → 九个，漏列模拟盘）与代码不一致
- `frontend/package-lock.json` 版本号停留在 3.0.0，与 `package.json`/`version.py` 漂移
- 本机新版 ruff 在改名前的 v4.2 提交上检出 38 项问题（未用导入、同名重定义、5 处未定义名等）；
  v4.0–v4.2 三个提交直接推到了 GitCode，未经 GitHub CI（最后一次 CI 停在 d9837c2），因此一直没被发现
- 五端一度不同步：GitCode 有 v4.0–v4.2，GitHub 三仓与 Gitee 停在 d9837c2；本次已全部对齐
- 限流配额差一：`len(bucket) >= max` 让「200 次/分钟」实际只放行 199 次，与响应头 `X-RateLimit-Limit: 200` 矛盾
- 登录防爆破只按 `X-Forwarded-For` 取 IP，未校验来源，可伪造头绕过 IP 维度限流；
  改为默认不信任该头，仅 `MONEYHELPER_TRUST_PROXY=1`（可信反代部署）时采信，CONFIG/DEPLOY 中英文四份文档同步说明

## [4.2.0] - 2026-10-27（团队模拟盘：多成员炒股看板，事件溯源内核）

> 延续 4.0/4.1 原则：**所有数字由代码重放算出，不是模型编的**。这次把「人」引进来——
> 多成员虚拟账户、下单成交、持仓估值、团队排行、净值曲线，一套券商终端式看板。

### 新增：团队模拟盘引擎（`app/calculations/paper.py`）

**事件溯源设计**：账户只存开户参数（初始资金），持仓/现金/成本全部从交易记录**重放**得出——
无状态漂移、可审计、可单测。删除/回滚一笔交易即回到对应时点。

| 能力 | 内容 |
|---|---|
| 整手成交 | 买入按 100 股整数倍（`round_lots`），卖出可零股 |
| A股费用口径 | 佣金双边 0.025%（最低 5 元）+ 卖出印花税 0.05% |
| 加权成本 | 买入合并摊薄、卖出不变，盈亏/盈亏% 逐持仓给出 |
| 估值降级 | 缺现价时用最后成交价并标注 `stale`（默认口径，下单时前端填现价） |
| 团队汇总 | 资金加权收益率、总资产、总盈亏、活跃持仓数 |
| 排行 | 收益率降序 + 净值兜底，纯函数可复现 |

### 新增：持久化与 API（`app/db/paper.py`、`app/routes/paper.py`）

- 三表：`paper_accounts` / `paper_trades` / `paper_snapshots`（租户隔离，已注册 `_TENANT_TABLES`）
- 上限治理：每团队 12 账户、单账户 500 笔；快照按日幂等 upsert（净值曲线存档）
- 六端点：`GET/POST /api/paper/accounts`、`DELETE /api/paper/accounts/{aid}`、
  `GET /api/paper/accounts/{aid}`（估值+净值曲线+最近交易）、
  `POST /api/paper/accounts/{aid}/trades`（引擎校验→手续费→落库→当日快照）、
  `POST .../snapshot`（手动存档）
- agent/MCP 工具 ×3：`paper_open` / `paper_trade` / `paper_overview`（工具总数 34）

### 新增：前端「模拟盘」工作台（导航第 9 tab，券商终端式看板）

- **团队摘要条**：账户数 / 总资产 / 总收益 / 团队收益率 / 活跃持仓
- **排行条形图**：成员收益率横向 bar（A 股红涨绿跌、正负分色）+ 明细行（排名/资产/盈亏/持仓）
- **账户详情**：净值曲线（对 1.0 基准）+ 持仓市值 donut 饼图 + 持仓盈亏表 + 最近 20 笔交易表
- **交易表单**：买/卖切换（红买绿卖）、代码/现价/股数、整手与现金不足即时校验、佣金+印花税费用预估、成交后自动刷新净值与排行
- **开户表单**：成员名 + 初始资金（≥1000），一键入队；删除账户连同交易/快照级联清理
- 图表全部走 `useEChart` / `useCandleColors` / `usePalette` 共享基建，深色模式与红涨绿跌方案即时换色

### 验证

- 后端：引擎 19 项单测 + API 集成测试（开户→下单→排行→详情→删除全链路、400/404 分支），全量回归通过
- 前端：tsc 类型检查、vitest 111 passed、vite build 绿
- 版本 4.2.0 三处同步（`version.py` / `pyproject.toml` / `package.json`）

## [4.1.0] - 2026-10-26（投研深化：统计预测 + 财报可视化增强）

> 延续 4.0 原则：**确定性计算 + 可复核输出**，预测也交给统计引擎而非模型猜。

### 新增：价格统计预测引擎（`app/calculations/forecast.py`）

| 能力 | 内容 |
|---|---|
| 线性趋势 | 最小二乘回归外推未来 N 期（斜率方向 → 偏多/偏空/中性） |
| 波动率 | 对数收益率年化波动率（√252），区间宽度随波动率放大 |
| 蒙特卡洛 GBM | 固定种子（42）可复现，2000 条路径 → 中值 + 5%/95% 分位区间带 |
| 均值回归 | 当前价相对 20 日均线偏离 %，偏离 ≥5% 提示回归倾向 |
| 结论 | 模板化中文说明（统计情景推演 + 免责声明），无需模型 |

新增端点 `/api/research/forecast`；agent/MCP 工具 `research_forecast`（工具总数 31）。

### 新增：财报分析增强

- `trends.cashflow_stack`：经营 / 投资 / 筹资三流序列（供前端堆叠柱图与现金净增加额汇总）
- 每期原始三流随 `periods[].cashflow` 返回，多期对比可直接落表

### 前端深化（金融可视化）

- **投研页**：K 线蜡烛改 **A 股红涨绿跌**（跟随全局颜色方案，us 模式自动反转）；日/周/月周期切换；缩放重置按钮；新增「价格统计预测」面板（趋势线 + 中值 + 5%-95% 区间带 + 四项指标）；回测参数可调（双均线快/慢线、定投金额/间隔）；双均线交易回合明细表
- **财报页**：现金流三流堆叠柱图 + 现金净增加额汇总；杜邦拆解条图（三因子 × → ROE，缺因子标注）；多期指标对比明细表（14 项指标 × 各期，同比/现金流着色）
- 新增共享 hook `useCandleColors`（解析 `--color-up/--color-down`，方案切换即时换色）

### 测试与修复

- 新增 `tests/test_forecast.py`（18 项：趋势/波动率/GBM 可复现/区间带/文本）+ API 用例
- 修复 `test_secrets.py` 超时：改用 `git ls-files` 只扫代码树（语义更贴合，避开 node_modules 海量遍历）

## [4.0.0] - 2026-10-26（财务智能体工作台：投研 + 财报分析）

> 定位升级：从「能管仓位的财务部门」变成「**垂直财务智能体工作台**」——对话只是入口，
> 八个页签整页切换，每页都是「指标条 + 图表 + 明细表」的决策看板。
> 新增两个垂直引擎（投研 / 财报），延续 3.0.0 的原则：**确定性计算 + 可复核输出**。

### 新增：股票投研引擎（`app/calculations/{technical,backtest}.py`）

| 能力 | 内容 |
|---|---|
| 技术指标 | MA(5/10/20/60)、EMA、MACD(12/26/9)、RSI(14)、BOLL(20,2σ)、KDJ(9,3,3) |
| 信号合成 | 规则引擎：MA 金叉死叉 / MACD 金叉死叉 / RSI 超买超卖 / 布林突破 / KDJ 金叉死叉 / 放量，带多空倾向聚合 |
| 策略回测 | 双均线（MA5/20，含交易成本）、定投（固定间隔定额）；总收益、年化、最大回撤、夏普、胜率、盈亏比、资金曲线 vs 买入持有 |
| 行情源 | 直接复用东财 K 线层（push2his 前复权），失败降级标注原因，不 500 |

新增 REST 端点：`/api/research/{analyze,backtest,overview}`；3 个 agent/MCP 工具
（`research_analyze` / `research_backtest` / `statements_analyze`）。

### 新增：财报分析引擎（`app/calculations/financial_statements.py`）

| 能力 | 内容 |
|---|---|
| 指标 | 20+：毛利率/净利率/营业利润率/ROE/ROA、资产负债率/流动比率/速动比率/利息保障倍数、三类周转率、经营现金流/净利润、现金营收比、同比成长 |
| 杜邦拆解 | ROE = 净利率 × 总资产周转率 × 权益乘数，缺因子标注不完整 |
| 异常预警 | 规则引擎：经营现金流为负、利润含金量低、商誉占比>20%、高杠杆、流动比率<1、毛利率骤降、应收/存货异常 |
| 报告 | 模板化中文分析报告（确定性，无需模型） |
| 持久化 | 三表 JSON 落本地库（financial_statements 表，租户隔离），可重新分析/删除 |

新增 REST 端点：`/api/statements/{analyze, 保存, 列表, 详情, 删除}`。

### 新增：前端投研页 + 财报分析页（可视化差异化）

- **投研页**：现价条 → 技术指标卡 → 可缩放 K 线主图（蜡烛 + MA5/20/60 + 布林带切换，成交量副图）
  → 信号流 → 策略回测（双均线/定投切换，指标条 + 资金曲线对比）；行情不可用逐块降级
- **财报页**：三表 JSON 输入（一键载入示例）→ 四组指标卡 → 营收&净利/盈利比率/偿债/现金流趋势图
  → 五维财务雷达图 → 预警流 → 报告文本 → 本地保存与重新分析
- ECharts 按需注册新增 candlestick / dataZoom 模块；首屏包不含投研/财报代码（懒加载）

### 文档与版本

- README / README.zh 定位重写：明确「与通用智能体的区别」，对话入口 + 工作台主场
- 国产模型优先表述（DeepSeek / 豆包 / 通义 / Kimi），弱化国外平台
- 版本号 3.0.0 → 4.0.0（version.py 单一真源）

## [3.0.0] - 2026-10-24（投资策略引擎 + 可复核底稿 + 模型评测）

> 定位升级：从"会记账的助手"变成"能管仓位的财务部门"。
> 三条主线都是**确定性计算 + 可复核输出**，没有一处让模型自己算数。

### 新增：投资策略引擎（`app/calculations/{portfolio_risk,strategy,valuation}.py`）

纯标准库实现，零新增依赖。所有指标口径写进 docstring，样本不足时返回
`null` 并标注原因，绝不返回看起来合理的假数值。

| 能力 | 内容 |
|---|---|
| 组合风险 | 年化波动率、夏普、索提诺、最大回撤、Calmar、Beta/Alpha、历史模拟法 VaR(95%)、上涨天数占比、单日最佳/最差 |
| 基准对比 | 沪深300/上证/深成/创业板四条基准，净值曲线双线归一化对比，超额收益 |
| 再平衡 | 目标配置 + 容忍带（3/5/8/10%），输出买/卖金额与整手股数；A 股卖出可零股、买入必须整手 |
| 估值温度计 | 当前价在近 750 个交易日区间中的位置分位，五档分区（低位区/偏低/中枢/偏高/高位区） |
| 定投 | 月/周计划、累计投入、份额、成本线、当前盈亏、下一期扣款日；数据覆盖前的定投日不补记 |
| FIRE | 目标本金（年支出/提取率）、完成度、储蓄率、复利年限；不可达时返回 `reachable=false` 而不是一个假年限 |

新增 6 个 REST 端点（`/api/strategy/*`）、5 个 agent 工具、5 个 MCP 工具
（外部 AI 也能调用），以及前端「投资策略」页（风险指标条 + 净值曲线 +
再平衡表 + 估值色阶 + 定投表 + FIRE 进度）。

### 新增：审计底稿导出（M6.1）

`GET /api/audit-report` 把 provenance 链路渲染成可归档 HTML：每条记录带
来源徽标、操作人、before/after **只列变化字段**的差异表。浏览器内一键
打印为 PDF。输出 HTML 而不是 PDF 是为了不引入几十 MB 的渲染依赖；
所有动态内容经 `html.escape`，并附 CSP 头禁用外部资源。

### 新增：模型评测题库与判分器（M6.3）

`app/eval_bank.py` 50 道题，覆盖记账解析/预算/负债/持仓/策略/口径推理六类。
`app/model_eval.py` 用**确定性判据**打分（数值按容差、文本按关键结论），
不让 LLM 给自己打分。端点：`/api/eval/{questions,run,score,leaderboard}`。
未配置模型时明确返回未评分，不生成假成绩。

### 性能：后端预聚合（M5.3）

`/api/dashboard` 本月现金流改走 SQL `GROUP BY`（`db.month_cashflow`），
流水明细限 500 条 + 独立总数；加 10 秒 TTL 缓存（键含 DB 路径与租户），
所有写路径（记账/持仓/负债/订阅/目标/预算/设置/确认执行/对话记账）
统一失效。账本十万行时不再把整库搬进内存。

### 修复：界面口径与真实缺陷（截图审查发现，全部有回归测试）

- **持仓编辑成本价放大 100 倍**：`positions[].cost` 是总成本，编辑框要每股成本；
  新增 `cost_per_share` 字段，前端与"追加持仓"都改用它。
- **占比双口径打架**：`by_asset` 同时给 `pct`（相对总市值，合计 100%，
  供饼图与占比列）与 `investable_pct`（相对非现金，供集中度判定）；
  此前现金行也用非现金分母，导致占比列合计 126%、风险提示 50.4% 与
  集中度 63.6% 同屏并存。
- **今日盈亏恒为 +0.00%**：分母把已是总额的 `cost` 又乘了一次股数。
- **健康评分两套值（51 vs 50）**：`/api/calculations/health` 改走
  `analysis.health_check` 单一实现。
- **亏损写成"浮盈"**：文案按盈亏正负切换浮盈/浮亏。
- **总资产两个值（282,540 vs 264,884）**：`/api/calculations/net-worth`
  与健康评分都改用实时行情，与总览同源。
- **手机端**：设置项 Row 改上下堆叠（供应商选择器不再横向溢出）；
  对话上下文条改 `sticky top-0`（不再被顶栏裁切）。
- **饼图中心文字被扇区覆盖**：环孔从 0% 改为 48%。
- **命令面板**补「去投资策略」入口。
- **表格/统计格**：占比列合计归 100%；平板宽度下大数字不再断行。

### 仓库与文档

- 删除入库的 `frontend/coverage/`（48 个产物文件）与零引用的 `docs/demo/`（980KB 旧图）。
- `scripts/push-all.sh` 重写：5 目标真实可用，支持 `--dry-run`/`--only`，
  凭据只从环境读取、打码输出。
- README 补 Release/CI/Docker badge、30 秒上手、Why Moneyhelper 对比、策略页截图；
  测试数统一为真实值。
- PROGRESS 同步到 3.0.0；ROADMAP-v3 标注为历史快照；三份旧审计文档加
  「历史快照，不代表当前状态」声明并归入「质量与审计（历史）」分组。

### 验证

- 后端 **906 passed**（原 791 + 新增 115）；`ruff check app tests` 全过。
- 前端 111 单测 + tsc + vite build 全过。
- 截图审查 15 张（桌面/手机/平板/暗色/空库/降级），逐张人工核对，无
  `undefined`/`NaN`/空白/裁切。

### 说明

组合风险曲线是**按当前持仓回溯的模拟净值**，不是实盘历史成交净值；
接口用 `basis: "backtest"` 与 `basis_note` 明确标注，前端在卡片上展示该提示。

## [2.9.3] - 2026-10-23（安全与数据完整性收口）

- **MCP 侧补齐多用户 fail-closed 鉴权**：`/mcp`、`/mcp-sse` 的挂载守卫此前只校验共享口令
  与 Host/Origin，已注册用户的实例里仍可无令牌调用工具。现把主 API 的鉴权总闸
  （口令 + 有账号必须 JWT）抽取为 `middleware.auth_gate`，主 API 与 MCP 子应用共用同一套判定，
  消除"主站有防护、MCP 侧裸奔"的第二条信任边界。
- **工具入参校验真正落地**：`tool_schemas` 新增 `validate_tool_args`（`extra="forbid"` 此前
  只停留在 schema 声明、从不执行），并在三个执行边界统一接线——agent 工具循环
  （错误回填给模型 self-correct）、agent_graph action 节点（校验失败返回"失败"结果）、
  confirm 直接执行（校验失败返回 400，杜绝以空参/多参误触写工具）。
- **备份覆盖补齐**：备份/恢复此前漏掉附件、会话摘要、部门呈批件三张租户表，
  恢复后知识库、会话上下文、呈批历史会整体消失；现一并纳入导出与恢复
  （reflections / undo_records / pending_actions 为运维态数据，刻意不进备份）。
- **CSV 列映射确定性**：`generic_csv` 列名候选从 set 改为按优先级排列的元组，
  同一文件在不同进程（PYTHONHASHSEED 不同）下解析结果完全一致。
- **前端清理**：删除零引用的 `ui/tabs.tsx`（65 行，被 pill-tabs 取代）；
  `responsive-shots` 截图脚本改为先进「功能」页再点「总览」（主导航已无总览入口）。

## [2.9.2] - 2026-10-23（收尾：体检页去重 + 浏览器启动开关 + 清理）

- 体检页：下方维度卡不再重复「建议」（上方「优先处理」已列出），只保留现状描述。
- `run.py` 支持 `MONEYHELPER_NO_BROWSER=1`：自动化验证不再弹出系统浏览器；
  用户双击 exe 时仍自动打开（并把端口改为读取 `PORT`，此前硬编码 8788）。
- 清理：关闭全部开发/演示服务进程，移除 `out/` 临时截图与演示库、缓存目录。

## [2.9.1] - 2026-10-23（对话内富回答块 + 上下文条）

> 界面最后一层：让对话里的数字"能操作"，而不是只读文本。

### 富回答块（`components/chat/FinanceBlocks.tsx`）
后端一直有 `card` 事件带完整的 market / ledger / flags，但前端只画了个静态四宫格。
现在按数据的实际内容渲染三种可操作块：

- **持仓概览**：总市值 + 盈亏/收益率，列出前三大非现金持仓；
  点任一行展开该标的 60 日走势（纯 SVG，不引图表库）；底部提示超限项。
- **本月收支**：收入/支出/结余/储蓄率四指标 + 支出分类条形（按金额排序）。
- **需要注意**：风控 flags 列表，每条带「去处理」跳转到对应页面。

### 去重
同一信息此前会重复三遍（风险块 / SummaryBlock 的等级徽章 / Action 按钮）：
- 有富回答块时 `SummaryBlock` 只保留「Moneyhelper 的理解」（意图识别），不重复指标与等级。
- 有块时不再渲染 action 按钮（块内已有「查看 →」）。
- 风险块跳过集中度条目（持仓块底部已提示）。

### 上下文条
对话顶部新增一行：`本地数据 · 3 项持仓 · 2 条消息 · 更新于 16:59`。
没有它，回答里的数字缺少可信度锚点，用户不知道助手看的是哪份数据、多久之前。

### 验证
- 前端 111 单测 + 21 e2e 通过；后端 786 通过；
- 截图确认：持仓块可展开走势、收支块分类条形、风险块跳转、上下文条按实际数据渲染。

## [2.9.0] - 2026-10-23（补齐 Skill / Prompt / Plugin / 知识库 + Agent harness 加固）

> 按「设置里该有的四类能力」逐项核对：Skill 已有、Prompt 只读、Plugin 缺失、知识库缺失。
> 补完后 Agent harness 的三个缺口（循环、输出上限、重试）也一并补上。

### 四类能力盘点与补齐

| 能力 | 补齐前 | 现在 |
|---|---|---|
| Skill | 4 个内置 + 自定义可增删、可绑定时 | 不变（已完备） |
| Prompt | `agents/<name>/instructions.md` 文件驱动，**设置页不能改** | 新增「系统提示词」分区：可视化编辑、留空回落默认、4000 字上限、即时生效 |
| Plugin | **缺失**：外部 MCP 服务器只能手改 `backend/data/mcp.json`，格式错一处整份失效 | 新增「插件（MCP）」分区：增删、测试连接、显示已发现工具；URL 凭据打码；写工具仍被禁止 |
| 知识库 | **缺失**：附件只能附在单条消息上，不参与检索 | 新增「知识库」分区：上传文档→切片→BM25 检索→注入 system 消息；可逐个开关、删除 |

### 知识库实现（`app/knowledge.py`）
- 切片：段落优先 + 长段落带重叠滑窗（400 字 / 80 字重叠），避免把句子切断。
- 检索：复用 rank-bm25（与长期记忆同一套中文双字+单字分词），只保留 score > 0 的命中。
- 注入：拼成带文件名的片段，2400 字预算内按得分顺序截断。
- 开关：`knowledge_enabled`（默认 on），关闭后完全不检索。
- 为什么不上向量库：与「本地优先、零外网」冲突（embedding 需外部 API 或几百 MB 本地模型）；
  接口按 retriever 设计，将来换向量实现只需替换 `rank_chunks`。

### Agent harness 加固
- **工具循环检测**：连续 3 次用相同参数调同一工具时中断并告知模型「结果不会变化」。
  此前只有 turn_cap 兜底，要烧满 5 轮才停。
- **输出上限**：工具循环的模型调用补 `max_tokens=2048`，防超长生成拖到超时。
- **重试与超时**：非流式调用补 `num_retries=2` + `timeout=60`（与流式路径对齐）。

### 验证
- 后端 786 通过（新增：MCP 管理 8、知识库纯函数 9、知识库接线 3、循环保护 6）。
- 知识库接线测试断言「入库文档的原文确实出现在 system 消息里」，非入库文档不出现。
- 前端 111 单测 + 21 e2e 通过；设置页 16 个分区逐页截图无报错。

## [2.8.6] - 2026-10-23（修复 Windows exe 启动闪退）

- **Windows exe 双击闪退（Critical，CI 实测复现）**：`run.py` 打印中文横幅时，
  Windows 控制台默认编码是 cp936/cp1252，`UnicodeEncodeError: 'charmap' codec can't
  encode characters` → 未捕获异常 → 进程退出。现在启动时把 stdout/stderr 切成 UTF-8
  并带 `errors="replace"` 兜底。
- 移除 spec 里无效的 `croniter` hidden import（项目未使用该依赖，PyInstaller 报
  `Hidden import 'croniter' not found`，在 CI 中只是警告，但会干扰真实错误定位）。

## [2.8.5] - 2026-10-23（设置页使用逻辑修复）

> 逐个分区走查设置页，修的都是"用户会踩到但不会报错"的逻辑问题。

- **未保存改动静默丢失**：改完设置点「关闭」直接丢弃修改，没有任何提示。
  现在关闭前弹确认（放弃并关闭 / 继续编辑）。
- **访问口令页自相矛盾**：输入框说明"后端 API_TOKEN 相同时才生效"，下面又说
  "未设置时无需口令"，用户填完无从判断是否生效。现在 `/api/health` 返回
  `auth_mode`（token / accounts / local），页面顶部直接显示当前实例的真实鉴权模式，
  并区分「需要口令 / 已启用账号体系 / 本机免登录」三种情况下的操作指引。
- **默认配置只读且无指引**：「Agent 与技能」底部展示默认语言/模型/审批阈值/工具轮次，
  用户看到数值却不知道去哪改。现在每项下方标注实际修改位置。
- **危险操作无区分**：「清空全部历史」与普通按钮同样式。改为危险色描边，
  并把「备份与恢复」独立成段，与危险操作分开。
- 「恢复」按钮文案改为「加载示例数据」，明确它做的是覆盖式载入演示数据。
- 设置页内容区放宽（max-w-5xl → 6xl 并改为 flex 布局），1440 下不再出现右侧大片空白。

### 验证

- 后端 760 通过（新增 3 项 auth_mode 回归）；前端 111 单测 + 21 e2e 通过。
- 设置页 13 个分区逐页截图 + 无 console/page error。

## [2.8.4] - 2026-10-22（设置页左右分段导航 + EXE 图标/版本信息）

### 界面

- **设置页改为真正的左右分段导航**：桌面左侧固定导航栏（三组：基础设置 / AI 与自动化 /
  数据与安全），右侧内容区独立滚动；手机端改为顶部横向分段条（一次一段，单次点击到达），
  替代原先需要两次点击的两层折叠。
- 分段控件与标签在 390px 下不再被挤压换行。

### 打包

- `moneyhelper.exe` 嵌入图标（`backend/app.ico`，7 个尺寸）与版本资源
  （FileVersion / ProductName / FileDescription 来自 `version.py` 单一真源）。
- 实测：`FileVersion 2.8.3`、`ProductName Moneyhelper`，运行首页 200 / API 正常 / MCP 正常。

## [2.8.3] - 2026-10-22（安全审计 + 全维度审查修复 + README 重做）

> 一次产品级审查：安全、可靠性、性能、可维护性、测试有效性、竞品对标。
> 所有发现均附复现路径；修复项均有回归测试。

### 安全（Critical / High）

- **认证绕过（Critical）**：`api_auth` 只在设置了 `API_TOKEN` 时校验，未设置就完全放行；
  租户由 JWT 解析、失败一律归默认租户 0。结果是注册了用户的实例，任何人无令牌即可
  `GET /api/dashboard`、`GET /api/export` 读到全部账本。已复现（返回 200 + 数据）。
  修复：库中已有账号时强制 JWT（共享口令除外），无用户时保持本机免登录。fail-closed。
  回归：`test_no_token_rejected_once_users_exist` + `test_no_token_allowed_when_no_users`。
- **MCP 工具绕过写保护（High）**：模型可见工具已排除写操作，但 `mcp__` 前缀走
  `resolve_mcp_tool` 分支，不受 `WRITE_EXCLUDED` 约束——外部 MCP 服务器若暴露
  记账/下单能力，模型可绕过确定性写分支直接调用。修复：MCP 工具按去前缀后的名字
  比对禁止清单。回归：`test_agent_mcp_guard.py`（9 项）。
- **限流可绕过（Medium）**：限流按 `client.host` 原始字符串建桶，双栈监听下
  `127.0.0.1` 与 `::1` 各拿一份配额。修复：`_normalize_ip` 归一化回环写法。
  回归：`test_rate_limit_ip.py`（6 项）。
- **ECharts XSS（Moderate，GHSA-fgmj-fm8m-jvvx）**：`npm audit` 实测存在，
  升级 echarts 5.5 → 6.1.0，复测 0 vulnerabilities，页面渲染回归通过。

### 界面缺陷（实测发现并修复）

- **图表整块空白（High）**：`useEChart` 的初始化副作用在组件提前 `return null` 时
  跑过一次、`ref` 为 null 就退出；数据到达后容器才出现，但再也不会初始化。
  健康五维雷达、现金流瀑布、支出结构、订阅时间线四个卡片全部受影响。
  修复：deps 变化时若容器存在但实例不存在，补一次 init。
- **订阅时间线不可读**：用气泡大小表达金额，¥2,034 被放大到占半张图、¥18 小到看不见。
  改为横向条形图（长度编码金额），并标出扣款日。
- **命令面板被裁切**：面板高度未随视口约束，最后两个分组被截断；Esc 也无法关闭。
  改为 `max-h: calc(100dvh - 16vh)` + 内部滚动 + Esc 关闭。
- **行情列表每行一条 404**：场外基金（如 110011）没有 K 线，前端仍逐行请求。
  改为按后端同一套规则预判，跳过不支持 K 线的标的。
- **净资产卡布局松散**：环图与明细分列两端、数值贴最右。改为整体限宽 + 固定数值列。
- **持仓页右栏留白**：补「风险提示」卡（直接列出后端算好的 flags）。

### 测试与文档

- 后端 757 通过（新增 17 项回归）；前端 111 单测 + 21 e2e 通过。
- 覆盖率实测：后端行覆盖 81.51%（9388 语句）；前端 53.55%（含未被单测覆盖的 UI 组件）。
- `docs/screenshots/` 全部重拍（旧图是两代之前的界面，与当前 UI 不一致）；
  README 中英双版重写「界面」章节与截图矩阵。
- 新增 `frontend/scripts/readme-shots.mjs`（README 展示图）与 `ui-audit.mjs`（全界面审查截图）。

## [2.8.2] - 2026-10-22（对标股票软件重做三个数据页 + EXE 实打包）

> 用户反馈"界面参考 codex/qoder/zcode、工作台软件和股票软件"，并追问是否打包了 exe。

### 三页重做（借鉴股票/证券软件的信息组织）
- **持仓页**：摘要条 → 集中度超限提示条 → 左「明细表格 + 盈亏贡献条形图」/ 右「集中度 + 行业分布」双栏。
  新增 `PositionContributionCard`：按盈亏绝对值排序的横向条形图，回答"这些钱是哪几只赚/亏出来的"。
- **行情页**：改为股票软件式「列表 + 详情」双栏。左侧自选/持仓表新增「近 60 日」迷你走势列
  （纯 SVG `MiniSparkline`，不引图表库）；右侧 `MarketDetail` 显示选中标的的走势、区间涨跌、
  60 日高/低，并可展开 K 线。
- **记账页**：流水从"日期独占一行"的两行结构改为标准单行表格（日期 / 条目 / 分类 / 金额 / 操作），
  11 条流水一屏看完；去掉固定 320px 内滚动（最后一行会被切一半）。
- **体检页**：评分卡改为「评分 + 状态计数 + 五维进度条」，右侧放结论与「优先处理」清单；
  下方维度卡改两列并补上建议文案（原来 4 张卡在 3 列网格里空一格，且只显示原始 `warn`/`bad`）。
- **总览页净资产卡**：环图与右侧明细两列对齐，环形中心显示资产合计；去掉重复的图表内图例。

### EXE 打包
- 实际执行 `pyinstaller moneyhelper.spec` 产出 **`backend/dist/moneyhelper.exe`（约 150MB）**，
  并实机运行验证：首页 200、`/api/health` 正常、`/mcp` 正常（406 为缺少 Accept 头的规范行为）。
- 说明：此前仓库只有打包脚本、从未真正产出过 exe。本次验证了完整链路。

### 行情可用性修复
- **K 线在部分网络下永远取不到**：`push2his.eastmoney.com` 的 HTTPS 握手会被中间设备重置
  （curl 正常、httpx 被断），但同路径 HTTP 端点可用。`_fetch_kline` 增加 HTTP 回退。

### 验证
- 后端 pytest 741 通过；ruff 通过。
- 前端 tsc 通过；vitest 111 通过；Playwright e2e 21 通过；vite build 通过。
- 桌面/手机/平板 + 亮色/暗色全量截图复核，无 pageerror。

## [2.8.1] - 2026-10-21（界面审查修复：整页财务工作区 + 8 个真实缺陷）

> 逐页截图审查（对话 / 财务五页 / 设置十三区 / 记账五面板 / 弹窗 / 手机 / 平板 / 暗色 / 空库），
> 每个界面都实际点开验证，发现的问题按"影响用户"排序修复。

### 布局：数据页从侧栏抽屉改为整页工作区
- 总览/持仓/行情/记账/体检此前塞在 440px 右侧抽屉里，表格被挤成两列、金额折行。
  改为**整页切换**（左侧导航保持不动，主区按 1200px 居中），对标 opencode / codex 的 section 导航。
- 顶部用页签切换五个子页，当前项下划线高亮；右上「返回问答」回对话。
- 删除 `DataModal.tsx`，新增 `FinancePage.tsx` / `HealthPage.tsx`。

### 修复的真实缺陷
- **命令面板完全错乱**：`cmd-item` 类名没有任何 CSS 定义，所有命令退化成竖排裸文本。
  补齐条目/分组/选中态样式（`index.css`）。
- **命令面板 Esc 关不掉**：只监听了 Ctrl+K，按 Esc 无反应，面板会卡住整屏。
- **K 线弹窗永远空白**：`useEChart` 的初始化副作用在面板关闭时就跑完，ref 还是 null，
  之后再打开不会重新初始化。把图表拆成只在打开后挂载的子组件。
- **行情搜索永远返回空**：东财 suggest 的响应是顶层 `QuotationCodeTable`，
  代码却读 `body["data"]`，所以搜什么都"没找到"。修正解析并抽出可测试的 `_parse_suggest`。
- **「这个月的开销怎么样」被判成闲聊**：`LEDGER_WORDS` 只收「支出」，
  口语「开销/开支/花费」全部漏掉，回答回落成"未接入模型"文案。补词并加回归测试。
- **财务快照卡显示无意义的「—」**：问持仓时后端只查 market，卡片仍渲染 ledger 字段。
  改为按实际拿到的数据渲染格子，展开按钮也指向对应页面。
- **新对话在侧栏留空会话**：每点一次「新对话」就立刻在库里建一条"新会话"。
  改为只切本地临时线程，首条消息发出后才真正建会话（对齐 ChatGPT）。
- **点「新对话」后界面停在旧会话**：先设临时线程再等接口返回，切换滞后。
- **审计日志/日志页被 asyncio DEBUG 刷屏**：Windows 的 Proactor 每建一个事件循环打一行，
  把真告警挤出屏幕。压到 WARNING，并给日志页加「只看问题 / 全部」切换。
- **体检空库显示 0 分**：数据不足时后端返回 score=0 且无维度，界面显示红字 0 分 + 三个空徽章，
  像是体检失败。改为引导态。
- **空库首屏文案**：标题从「我是 Moneyhelper」改为统一的「问你的钱，这里都有答案」，
  副标题按有无数据切换引导语。

### 其他一致性
- 行情自选/持仓列表改为对齐的表格（标的 / 现价 / 涨跌幅 / 操作），移动端退回两行卡片。
- 记账流水改成真正的四列表格行（日期分组头 + 条目 / 分类 / 金额 / 操作），移动端不再重复日期。
- 移动端底部导航「总览」改名「财务」（该入口覆盖五个子页），财务子页也高亮。
- 财务页顶栏保留移动端菜单按钮（原先后返回按钮把菜单挤掉了）。
- 设置页分段控件在 320–390px 不再把「标准/大/特大」压成竖排。
- 体检页评分卡改为评分 + 状态计数 + 五维卡片（原来直接显示 `warn` / `bad` 原始枚举）。
- 新增 `frontend/scripts/ui-audit.mjs`：一条命令拍完桌面/手机/平板所有页面与弹窗。

### 验证
- 后端 pytest 741 通过（新增 4 项：搜索解析 2、口语路由 1、空查询 1）；ruff 通过。
- 前端 tsc 通过；vitest 111 通过；Playwright e2e 21 通过；vite build 通过。
- `ui-audit.mjs` 全量跑完：无 pageerror、无 console error。

## [2.8.0] - 2026-10-21（前端重构：对齐 ChatGPT 的对话界面范式）

> 用户反馈"前端拉垮、不要自己乱做"。本轮不发明设计，按 ChatGPT 已验证的界面结构重排。

### 布局
- 侧栏改为浅灰底（`--sidebar`），主区纯白：只有发送键/焦点态保留品牌绿，交互底色一律中性灰，
  不再整屏泛绿。
- 侧栏结构对齐 ChatGPT：品牌（名称+标语）→「新对话」→ 搜索 → 今天/过去 7 天/更早 分组 →
  底部功能入口（总览/定时产出/财务部门/晨报/设置）。会话项悬停才出重命名/删除。
- 顶栏压成 48px 无分割线工具条：移动端导航 + 品牌，右侧仅语言/明暗/设置三个弱化图标。
- 对话列固定 `48rem` 居中；用户消息改为中性灰圆角气泡（原为绿色），助手消息无容器、
  左侧品牌头像 + 可读宽度正文。
- 空态：品牌标记 + 一句话标题 + 4 个带图标的建议卡（有账本数据时用后端按真实数据生成的建议）。
- 输入器改为 ChatGPT 式圆角容器：附件、文本域、语音、发送同处一框，聚焦时整块抬起。
- 助手操作条（复制/重新生成/下载）移到回答下方，悬停显示。
- 移除右侧常驻 Agent 面板：计划与工具调用在回答内已有内联展示，侧栏只会挤压对话。

### 排版与细节
- 新增 `.md-body` 排版规范：16px / 1.75 行高、标题层级、列表缩进、表格与引用块边界，
  Markdown 回答的阅读密度对齐 ChatGPT。
- 新建会话改为立即切到临时线程（此前会先停在旧会话，需等接口返回才切换）。
- 设置页改为独立全屏页：顶部标题 + 关闭，内容区居中 `max-w-5xl`；桌面侧栏去掉卡片描边。
- 移动抽屉背景统一为侧栏灰，去掉与内容区不一致的卡片白。
- 助手显示名与首屏标题随界面语言切换（英文 Moneyhelper / 中文 Moneyhelper）。
- 删除 `ChatHeader.tsx`、`AgentPanel.tsx` 两个不再使用的组件与相关文案。

### 验证
- `tsc --noEmit` 通过；vitest 111 通过；Playwright e2e 21 通过；`vite build` 通过。
- 1440×900 / 1024×768 / 768×1024 / 390×844 四档截图复核，横向溢出均为 0。

## [2.7.1] - 2026-10-21（专家评审 9 个 P0 全部修复）

> 独立专家评审给出 19/50 打回，逐条修复后复验。

### P0（数据安全 / 功能不可用）

- **迁移备份在 WAL 下是空文件**：`shutil.copy2` 只复制主文件，已提交数据可能全在 `-wal`。
  改用 `sqlite3.Connection.backup()` 生成一致性快照；**备份失败直接中止迁移**（不再"留痕继续"）。
- **迁移非原子**：重建表（DROP+RENAME）无事务，崩溃即永久卡死。整个迁移包进
  `BEGIN IMMEDIATE ... COMMIT`，并新增 `_recover_stale_temp_tables()` 启动清理/恢复遗留临时表。
- **半迁移库永远修不好**：判据从"列是否存在"改为**主键形状**（PRAGMA），
  有 user_id 但主键仍是单列的库能被识别并重建。
- **注册接口必然 500**：passlib 1.7.4 读 `bcrypt.__about__`（bcrypt 5 已移除）导致哈希抛错。
  改为直接用 `bcrypt.hashpw/checkpw`；另修 `_ensure_secret()`（未跑 lifespan 时 JWT secret 为空）。
- **reset 抹掉全实例账本**：`DELETE FROM {t}` 无 WHERE。现在只清当前租户；
  已有用户时未登录调用返回 401。
- **settings / budgets / members 未隔离**：settings 主键改 `(user_id,key)`、
  budgets 改 `(user_id,month,category)`、members 加 `user_id` + `UNIQUE(user_id,username)`；
  `_COMPOSITE_MULTI` 负责旧库重建。
- **备份恢复丢流水**：恢复顺序改为 members → member_loans → transactions；
  `_restore_table` 不再静默 `continue`，失败即抛错整体回滚。
- **编辑 / 合并流水必报错**：多租户改造时补了 SQL 的 `user_id=?` 却漏传实参（6 处）。
- **审计写入提交他人事务**：`add_audit_log` 改为 SAVEPOINT 隔离（与 provenance 一致）。

### 其他

- **CLI 跨事件循环卡死**：读连接池与写连接都绑定事件循环，同一进程连续调用 `asyncio.run`
  会永久等待。读池加 `set_read_pool(False)`（CLI 禁用）、`init_db`/`_read_conn` 检测 loop
  归属、`close_db` 先回滚再带超时关闭；读池的 `mode=ro` 改 `PRAGMA query_only`（WAL 下
  mode=ro 会等写连接 checkpoint）。

### 回归测试

- 新增 `backend/tests/test_p0_regressions.py`（14 项），每条 P0 至少一个用例。
- 全量 737 passed；ruff / tsc / vitest 111 / e2e 21 / mkdocs strict 全绿。

## [2.7.0] - 2026-10-21（可安装性修复 + 多平台产物 + MCP 定时产出）

### 修复（可安装性，实测驱动）

- **`pip install` 出来的包根本跑不起来**：wheel 只含 5 个门面文件（15KB），
  真正的实现在 `backend/app` 下没有被打包；装完 `import moneyhelper.server`
  直接 `ModuleNotFoundError: app`。现配置 `package-dir` 同时安装 `app.*`，
  wheel 变为 320KB / 102 个文件；实测从 `C:/Windows` 目录导入成功、
  `moneyhelper.server.app` 是真实 FastAPI 实例、CLI `--help` 正常。
- **`pyproject.toml` 依赖漂移**：仍引用已删除的 mem0 / chromadb / opentelemetry /
  langchain-litellm，且 `moneyhelper.mcp` 未纳入包列表。已与 requirements 对齐。

### 新增

- **多平台桌面构建工作流** `.github/workflows/desktop.yml`：Windows / macOS / Linux
  三平台矩阵，各自打 PyInstaller 单文件，带"产物能启动并响应健康检查"的冒烟测试，
  tag 触发时自动附加到 Release。
- **MCP 定时产出资源**（Tasks 的可行替代）：
  - `moneyhelper://scheduled-outputs` —— 最近 10 条晨报/技能产出
  - `moneyhelper://scheduler-status` —— 调度状态
  为什么不用 Tasks：mcp 1.30 的 Tasks 仍是 experimental，fastmcp 2.x 未透传；
  而"客户端能拿到定时产出"用 resource 拉取即可满足，服务端仍由 APScheduler 生成。


### 修复（并行稳定性，根因）

- **审计写入破坏事务边界**：`provenance._persist_entry` 原先复用全局唯一写连接并
  `commit`，会把别的协程未完成的多语句事务一并提交。改为在同一连接上用
  `SAVEPOINT` 局部隔离——既不提交外层事务，也不因独立连接在 Windows 上与主连接
  互等而死锁（两种更简单的做法都实测失败过）。
- **进程级活跃成员状态跨用例泄漏**：`_active_member_id` 是模块级全局字典，
  某用例设置后未清理，会让后续用例把流水挂到"别的库里的成员 id"上，
  触发 `FOREIGN KEY constraint failed`。`temp_db` 与 `test_evaluate` 的
  fixture 现在逐用例清零。修复后连续 8 轮并行回归 723 项全绿（此前约每 5–8 轮
  偶发一次）。

### 验证

- 文档站静态校验：`mkdocs.yml` 的 16 个导航条目全部存在，全仓库文档相对链接 0 坏链
  （本机无法访问 pypi，装不了 mkdocs，故用静态校验替代 `mkdocs build --strict`）。

## [2.6.1] - 2026-10-21（流式断流不再伪装成功）

### 修复

- **半截回答被当成完整结果**：`apiStream` 原先只要收到过任意一帧就把连接关闭当作成功
  （`if (got) return`），断流时用户看到的是一段看似完整的文字，实际缺后半段。
  现在以服务端 `done` 终帧作为完成标志；已收到内容但未收到终帧时如实抛错。
- **错误时隐藏已收到的内容**：`ChatMessageBubble` 原先只要有 error 就整块替换成报错行，
  用户刚看到的文字会消失。现在有正文时保留内容，另起一行提示"回答可能不完整"。

### 测试

- 新增 e2e：拦截 `/api/ask` 只发两帧文本后关闭，断言页面既显示已收到的文字、
  也显示不完整提示。这条用例是驱动上述修复的回归护栏。

## [2.6.0] - 2026-10-21（测试真实性整改 + 权限模型 + 适老化 + 桌面端）

### 测试真实性（重点）

审计发现"看起来有测试、实际没验证"的情况，已整改：

- **`test_dept_agent.py` 的 7 个用例 mock 掉了 `agent.run_agent` 本身**，只验证
  "参数被传下去了"，真正的工具循环/参数解析/结果回填从未执行。新增
  `test_agent_real_loop.py`（6 项）：只桩模型 I/O 边界，让 agent 循环与工具实现
  真实跑起来，断言"工具被真实执行、结果被回填、账本确实变了、写工具不可见"。
- **删除 `ImportPanel.tsx` 及其 3 个假测试**：该组件与 `EntryView` 内的同名实现
  重复，实际是死代码；三条用例都在断言"渲染不报错"，其中一条与另一条完全重复。
- **补强 `test_evaluate`**：原先只断言 200，现验证返回结构（month/refreshed_at/
  summary/items）与每条评估项的字段契约。
- 新增语音 hook 测试 5 项（真实分支：不支持时的提示、识别结果写回、停止复位、语言跟随）。
- 迁移类测试加 `xdist_group` 隔离（会切换全局 DB_PATH，必须与其它用例串行）；
  连续 6 轮并行回归稳定在 721 项。

### 权限模型（方案 B）

对比三种方案后选择"严格隔离 + 管理员只读概览"：
- 每个登录用户只能读写自己的租户数据（角色不能越权读明细，有测试证明）。
- 管理员新增两个端点：`/api/auth/users`（账号列表）、`/api/auth/tenants-overview`
  （各租户**条数**概览）。**只给规模，不给金额/名称/流水**——管理员需要知道
  "多少人在用"，不需要知道"张三花了多少钱"；家庭共享由 members 机制承载。
- 非管理员 403、未登录 401，均有测试。

### 适老化

- 新增设置项 `text_scale`（标准/大/特大）与 `high_contrast`，通过根元素
  `data-*` 驱动全局 CSS：字号基准 16 → 18/20px，高对比加深文字与边框。
- 实测：手机宽度（390px）切到特大 + 高对比后仍无横向溢出。
- 语音识别语言改为跟随界面语言（此前硬编码 zh-CN，英文界面也用中文识别）。

### 桌面端（M4）

- 重写 `moneyhelper.spec`：清掉已删除的 mem0/chromadb/alembic/opentelemetry 引用，
  用文件系统递归收集 litellm 子模块 + 整目录收集其非 Python 资源
  （模型价格表、tokenizer）——缺任一项启动即失败，实测踩过。
- `run.py` 修数据目录：打包后默认 `~/.moneyhelper`（此前文档这么写但代码没做）。
- 实测产出 144MB 单文件，启动后健康检查 200、前端完整渲染、写入落盘、MCP 200。

## [2.5.0] - 2026-10-20（家庭账本上界面 + 升级路径实证）

### 新增

- **家庭账本界面**（设置 → 家庭账本）：成员增删、成员间借贷（记录/结清/删除）、
  家庭收支汇总与各成员占比。这套后端能力（12 个端点）此前完全没有前端入口。
- **升级演练脚本** `backend/scripts/upgrade_drill.py`：用旧版 schema 造一个带数据的库，
  再用当前代码打开，验证 12 张表数据完整、复合主键共存、重复启动幂等、旧路径自动搬迁。
- e2e 新增家庭账本全流程（添加成员 → 汇总 → 借贷 → 结清）。

### 安全

- **迁移前自动整库备份**：多租户迁移会重建四张表（DROP + RENAME，无回滚点），
  现在动结构前先复制一份 `<db>.pre-mt-<时间戳>`。备份失败只告警不阻断，但一定留痕。
- 迁移幂等有测试兜底：已迁移的库再次启动不会再产生备份。

### 验证

- 升级演练 ALL PASSED（旧库 12 张表 → 迁移后条数一致）。
- 迁移备份实测：`.pre-mt-*` 文件内容为迁移前状态（无 user_id、数据完整）。

## [2.4.3] - 2026-10-20（溯源链上界面）

### 新增

- **溯源链界面**（设置 → 数据与安全 → 溯源链）：把后端已有的 `/api/provenance` 接到前端。
  可按实体类型与 ID 过滤，逐条展开查看改动前/后快照，回答"这个数字是谁在什么时候改的"。
  此前该能力只有接口、界面上完全看不到——而这正是产品宣称的"数字可对质"卖点。
- 接口测试 2 项：写入产生溯源记录、按类型过滤、单条详情 404。

## [2.4.2] - 2026-10-20（Docker 数据持久化修复 + 实测验证）

### 修复（P0）

- **容器重建丢账本**：代码默认把库写在 `backend/app/data`，而 Dockerfile 的 VOLUME 与
  compose 挂的是 `backend/data`。实测确认：容器内写入的数据落在卷外，`docker rm` 即丢。
  现在库 / 备份 / LangGraph checkpoint 统一由 `MONEYHELPER_DATA_DIR` 决定（默认 `backend/data`），
  镜像内置 `/app/backend/data`，与数据卷一致。
- **旧数据自动迁移**：升级后首次启动若新位置无库、旧位置有库，自动搬移（连带 `-wal` / `-shm`，
  避免 WAL 中已提交事务丢失）。显式设置 `MONEYHELPER_DB_PATH` 时不猜。
- **备份与 checkpoint 同目录**：`BACKUP_DIR` 与 `agent_checkpoints.db` 一并跟随数据目录，
  不再散落在代码目录里。

### 验证（本轮实际执行）

- Docker 实机构建 + 运行：健康检查 `healthy`、首页 200、`/mcp` 200、以 uid 1000 非 root 运行。
- 容器写入数据 → `docker rm` → 重建 → 数据仍在（此前会丢）。
- 部门工单白名单补端到端测试：模型实际收到的工具面被收窄到工单声明的那一个。

### 文档

- `docs/planning/` 九份规划文档统一加「归档说明」：标明记录的是当时决策过程，
  当前状态以 PROGRESS 与代码为准（文中 mem0/规则引擎/react_agent 等已移除）。
- PROGRESS 里程碑校准：M2 95%、M3 100%（白名单已生效）、M4 60%（Docker 已验证）。

## [2.4.1] - 2026-10-20（关键端点测试补全 + 性能与超时）

### 新增

- **关键端点 HTTP 测试**（10 项）：`/api/confirm` 的一次性 token 语义（重复确认必须 409、写操作只发生一次）、附件上传/删除/类型校验、审计与日志列表。

### 修复

- **收尾请求不再拖死整次问答**：工具轮次用尽后本应基于已有结果成文，但此前该请求无超时预算，网关抖动时会挂到 120s。现收紧到 20s（外层 25s 兜底），超时立即走确定性模板——实测网关 504 时 1.1 秒内给出降级回答。
- **LLM 客户端指纹包含 api_key**：此前只比对模型名与端点，用户在设置页换密钥后仍复用旧 client，表现为"改了 key 仍 401，重启才好"。现用密钥哈希前 8 位参与指纹。

### 性能

- **MCP 工具发现加 30s 缓存**：每次问答都重新握手并 list_tools，实测拉长首 token 时间。缓存键包含配置指纹，换配置立即失效。

### 清理

- 删除与 `manifest.webmanifest` 逐字节相同的 `manifest.json`，同步更新 Service Worker 预缓存清单。

## [2.4.0] - 2026-10-20（完整多租户 + 遗留缺陷收口）

> 定位：一个实例支持多个独立账本，且历史数据可平滑升级。

### 新增

- **完整多租户隔离**：业务表新增 `user_id` 维度，JWT 登录用户各自拥有独立数据。
  - 四类"业务字段作主键"的表（持仓 `symbol`、订阅/负债/目标 `name`、自选 `symbol`）改为 `(user_id, 原主键)` 复合主键——两人都持有「茅台」或都有「买房」目标时不再互相覆盖。
  - `sessions.thread_id` 的全局唯一约束改为 `(user_id, thread_id)`；`conversation_summary` 同理。
  - 所有读写按请求上下文中的租户过滤（`app/db/tenant.py` 的 ContextVar），未登录请求落在默认租户 0。
  - 备份/恢复按租户隔离：恢复只清当前用户的数据，绝不抹掉别人的账本。
  - 自动迁移：启动时检测旧库并就地升级（补列、重建复合主键表、回填历史数据到默认租户），幂等可重跑。
- **租户覆盖护栏**：`backend/scripts/check_tenant_coverage.py` 静态扫描数据层 SQL，任何漏加 `user_id` 的查询都会报错；确需跨租户的维护操作须显式标注 `# tenant: allow`。
- **隔离测试**：数据层 7 项 + HTTP 端到端 4 项（两个 JWT 用户的持仓/流水/目标互不可见）。

### 修复

- **健康分统一口径**：`analysis.health_check` 改用五维加权（与 `calculations/health.py` 一致），并补上 `grade` 字段（呈批件此前一直显示"得分 X（—）"）。
- **部门工单白名单生效**：执行阶段按 `order.tools_allowed` 收窄工具面，LLM 派工的"只给两个工具"约束不再是空话。
- **MCP 清仓接入审批**：`shares=0`（清仓）此前算成 0 元永不触发审批，现按持仓市值兜底，清仓这种最不可逆的操作必须确认。
- **测试并行稳定**：`test_evaluate` 的临时库 fixture 未先关闭旧连接，共享默认库时会串数据；补 `close_db()`。
- **测试 JWT 密钥固定**：避免每次导入生成随机 secret 导致同轮测试签发/校验不一致。

## [2.3.0] - 2026-10-20（可用性总修：工具链路、部署、响应式、跨平台）

> 定位：把"能跑"变成"跑对"。本轮以实际运行验证为准，修复了会让核心能力整体失效的缺陷。

### 修复（P0）

- **工具调用整体失效**：LiteLLM 1.106 在带 `tools` 时会导入其内置 MCP 网关，该模块依赖 mcp>=2 才有的 `CacheableResult`，而项目锁定 mcp 1.30（fastmcp 2.x 要求 <2.0）。表现为任何 function calling 直接 ImportError，模型永远拿不到工具。现在显式传 `_skip_mcp_handler=True` 绕开这条未使用的分支。
- **前端静态托管被遮蔽**：MCP 子应用曾 `Mount("/")`，拦截所有未匹配请求，单端口部署时 `/` 与 `/index.html` 返回 503。改为只挂 `/mcp`，并新增精确路径路由，使 `/mcp` 与 `/mcp/` 都直达（不再 307）。
- **`/mcp` 鉴权与来源校验**：改为复用主应用同一套判定（口令 + 本机/内网来源 + Host/Origin 白名单），消除"主站有防护、MCP 侧裸奔"的第二信任边界。
- **MCP 批量导入 100% 失败**：`mcp_server.py` 中 `from ..csvimport` 越界相对导入，改为 `from .csvimport`。
- **设置页无法保存**：`saveMutate` 从未被调用，月收入/应急目标/储蓄率/晨报时间只改本地 state。新增底部保存栏（含未保存提示与放弃改动）。
- **首屏 hooks 顺序违规**：`App.tsx` 在部分 hooks 之间条件 return 登录页，已注册实例且无 token 时会白屏。条件 return 移到全部 hooks 之后。
- **依赖不可解**：`langgraph` 与 `langchain-core<0.4` 约束互斥；移除重复的 `react_agent`（官方 ReAct 包装）后统一走 `agent.run_agent`，依赖树恢复可解。
- **Docker 数据路径退化**：compose 注入空串导致 `MONEYHELPER_DB_PATH=""`，`Path("")` 解析为当前目录。路径解析改为忽略空值并展开相对路径；compose 不再传该变量。
- **`.env` 泄密路径**：一键脚本把含密钥的 `.env` 写到仓库根但未被忽略，现已在 `.gitignore` 覆盖根目录 `.env`。

### 修复（P1）

- **确认接口可重复执行**：新增 `claim_pending_action` 原子抢占（条件 UPDATE + rowcount 校验），并发/重放只有一方能执行；图内与降级路径都改用它。
- **成员删除外键失败**：改为先删 `member_loans` 再删 `members`，并包在事务里。
- **撤回流水外键失败**：`owner_id` 为空时保持 NULL，不再写成 0。
- **备份不完整**：导出/恢复补齐成员、借贷、自选、溯源、审计五类数据；流水恢复保留 `owner_id`/`is_shared`；格式版本升到 3（兼容读 v2）。
- **关闭晨报连带关掉订阅巡检**：两者解耦，巡检始终注册。
- **收益率口径**：简单收益率只把非工资性流入算作追加本金；XIRR 改为"成本投入 → 当前市值"两笔现金流，不再把生活收支混进投资收益。
- **附件上传必然 400**：前端不再对 FormData 强制注入 JSON Content-Type；后端校验 multipart 并拒绝 PDF（明确告知，而不是把二进制当文本）。
- **财务快照卡恒为空**：字段名修正为 `total_market_value`，储蓄率不再重复乘 100。
- **收件箱请求循环**：`markAllRead` 改用 ref 读取最新列表，回调身份稳定，不再触发 effect 反复请求。
- **Service Worker 永不更新**：构建脚本改为按内容哈希替换 `CACHE` 常量，并可幂等重跑。
- **行情下跌不显示跌幅**：涨跌额/涨跌幅改用允许负数的解析器。
- **`/api/health-check` 免鉴权**：从白名单移除（会输出财务体检结论）。
- **工具层设置键不一致**：补 `lang` 白名单，`morning_report_time` 归一为 `report_time` 并触发调度重排。

### 变更

- **长记忆改为纯本地**：移除 mem0 + chromadb（其 embedder 默认走 OpenAI，记忆内容会离开本机），改用本地 BM25 检索 `user_memory`，接口 `remember/recall` 不变。
- **删除未接线的规则引擎**：`rules.py` / `settings_rules.py` 全仓无调用，连同测试一并移除。
- **删除 11 个未使用 UI 组件与 7 个 Radix 依赖**。
- **可观测性改为零依赖**：移除 OpenTelemetry/Phoenix 依赖，改用标准库记录 LLM/工具耗时，`/api/metrics` 输出平均值/峰值/次数。
- **响应式**：侧栏与数据面板支持拖拽调宽（持久化、双击复位）；手机端新增底部导航；设置页在窄屏按三组折叠；数据面板在 xl 断点才挤占主区，消除 768–1279 的半遮挡；面板补齐焦点陷阱与焦点归还。
- **首屏体积**：Dashboard/部门面板/收件箱面板改为懒加载，主包 581KB → 453KB。

### 跨平台

- `scripts/dev.sh`、`scripts/lint.sh`、`scripts/e2e-backend.sh`、`deploy/one-click.sh` 自动探测 `Scripts/python.exe` 与 `bin/python`，Python 命令按 `python3 → python → py` 回退。
- `start.bat` 支持 `--prod`，自动建 venv 与装依赖；`.gitattributes` 固定 `.bat` 为 CRLF、`.sh` 为 LF。

## [1.4.0] - 2026-10-07（安全加固 + 前端渲染修复 + 测试覆盖提升 + 订阅/撤回/预算）

> 定位：安全漏洞全面修复；空白页根因治理；CI 真正跑测试；订阅到期巡检+撤回面板+预算/订阅卡片落地。

### 安全修复

- **P0 `/mcp` 鉴权绕过**：`mount_to_app` 新增 `_McpAuthGuard`（`BaseHTTPMiddleware`），对 `/mcp` 路径强制校验 `API_TOKEN`，关闭"挂载 ASGI 子应用绕过主中间件链"的缺口
- **P0 MCP 工具命名隔离**：外部 MCP 工具统一加 `mcp__` 前缀，防止与内置财务工具命名冲突及 prompt injection 误调用
- **P0 SQL LIKE 通配符注入**（`db.search_runs`）：转义 `%` / `_` / `\`，加 `ESCAPE '\'` 子句，杜绝用户输入被当通配符引发全表扫描
- **P1 备份口令 SSE 泄漏**：`tool_backup_now` 返回文本不再含明文口令，口令仅通过独立 `passphrase` 字段一次性传递
- **P1 登录限流分布式爆破**：`auth.login()` 注入 `FastAPI Request`；支持 `X-Forwarded-For` 取真实 IP；额外按用户名限流
- **P1 `ai_enabled` 工具层拒绝**：从 `SETTING_KEYS_ALLOWED` 移除 `ai_enabled`，防止模型静默关闭 AI 功能
- **P1 LLM 配置读取静默吞异常**：`llm._config()` DB 失败改为 `_log.warning`，区分"未接入"与"配置损坏"

### 前端修复

- **白屏根因**：`main.tsx` 中 `I18nProvider` 提升至 `ErrorBoundary` 外层，消除 `useI18n()` 在 Provider 外 throw 导致整树崩溃

### 工程化

- **CI/CD**：`.github/workflows/ci.yml` 后端段新增 `pytest` 运行（289 用例），前端段新增 `vitest run`（31 用例），CI 真正成为质量门禁
- **文档**：`CHANGELOG` 版本降序重排；中英文 README 版本号统一；`CONTRIBUTING.md` 端口号修正；删"AI生成"残留标记
- **Git**：移除 remote URL 中的 PAT 凭据明文

### 来自 1.3.x/1.2.x（保留条目）

- **订阅到期巡检**：`app.scheduler.subs_due_check` CronTrigger Asia/Shanghai，7 天窗口，月度幂等去重写入 `user_memory`
- **通用撤销面板**：`CommandPalette`（Cmd+K）撤销分组，`POST /api/undo/{record_id}` 撤回
- **Dashboard 预算卡**（`BudgetCard`）三档配色 + 红色超支徽标 + 分类进度行 + 无预算引导
- **订阅待缴卡**（`SubscriptionsCard`）前端纯 hook 计算 7 天内到期项；今日红/3 天黄
- **BudgetSection 实时预览**：分类输入即时渲染堆叠进度条，溢出红提示
- **新增端点**：`GET /api/subscriptions` + `GET /api/undoables` + `POST /api/undo/{record_id}` + `DELETE /api/memory?kind=`

## [1.3.0] - 2026-10-05（撤回 + 规则引擎 + 限流 + 前端单测）

> 定位：让应用在「可用」之上进一步「可逆、可自治、可回归」——写错能撤回、分类能自学习、接口能被保护、前端能被单测约束。

### 新增

- **SQLite 快照式 undo**：每笔写交易/持仓/负债/订阅落库前 `_record_snapshot`，撤回时 `_restore_from_snapshot` 还原。单条 + 批量撤回，零新依赖
- **JSON DSL 分类规则引擎**（`backend/app/rules.py`）：`desc_contains`/`desc_regex`/`category_is`/`amount_min`/`amount_max`，priority 数字大者优先，命中即短路
- **in-memory 滑动窗口 API 限流**：200 次/分钟/IP，429 + `Retry-After`；`/api/health` 与 `/api/metrics` 不计。绕过 slowapi 依赖
- **vitest + RTL + jsdom 前端单测**：覆盖 `i18n`/`store`/`AlertBanner` = 16 项

### 工程化

- 后端 282 用例全绿；前端 16 用例全绿
- Playwright 11 项 e2e（smoke×5 + chat×2 + data×4）在位
- `test_rate_limit.py` 4 项专项测限流行为

## [1.2.1] - 2026-10-05（去自研发化 + 前端安全/性能加固 + e2e 补齐）

> 定位：消除重复造轮子；收紧前端安全与性能基线；补齐端到端测试短板。

### 重构

- backend/mcp_client.py：自研 JSON-RPC + StreamableHTTP 帧重试移除，改用官方 `mcp.ClientSession` + `streamable_http_client`
- backend/db.py memory_retrieve：手写 Okapi BM25 换为 `rank_bm25.BM25L`；保留中文二元组分词

### 安全

- ReactMarkdown 输出过 `rehype-sanitize` 阻断脚本注入
- DataSection.importBackup：探测明文/加密备份，差异化提示

### 性能

- FinishedMessages 消息虚拟化窗口，长会话 DOM 节点下降约 10 倍
- build：esbuild `pure: [console.log/debug/info]` 剔除生产 console

### 依赖

- + `mcp>=1.0,<2` / `rank-bm25>=0.2,<1` (backend)
- + `rehype-sanitize` / `@playwright/test@1.63.0` (frontend)

### 测试

- Playwright 端到端 11 项冒烟 + 问答 + 功能页

## [1.2.0] - 2026-10-05（Agent 智能体升版）

> 定位：Agent 路线图 P0/P1/P2 全部落地，真实模型端到端联调与质量安全收尾。

### 新增

- **Agent P0**：长会话摘要压缩；模型点亮/可用性探测 + 自动降级
- **Agent P1**：记忆分层（会话/长期/经验）+ BM25 语义检索 + 经验库反思 + 主动遗忘
- **Agent P2**：多 Agent 编排（supervisor → 财务/通用/记忆）；审计日志；MCP 客户端；附件上传
- 真实 AI 端到端联调 + 压力测试（20 并发写 / 15 混合读写 / 极端输入全 422）

### 修复

- 空库 agent 降级误报「总市值 0」→ 改走「还没有录入」引导
- conftest 注入 `_no_real_llm`，全量 5–6 分钟降到 42.8s

### 工程化

- 后端 269 用例全绿（42.8s）、覆盖率 77%（核心模块 90%+）
- 前端生产构建通过

## [1.0.0] - 2026-10-01（正式版）

> 定位：**本地运行 × 云端能力**。对话界面中枢；数据 100% 本地存储；国产 AI 端点。

### 新增

- 5 页签投资者心智前端；17 个 agent 工具；财务目标/长期记忆/体检（5 维度）+ 晨报
- PBKDF2 + Fernet 加密备份（口令一次性展示）；行情三级降级；空库首启引导
- 双语 UI + 高度自定义（默认首页/涨跌色/语言/轮询…）

### 修复

- 理财咨询句不被记账劫持；6 位代码买入不错记支出；晨报递归修复
- 安全：agent 模式只暴露读类工具（7 个写工具从模型侧移除）；`tool_set_setting` 白名单

### 工程化

- 182 测试全绿；覆盖率 75%+
- 开源化：中英文 README + 真实截图 + SEO + docs 五件套

## [0.9.0] - 2026-09（投资者心智重构 + 工作流）

- 5 页签导航、指数条、持仓分组 + 集中度风控、行情自选/搜索/K 线、17 个 agent 工具

## [0.8.0] - 2026-09（目标 · 记忆 · 体检）

- 财务目标、长期记忆、5 维度体检；对话中"记住…"直存

## [0.7.0] - 2026-09（LangGraph 单路径）

- LangGraph 图成为唯一执行路径；React 19 / Vite 7 / Tailwind 4

## [0.6.0] - 2026-09（Agent 升级）

- 真实 agent 工具循环、K 线、备份/恢复、Docker、一键启动

## [0.5.0] - 2026-09

- 预算、记账、CSV 导入、PWA、会话搜索、AI 问答、品牌系统
