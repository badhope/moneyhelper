
---

# 连接中心 · 深化篇（v4.5）

> v4.4 解决「能不能接上」，v4.5 解决「接上之后能不能真干活」。
> 这一层全部是**确定性计算 + 真实解析**，没有一处是"看起来合理"的占位数字。

## 一、行情深化：腾讯源 + 市场温度 + 个股档案

### 为什么换/加源

| 源 | 实测结果 | 角色 |
|---|---|---|
| 东财 `push2` | **本机被运营商出口重置**（curl 000 / httpx RemoteProtocolError） | 个股行情主源（不保证） |
| 东财 `push2ex` | 可达 | 涨跌分布、涨停/跌停池 |
| 新浪 `hq.sinajs.cn` | 可达，字段少 | 指数与个股备源 |
| 腾讯 `qt.gtimg.cn` | 可达，**50+ 字段** | 档案/分时/K 线主力 |
| 天天基金 `fundmobapi` | 可达 | 场外基金净值 |

腾讯字段解析见 `backend/app/connect/quote_tencent.py` 的 `_TENCENT_FIELDS`（下标已用 sh600519 实测核对），
一次批量请求可取价格、昨收、PE(TTM)、PB、总/流通市值、换手率、量比、振幅、涨跌停价。

### 市场温度

`GET /api/connect/market/breadth` → 涨跌家数、涨停/跌停数量、强势股数量、情绪温度 0-100。

温度公式（写死在 `market_breadth()`，可审计）：

```
temperature = 上涨占比×60% + 涨停/(涨停+跌停)×25% + min(1, 强势股/总数×20)×15%
档位：≥70 过热 / ≥55 偏暖 / ≥45 中性 / ≥30 偏冷 / <30 冰点
```

### 个股档案

`GET /api/connect/stock/{symbol}/profile` → 价格、PE、PB、总市值（亿）、换手、量比、振幅、涨跌停价。
PE 为负时明确标注「公司亏损，PE 无参考意义」，不给误导性数字。

## 二、预交易风控（`calculations/pretrade.py`）

模型说「买」不等于能买。9 项确定性检查，全部通过才放行：

| 检查 | 级别 | 口径 |
|---|---|---|
| params | block | 6 位代码 / buy·sell / 价格>0 / 股数>0 |
| lot | block | 买入必须 100 股整数倍；卖出可零股 |
| price_limit | block | 主板 ±10%、创业板/科创板 ±20%、北交所 ±30%、ST ±5%（用昨收算） |
| deviation | warn | 委托价偏离最新价超阈值（默认 3%）告警 |
| cash | block | 买入校验「金额+费用 ≤ 可用现金」 |
| holdings | block | 卖出校验「可卖 = 持仓 − 当日买入」 |
| t_plus_1 | block/warn | 当日买入股数不可当日卖出 |
| concentration | warn | 买入后单一标的占比超阈值（默认 30%） |
| daily_limit | block | 当日累计委托金额超日限额（默认 20 万） |
| duplicate | block | 60 秒内同标的/同方向/同价/同量重复委托 |

另提供 `rebalance_orders()`：把再平衡清单转成可执行委托——**先卖后买、买入整手取整、不足一手明确列出原因**，
不再静默丢弃。

## 三、券商持仓对账（`import_parsers/broker_holdings.py`）

不只是导流水，而是把**持仓**导进来：

- 支持 `证券代码 / 股票代码 / 代码`，`SH600519`、`600519.SH` 统一归一为 6 位；
- 识别 `持仓数量 / 股票余额 / 证券数量` 与 `成本价 / 参考成本价 / 摊薄成本价`；
- 自动跳过「合计/小计/汇总」行；
- 成本价或现价缺失时**明确 warning**，不静默填 0；
- 同内容文件按 SHA-256 指纹幂等，重复导入标记 `duplicate`。

## 四、发票归档（`import_parsers/invoice.py`）

| 格式 | 实现 | 依赖 |
|---|---|---|
| OFD | zip + ElementTree 直读 XML 文本节点 | stdlib |
| PDF | pypdf 文本层；未安装时明确报「不可解析」 | 可选 |
| 图片 | 明确返回「本机无 OCR 引擎」 | — |
| 文本 | 正则抽取代码/号码/日期/价税合计/税额/税率/购销方 | stdlib |

