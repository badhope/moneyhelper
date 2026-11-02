# 边界攻坚（v4.6）：能抄的都抄了，不能抄的说清为什么

> 上一版（v4.5）我把四件事标成了「边界/限制」。这一版逐个处理：调研开源实现 → 选可移植做法 → 落地 → 实测。
> 结论先放前面：**三件已经真正可用，一件是「架构就绪但需要用户自己的环境」——那不是没做，是设计。**

## 一、发票图片识别：二维码优先 + OCR 兜底

### 调研结论

| 方案 | 结论 | 采用 |
|---|---|---|
| PaddleOCR | 识别率高，但依赖 paddlepaddle（数百 MB），模型需下载 | 作为可选引擎之一 |
| RapidOCR (onnxruntime) | 体积小、离线、`pip install rapidocr-onnxruntime` 即用 | **首选 OCR 引擎** |
| pyzbar | Windows 需额外装 zbar DLL，常见踩坑 | 备选解码器 |
| OpenCV `QRCodeDetector` | 零配置、识别率最好、`opencv-python-headless` 即可 | **首选二维码解码器** |
| 训练发票检测模型 | 版式随地区/年份变化，训练成本高且不可控 | **不采用** |

### 关键洞察：发票二维码比 OCR 更可靠

中国增值税发票二维码内容格式固定：

```
01, 发票代码, 发票号码, 金额(不含税), 开票日期(YYYYMMDD), 校验码, 随机码
```

拿到二维码就等于拿到最关键的四个字段，且**不会有 OCR 的字符误识**。所以策略是
「二维码优先，OCR 补齐购买方/销售方/税额」，而不是硬啃 OCR。

### 实测（本机装了 opencv + rapidocr）

| 场景 | 结果 |
|---|---|
| 生成的发票二维码 PNG | `decoder=opencv`，解出 `01,011002100311,12345678,100.00,20261015,123456,abc`，字段全部正确 |
| 渲染的中文发票图片（无二维码） | `engine=rapidocr`，识别出「增值税电子普通发票 / 发票代码011002100311 / 发票号码87654321 / 开票日期2026年10月20日 / 价税合计88.00」，字段抽取成功 |
| 未安装任何解码器 | 返回 `install_hint`：「安装 opencv-python 可自动读取发票二维码（最准）」——不报错、不假装识别 |

### 落地位置

- `backend/app/import_parsers/invoice_vision.py`：QR 解析、解码器探测、OCR 探测与调用、图片一体化识别
- `POST /api/connect/invoices/image`：上传图片 → 自动选择 QR/OCR 路径 → 归档
- `GET /api/connect/invoices/vision/status`：能力探测（前端据此显示"可用/需安装"）

## 二、PDF 对账单：表格优先，文本回退，扫描件明确拒绝

### 调研结论

| 库 | 表格 | 文本层 | 体积 | 采用 |
|---|---|---|---|---|
| pdfplumber | ✅ 最强 | ✅ | 中 | **首选** |
| PyMuPDF (fitz) | 一般 | ✅ 快 | 大（AGPL） | 不采用（许可证） |
| camelot | ✅ 但依赖 Ghostscript | ❌ | 重 | 不采用 |
| pypdf | ❌ | ✅ | 小 | 发票文本层用 |

### 实现策略

1. 先用 `pdfplumber.extract_tables()` 抽表格 → 识别表头（日期/摘要/金额/借贷分列）→ 逐行归一；
2. 表格抽不到时回退文本行（日期 + 金额正则）；
3. 都抽不到 → 明确提示「若是扫描件，请改用图片识别（OCR）」，**不把二进制当文本读**；
4. 解析完成后可用 `statement_reconcile()` 与账本核对（按「日期 + 金额」匹配，摘要不参与，避免假差异）。

### 实测

用 reportlab 生成带表格线的银行对账单 PDF：

```
method=table, pages=1, rows=3
2026-09-01  Ride hail  -35.0  其他
2026-09-02  Salary     20000.0  其他
2026-09-03  Rent       -5200.0  其他
```

对账：`matched=1, missing_in_ledger=2, balanced=False`（账本确实只有 1 笔，结果正确）。

## 三、账单智能归类：抄 double-entry-generator 的规则模型

### 调研结论

