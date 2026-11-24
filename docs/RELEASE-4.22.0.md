# Moneyhelper 4.22.0 交付说明

> 状态：**已做完**。外部协同页从“只能下载、人工转发”推到“真实出本机”：能配邮箱就真发信，能配网关就真签名 POST；没资质、没密钥的地方明确停在未配置，不拿界面占位冒充接入。

- 版本：`4.22.0`（上一版 `4.21.1`）
- 日期：2026-11-24
- 仓库：`moneyhelper`，分支 `main`
- 业务表：75 张（新增 `external_channels`、`external_deliveries`）
- 接口：357 个 OpenAPI 路径（新增 6 个 `/api/external` 通道/投递接口）
- 代码规模：`backend/app` 534 个 Python 文件；`frontend/src` 261 个 TS/TSX 文件
- 功能提交：`f6ff57edcbee1c399609d3d0c1e992ef88e66c63`
- 五远端：GitCode / GitHub ×3 / Gitee 的 `main` 同为同一 SHA
- 飞书交付：https://my.feishu.cn/file/V5HsbN1g3oI1w1xaHKucWnyv6Pe

## 一、这次真的接了什么

4.21.1 把外部协同页做得能读了，但最后一步仍然停在页面。4.22.0 补的是“资料包怎么真实离开本机”，不是再画一层。

### 1. 邮箱投递（真发信）

- 用用户自己的 SMTP 邮箱，主机、端口、STARTTLS/SSL、用户名、授权码、发件人、收件人、主题前缀都可配。
- 测试按钮会真的发一封测试邮件；业务投递会带包体 JSON、SHA256 摘要，付款包再附 CSV。
- 返回 SMTP 受理收件人、被拒收件人与 Message-ID；密码填邮箱授权码，不填网页登录密码。
- 外部邮箱强制 STARTTLS / SSL；明文只允许本机联调，且需 `MH_ALLOW_LOCAL_CHANNELS=1`。

### 2. 税费申报网关（真签名 POST）

- 地址、服务商名、签名密钥、超时四项；地址只收 HTTPS，拒绝 URL 内嵌账号密码、内网与保留地址。
- 请求头带 `X-MH-Timestamp`、`X-MH-Signature`（HMAC-SHA256）、`Idempotency-Key`。
- 只把 2xx 视为对端受理；状态码、回执号、响应片段原样落库。
- 治税直连的资质问题没有被绕过：这里只负责把核对包送达服务商入口，不生成申报表、不冒充税局回执。

### 3. 付款与审计网关

- `bank_gateway` 只收付款包，`audit_gateway` 只收合并包；都走同一套签名与幂等规则。
- 它们现在可以真实接通服务商，但不代表银行已划款、审计已出意见。没有持牌通道与授权时，页面停在未配置。

## 二、怎么防止“假成功”

- 没密钥、没启用、缺地址时 fail-closed，不会因为点了投递就默认成功。
- 同一底稿的幂等键由用户、通道、包类型、包 ID、来源摘要组合哈希；重复点击返回 `duplicate`，不重复外发。
- 投递成功自动进交接台账；失败写 `HANDOFF_SEND_FAIL` 审计，错误文本原样保留。
- 状态只有 `pending / accepted / failed`；`accepted` 的文案明确写“只代表对端受理”，不写成申报成功、付款成功或审计完成。

## 三、真实验收证据

本地起了一个独立接收端，不走 mock：

- SMTP：`127.0.0.1:2525`，收到测试邮件与税务包业务邮件；业务邮件附件字节 4,809，数据库记录 `attachment_bytes=4809`。
- HTTP：`127.0.0.1:9099/hook`，收到税费网关签名 POST，回执 `SINK-RECEIPT-4220`；请求日志落在 `/tmp/channel_http.log`。
- 数据库留痕：
  - `tax_gateway` → `TAX-202611-f9ccecd1`，`accepted`，回执 `SINK-RECEIPT-4220`。
  - `smtp` → `TAX-202611-f9ccecd1`，`accepted`，收件人 `accountant@local.test`，附件字节 4,809。
