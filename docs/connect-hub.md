# 连接中心（Connect Hub）

> 解决的问题：用户不想一条条手输，也不想每次导出导入都自己找入口。
> 这里把外部平台收成「一条连接」，能自动的后台直连，要登录的给官方入口 + 一次性配对码。

## 四类接入方式

| 方式 | 用户动作 | 数据怎么进来 | 典型对象 |
|---|---|---|---|
| `public_api` 公开接口 | 无 | 后台直连官方公开接口 | 行情、基金净值、涨跌榜、巨潮公告 |
| `deep_link` 官方跳转 | 点一下去官方页面 | 用户自己在官方页面操作，导出后走文件导入 | 券商、银行、电子税务局 |
| `browser_login` 浏览器代登录 | 登录官方页面 + 点一次书签 | 书签脚本把当前页文本回传（带一次性配对码） | 支付宝、雪球、天天基金、云闪付 |
| `file_import` 文件导入 | 官方 App 导出 CSV | 放进收件目录，后台每 10 分钟自动扫描 | 微信支付、任意银行 |

自动化档位：`auto`（全自动）/ `semi`（一次授权）/ `manual`（导出即入账）。

## 已接入的公开数据源

| 数据 | 接口 | 说明 |
|---|---|---|
| 四大指数 | 新浪 `hq.sinajs.cn`（东财 push2 备源） | 东财 push2 在部分运营商出口会被重置，实测新浪稳定 |
| 全市场排行 | 东财 `clist` → 新浪 `Market_Center` | 涨/跌/换手/成交额，双源自动切换 |
| 场外基金净值 | 天天基金 `fundmobapi` / `f10/lsjz` | 最新净值 + 历史净值，免登录 |
| 个股/ETF 行情与 K 线 | 东财 `push2` / `push2his` | 既有能力，连接中心复用 |

## 安全边界（重要）

1. **平台密码、支付密码、短信验证码永不经过本系统**，也不落库。连接只保存「账号后四位」这类辨识信息。
2. **配对码是一次性能力凭据**：10 分钟有效、用后即焚、只能触发写入不能读出任何数据。`/api/connect/ingest` 因此允许免 JWT，但受限流与 Host 防护约束，且单独放开 CORS。
3. **书签脚本不读 cookie / localStorage**，只看用户当前正在看的这一页，等价于用户自己复制粘贴。
4. **实盘交易不代下单**：交易意图（`live`）只生成交接单并打开券商页面，成交后由用户回填。
5. 模拟盘（`paper`）才直接成交，走既有 A 股整手/佣金/印花税口径。

## API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/connect/catalog` | 连接器目录（分组 + 已建连接 + 统计） |
| GET | `/api/connect/sources/status` | 公开源连通性探测 |
| GET | `/api/connect/indices` | 四大指数快照 |
| GET | `/api/connect/movers?kind=` | 全市场排行（gainers/losers/turnover/amount） |
| GET | `/api/connect/fund/nav?codes=` | 场外基金最新净值 |
| GET | `/api/connect/fund/history?code=` | 基金历史净值 |
| POST/DELETE | `/api/connect/connections[/{id}]` | 建/删连接 |
| PATCH | `/api/connect/connections/{id}` | 改标签/状态 |
| POST | `/api/connect/connections/{id}/sync` | 单条同步（登录类返回配对码） |
| POST | `/api/connect/sync-all` | 全部同步 |
| POST | `/api/connect/pairing` | 签发配对码 |
| GET | `/api/connect/pairing/{cid}/bookmarklet` | 生成回传书签 |
| POST | `/api/connect/ingest` | 书签回传入口（免 JWT，配对码鉴权） |
| GET/POST | `/api/connect/inbox[/scan]` | 收件箱状态 / 立即扫描 |
| GET/POST | `/api/connect/intents` | 交易指令列表 / 新建 |
| POST | `/api/connect/intents/{id}/execute` | 执行（paper 成交 / live 交接） |
| POST | `/api/connect/intents/{id}/confirm` | 实盘成交回填 |
| POST | `/api/connect/intents/{id}/reject` | 取消指令 |
| GET | `/api/connect/jobs` | 同步任务记录 |

## Agent / MCP 工具

- `connect_catalog` 查目录与连接状态
- `connect_sync` 建连接并同步（登录类返回官方入口 + 配对码）
- `connect_fund_nav` 查基金净值
- `connect_order` 生成交易指令（`execute=true` 时 paper 直接成交；live 永远只出交接单）

## 后台自动化

| 任务 | 频率 | 行为 |
|---|---|---|
| `connect_auto_sync` | 每 60 分钟 | 只同步 `automation=auto` 且未停用的连接 |
| `connect_inbox_scan` | 每 10 分钟 | 扫描 `data/import-inbox/u<uid>/` 并自动入账 |

## 配置项

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `MONEYHELPER_PUBLIC_URL` | `http://127.0.0.1:8788` | 书签脚本回传地址；反向代理对外时改成公网地址 |

## 收件目录

`backend/data/import-inbox/u<user_id>/`：放 `.csv` / `.txt`；处理完的移到同目录 `done/`。
支持来源自动识别（文件名或表头含 alipay/支付宝 → 支付宝解析器；含 wechat/微信 → 微信解析器；其余走通用 CSV）。