[double-entry-generator](https://github.com/deb-sig/double-entry-generator) 是成熟的「账单 → 复式记账」规则转换器，核心设计值得直接借鉴：

- 规则维度：`peer`（交易对方）/ `item`（摘要）/ `category`（账单分类）/ `type`（收支方向）/ 金额区间；
- 优先级：**具体度高的规则优先**（命中的非空维度越多越优先），而非声明顺序；
- 必须有兜底账户，兜底命中要打标待复核；
- 每条结果记录「命中规则 ID + 匹配字段」，可解释、可调优。

### 我们的改造

不输出复式分录（本系统账本是单式：收入/支出 + 分类），只做「分类 + 标签」，但保留全部设计要点：

| 设计点 | 实现 |
|---|---|
| 多维匹配 | `peer` / `item` / `category_match` / `type` / `min_amount`~`max_amount` |
| 优先级 | `specificity()` = 非空维度数，降序；同分时精确匹配优先于正则 |
| 正则安全 | 编译缓存 + 长度上限 200 + 异常兜底（坏正则静默跳过） |
| 兜底 | `fallback` 标记 + `needs_review` 标签 |
| 可解释 | 返回 `rule_id` + `matched` 维度列表 |
| 调优依据 | `explain()` 输出兜底比例，>30% 时给「该补规则」提示 |

### 实测

19 条内置规则，命中情况：

```
滴滴快车     -> 交通   (transport-ridehail-item)
工资         -> 收入   (income-salary)
美团外卖     -> 餐饮   (food-delivery)
天猫超市     -> 购物   (shop-ecommerce)
云盘会员年费 -> 订阅   (sub-streaming)
未知商户 XYZ -> 其他   (fallback, needs_review)
```

发现并修掉一个真实缺口：`滴滴快车` 只出现在摘要（银行账单常见）而非商户字段时匹配不到，
因此补了一条 `item` 维度规则 `transport-ridehail-item`。

## 四、券商自动执行：适配层 + 七道护栏（默认永不下单）

### 调研结论

| 方案 | 能否真下单 | 本质 | 门槛 | 结论 |
|---|---|---|---|---|
| **QMT / miniQMT (xtquant)** | ✅ | 券商官方终端 API，`xtquant` 本地库 | 需开通 miniQMT 权限（常见 50 万资产门槛） | **首选实盘通道** |
| **easytrader** | ✅ | pywinauto 驱动券商客户端 GUI | 零门槛，但仅 Windows，客户端升级即失效 | 备选 |
| THSTrader | ✅ | 同花顺客户端自动化 | 同 easytrader | 同类，不重复接 |
| vnpy | ✅ | 开源量化框架 + 柜台网关 | 股票实盘多为机构权限 | 不采用（过重） |

**关键事实**：`xtquant` 不能 pip 安装，必须从券商 QMT 终端目录取；easytrader 的返回值只代表
「委托已提交」，不代表成交，必须轮询对账。

### 我们交付什么

`backend/app/broker_adapter.py`：

```
BrokerAdapter（协议）
  ├── NullBroker        默认：只读、拒绝一切下单
  ├── PaperBroker       模拟盘：交给既有 calculations.paper 撮合
  ├── XtQuantBroker     实盘：import xtquant 才可用
  └── EasytraderBroker  实盘：import easytrader 才可用，仅 Windows
```

**七道护栏全部在 `guarded_submit()` 里强制执行，适配器自身绕不过**：

| # | 护栏 | 实测结果 |
|---|---|---|
| 1 | 总开关 `trading_enabled`（默认 false） | `stage=switch`，拒绝 |
| 2 | `dry_run` 默认 true | `stage=dry_run`，返回模拟结果不报单 |
| 3 | 券商白名单 | `stage=whitelist`，适配器不匹配即拒 |
| 4 | 单笔金额上限 | `stage=max_order` |
| 5 | 单日累计上限 | `stage=max_daily` |
| 6 | 单票集中度上限 | `stage=position_ratio` |
| 7 | 二次确认令牌（绑定标的/方向/价格/数量，5 分钟） | 无 token `stage=confirmation`；用后即焚；内容不一致拒绝 |

### 为什么不是「没做完」

本机没有券商客户端，QMT/easytrader 的 `probe()` 会明确列出缺什么：

```
xtquant: 未安装 xtquant（需从券商 QMT 终端目录获取，不能 pip 安装）
         未设置 QMT_USERDATA_PATH / QMT_ACCOUNT_ID
easytrader: 未安装 easytrader / 未设置 EASYTRADER_EXE_PATH
```

这是**设计**：交易执行必须在用户自己的机器上、用用户自己的券商权限开启，且默认关闭。
框架已就绪，用户装好环境、设好三个环境变量就能用，不需要改代码。

## 五、定位纠偏：不是「本地优先」，是「AI 财务部门」

### 问题

仓库里有 6 处把「local-first / 本地优先」当核心卖点或产品定义，与 `docs/ROADMAP-v3.md` 的
明确决策冲突：

> **弃用口号**："local-first 隐私"降级为部署选项之一，不再当核心卖点。
> **新定位**："能自主干活的财务部门" —— 不只是一个记账工具，而是一个可编排、可复核、可接管的 AI 财务团队。

### 改法

| 文件 | 改前 | 改后 |
|---|---|---|
| README.md | "a local-first **vertical finance intelligence workbench**" | "an **AI finance department you can audit**" |
| README.md 对比表 | "Privacy / Local-first: ..." | "Data handling / ... Local, self-hosted or cloud are all deployment options" |
| README.zh.md | "本地优先的垂直财务智能体工作台" | "能自主干活、且每一步都可审计的 AI 财务部门" |
| README.zh.md 卖点 | "数据留在本机"（列为核心卖点） | "数据在你手里"（降级为部署形态说明，移到卖点末尾） |
| pyproject.toml description | "本地优先的垂直财务智能体工作台" | "面向个人与小微公司的 AI 财务部门（...数字可复核、操作可审计...）" |
| frontend/index.html | meta description 主打"本地优先" | 主打能力清单（记账/持仓/投研/财报/税负/资金调度） |
| docs/ARCHITECTURE-detail.md | "开源、本地优先的个人理财 AI Agent" | "开源的 AI 财务部门（...部署形态是选项，不是卖点）" |
| docs/promo.html | 横幅"开源 · 本地优先" | "开源 · AI 财务部门 · 数字可复核" |

同时把**真实能力**补进卖点（原来缺）：

- 能接外部世界（公开源 + 对账单 + 账单 + 发票 + 配对码回传）
- 能算公司账（增值税/企业所得税/个税/工资/月结/现金流预测）
- 交易执行（9 项预检 → 二次确认 → 适配层 → 审计）

### 保留什么

「数据存在本地 SQLite」是**事实**，不删，但改到「部署形态」位置，而不是当唯一卖点。
`docs/planning/`、`docs/research/`、`CHANGELOG` 里的历史记录不动——那是当时的决策快照，
改了反而失真。

## 六、可选依赖（不装也能跑，装了才启用）

```bash
pip install -e ".[vision]"   # 二维码 + PDF 表格 + 图片读取
pip install -e ".[ocr]"      # 离线 OCR（rapidocr）
pip install -e ".[broker]"   # 券商 GUI 自动化（仅 Windows）
```

未安装时：能力探测接口返回 `available=false` + 安装提示，功能入口显示「需安装」而不是报错。

## 七、验证

- 后端全量：**1220 passed**（v4.5 基线 1164 + 新增 56：确定性/解析 39 + HTTP 17）
- 前端：112 passed，tsc 0，build 成功
- 实测：二维码解码、OCR 识别、PDF 表格抽取与对账、规则归类、券商七道护栏逐项触发
- 定位：`grep -rn "local-first|本地优先"` 在 5 个对外文件中清零


# 八、v4.7 真实券商通道（不是占位）

v4.7 把执行层从「只有 Null/Paper/XtQuant/easytrader 框架」升级为真实 SDK 通道：

| 通道 | SDK | 本机安装/探测 | 真实连接条件 |
|---|---|---|---|
| 富途 | `futu-api` | import 成功；无凭据时 probe 精确提示 | 本机 Futu OpenD（默认 127.0.0.1:11111）+ 交易权限 + account_id |
| 长桥 | `longport` | `longport.openapi` 入口验证通过 | App Key / App Secret / Access Token + 权限 |
| 老虎 | `tigeropen` | config/client API 入口验证通过 | Tiger ID / 私钥 / 交易账户 |
| 盈透 | `ib_insync` | import 成功 | 本机 TWS/IB Gateway（7496/7497）+ API 开关 |
| QMT | `xtquant` | 本机缺少（probe 给路径提示） | 券商开通 miniQMT，终端 `userdata_mini` |
| easytrader | `easytrader` | pip import 成功；本机缺客户端路径/账户 | Windows 券商客户端 + 路径/账户配置 |

真实适配器文件：`backend/app/broker_live.py`，每个通道都实现：

- `probe()`：只检测 SDK/参数，不联网、不泄密；
- `connect()`：真实连接 OpenD / OpenAPI / TWS；
- `get_cash()` / `get_positions()`：读取真实资金与持仓；
- `preview()`：本地预检；
- `submit()`：真实委托（但必须通过 `guarded_submit()`）；
- `poll_orders()`：拉取委托状态，强调「已提交不等于已成交」。

## 凭据保存

`broker_credentials` 表只存 vault 加密 JSON：

```text
secret_enc = ~<salt>:<fernet ciphertext>
```

- `VAULT_PASSPHRASE` 未配置时拒绝保存，不降级成明文；
- API/UI 只返回 `configured=true`、label、meta，不返回 App Secret、Access Token、私钥；
- 真实 SDK 适配器读取顺序：连接记录的 vault 凭据 → 环境变量（便于 CLI/容器）；
- 连接器 UI 支持选通道、填写字段、加密保存，下一步可直接点连接/读取账户。

## 真实下单护栏不解除

接上真实通道不等于取消安全边界。真实提交仍需：

1. `MONEYHELPER_TRADING_ENABLED=true`；
2. `MONEYHELPER_TRADING_DRY_RUN=false`；
3. `MONEYHELPER_TRADING_BROKER` 在白名单；
4. 单笔/单日金额与单票集中度不过限；
5. preview 产生的 5 分钟一次性 confirmation token；
6. provenance 审计；
7. 提交后轮询券商成交状态。

默认状态依然是 `NullBroker + dry_run=true`，不会因用户配置了 API Key 就误触真实委托。


# 八、v4.7 真券商接入（SDK 实装，不是占位）

## 通道矩阵

| 通道 | SDK / 网关 | 已实装内容 | 仍需用户具备的条件 |
|---|---|---|---|
| 富途 | `futu-api` + Futu OpenD | probe / connect / cash / positions / preview / submit / orders | OpenD 本机 11111、富途交易权限、Account ID |
| 长桥 | `longport` OpenAPI | Config.from_apikey、cash / positions / submit / orders | App Key / Secret / Access Token、相应市场权限 |
| 老虎 | `tigeropen` | TigerClientConfig、cash / positions / submit / orders | Tiger ID、私钥、交易账户 |
| 盈透 | `ib_insync` + TWS/IB Gateway | accountSummary / positions / LimitOrder / openTrades | TWS/Gateway API 端口 7496/7497、API 开关 |
| QMT | `xtquant` | 原有 QMT 适配器保留 | 券商开通 miniQMT，终端 userdata_mini |
| easytrader | `easytrader` + 券商客户端 | GUI 适配器保留 | Windows 客户端路径、账户、客户端版本稳定 |

本机已安装并验证 import：`futu`、`longport`、`tigeropen`、`easytrader`、`ib_insync`；
QMT 因依赖券商终端，不在 pip 中安装，`probe()` 会给出缺项。

## 凭据安全

`broker_credentials` 只存 vault 加密 JSON。API 与前端仅返回：通道名、label、meta、`configured`、`enabled`；
不返回 App Secret、Access Token、私钥或密码。`VAULT_PASSPHRASE` 未配置时拒绝保存，不降级成明文。
备份不导出券商密文，避免将券商凭据复制到备份文件；恢复后需要重新配置。

## 为什么不是「一键自动炒股」

接入真实 API 后，系统仍强制：`trading_enabled`、`dry_run=false`、白名单、单笔/单日/集中度限额、
preview 确认令牌、provenance 审计、成交轮询。SDK 的 submit 返回「委托提交」而不是「成交」，本系统不会把
提交假报成成交。用户需要自行完成券商开户、API 授权、OpenD/TWS/客户端登录与合规确认；这些是外部权限，
不是软件可以合法替代的步骤。

配置接口：

- `GET /api/execute/status`：适配器探测 + 配置状态（打码）；
- `PUT /api/execute/brokers/{name}/credentials`：vault 加密保存（只传 API Key/Token/连接参数）；
- `GET /api/execute/brokers/configured`：只读掩码状态；
- `POST /api/execute/adapters/{name}/connect`：真实连接并读取现金/持仓；
- `POST /api/execute/preview` → `POST /api/execute/submit`：预检→一次性确认令牌→报单。