- 通道测试留痕：
  - `smtp`：`last_test_ok=1`，“SMTP 服务器已受理测试邮件”。
  - `tax_gateway`：`last_test_ok=1`，“对端已受理测试请求”。

## 四、这一轮修掉的三个真问题

1. **“未知通道”**：通道目录漏了 `channel_id`，`readiness()` 把四张卡都识别成 `unknown`；补上 `channel_id: spec["id"]` 后恢复。
2. **投递被“无外部通道”反拦**：税务包 `filing_channel`、付款包 `execution_channel`、合并包 `audit_basis` 本身就是“无外部通道”的阻断项，不能反过来阻断投递；现在只拦真正的数据阻断项与 `missing` 包。
3. **有密码的本机 SMTP 点不了测试**：前端按 `configured` 禁用测试按钮，但无密码的本机 SMTP 实际已就绪；改为按 `ready` 判断。
4. **附件数审计不一致**：SMTP 投递摘要原先在发送后补附件数、但未回写数据库，显示 `attachments: 0`；现在创建投递前计算并落库，税务包固定 2 个附件。

## 五、验证

| 项 | 结果 |
| --- | --- |
| 后端定向 | `test_external_delivery.py` + 交接/资料包共 9 项通过（16.00s） |
| 后端全量 | `1960 passed, 1 warning`（306.75s） |
| 前端全量 | 36 文件 / `247 passed`（79.86s） |
| 类型 | `tsc --noEmit` 通过 |
| 构建 | `npm run build` 18.76s；`ExternalPacketPanel` 67.03 kB / gzip 15.18 kB |
| 浏览器 · 亮色 | 四张通道卡、两笔已受理记录、SMTP/税费网关均显示已就绪 |
| 浏览器 · 暗色 | 同一页切换后卡片、状态、最近投递与台账徽章正常 |
| 浏览器 · 移动端 | 390×844：通道卡纵向排列，配置与测试按钮完整，无横向滚动 |
| 真实测试 | SMTP 测试邮件、税费网关 probe 均真实到达本地接收端 |
| 真实投递 | 税费网关与 SMTP 各完成一次业务投递，状态 `accepted` 并留痕 |

## 六、截图

- `docs/screenshots/192-external-4220-channels.png`：亮色投递中心，两张通道已就绪、两笔已受理记录。
- `docs/screenshots/193-external-4220-gateway-config.png`：税费申报网关配置侧栏，地址、服务商、签名密钥、启用开关。
- `docs/screenshots/194-external-4220-smtp-config.png`：邮箱投递配置侧栏，主机、端口、加密、发件人与收件人。
- `docs/screenshots/195-external-4220-test-success.png`：SMTP 测试成功提示与通道状态。
- `docs/screenshots/196-external-4220-dark.png`：暗色投递中心与最近投递。
- `docs/screenshots/197-external-4220-mobile.png`：390×844 移动端总览与投递入口。
- `docs/screenshots/198-external-4220-mobile-channels.png`：移动端通道卡与测试结果。

## 七、边界（一条没松）

| 项目 | 当前事实 |
| --- | --- |
| 税局直连申报/缴款 | 仍需乐企准入或服务商通道；4.22.0 只把核对包送达可配置网关，不生成申报结论 |
| 银行/券商真实资金划转 | 仍需持牌通道与用户授权；银行网关只负责送付款草稿包，不执行划款 |
| 集团法定合并/审计意见 | 仍需审计口径、抵销与合并范围确认；审计网关只负责送合并包，不出意见 |
| 五个内容社区代发布 | 仍需各平台账号、登录与发布授权；不属于本轮范围 |

## 八、结论

4.22.0 已做完并交付。它没有把 P2 的外部资质问题“用代码糊过去”，而是把能真实做的一段做成了真实：邮件真发、网关真签名 POST、测试真触网、回执真落库、重复点击不重发、失败不装成功。税局、银行、审计、社区发布仍然停在需要资质与授权的位置，页面上也如实这么写。