置信度按「号码 + 日期 + 金额」齐全度判定（high/medium/low），缺字段列 warning，绝不编造票号。

## 五、公司财税（`calculations/tax.py`）

| 能力 | 口径 |
|---|---|
| 增值税 | 一般计税 13/9/6/0；简易 5/3/1%；进项留抵按 0 申报并提示；小微免征阈值 |
| 附加税 | 城建 7/5/1% + 教育 3% + 地方教育 2%，以实缴增值税为基数 |
| 企业所得税 | 标准 25% / 高新 15% / 小微 5%；小微超 300 万自动回落 25%；支持弥补亏损 |
| 个税 | 工资薪金累计预扣法，7 级超额累进 + 5000 起征 + 三险一金 + 专项附加 |
| 工资 | 五险一金个人/企业两侧，缴费基数上下限钳制，输出应发/代扣/实发/企业总成本 |
| 月结 | 12 项通用清单（银行对账、发票勾稽、工资计提、增值税申报、报表勾稽…） |

**全部参数显式传入**，默认值只作演示；输出统一带 `disclaimer`，不构成正式税务意见。

## 六、个人现金流（`calculations/cashflow.py`）

1. **三档预测**：按有流水月份的净流入分布取 P20/P50/P80，输出未来 1-12 月余额路径；
   一次性大额（默认 ≥2 万）单独剔除并列出，避免被年终奖/买车带偏；悲观档转负时告警。
2. **订阅识别**：按摘要聚合 → 间隔中位数落入 25-35/85-100/350-380 天 → 金额变异系数 ≤0.15；
   支持涨价检测（最近一期 > 历史中位数 5%）与下次扣款日。
3. **异常扣款**：按商户用 `中位数 + MAD`（×1.4826 与标准差可比）判定，阈值 3.5σ；
   比均值+标准差抗极端值。

## 七、条件单

`POST /api/connect/conditionals` 支持 `price_below / price_above / pct_change_below / pct_change_above`。
`POST /api/connect/conditionals/evaluate` 拉实时行情检查，命中后**只生成待确认交易意图**，不直接下单。

## 八、API 一览（v4.5 新增）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/connect/market/breadth` | 市场温度 |
| GET | `/api/connect/stock/{symbol}/profile` | 个股档案 |
| GET | `/api/connect/stock/{symbol}/minute` | 分时 |
| GET | `/api/connect/kline` | K 线（腾讯备源） |
| GET/PUT | `/api/connect/risk/settings` | 风控参数 |
| POST | `/api/connect/risk/check` | 预交易检查 |
| POST | `/api/connect/rebalance/orders` | 再平衡转委托 |
| POST | `/api/connect/import/holdings` | 券商持仓对账 |
| GET | `/api/connect/import/holdings/history` | 导入记录 |
| POST/GET | `/api/connect/invoices[/text]` | 发票归档 |
| GET/POST | `/api/connect/conditionals` | 条件单 |
| POST | `/api/connect/conditionals/evaluate` | 检查触发 |
| POST | `/api/finance/tax/{vat,cit,iit,payroll,summary}` | 税负计算 |
| GET | `/api/finance/month-end/{month}` | 月结清单 |
| GET | `/api/finance/cashflow/forecast` | 现金流预测 |
| GET | `/api/finance/subscriptions/detect` | 订阅识别 |
| GET | `/api/finance/anomalies` | 异常扣款 |

## 九、Agent / MCP 工具（新增 10 个）

`tax_calc` / `cashflow_forecast` / `scan_subscriptions` / `scan_anomalies` / `pretrade_check` /
`import_brokerage_holdings` / `parse_invoice` / `market_breadth` / `stock_profile` / `conditional_order`

财务工具总数 48，MCP 工具面与 function calling 工具面保持同一份 schema 真源。

## 十、前端

- 连接中心新增三个页签：**投研深化**（市场温度 + 个股档案）、**交易风控**（预交易检查 + 风控参数 + 条件单）、
  **发票与对账**（发票归档 + 券商持仓导入）。
- 新增「**公司财税**」页：现金流预测卡 → 增值税/企业所得税/个税/工资/月结五页签 → 订阅与异常双卡。
- 税负页打开即用默认参数算一次（避免空结果区），所有数字标注口径与免责。
