"""连接器目录：内置接入点清单（纯数据，无 I/O）。

一份连接器 = 一个外部平台/数据源的接入说明，包含：
- 用哪种接入方式（public_api / deep_link / browser_login / file_import）
- 能拿到什么（能力标记）
- 用户要做几步（automation：auto / semi / manual）
- 官方入口地址（不接受任何第三方聚合站）

能力标记约定：
    quotes     行情/K 线/净值
    holdings   持仓与资产
    bills      交易流水/账单
    invoices   发票
    statements 财报/公告
    trade      下单（真实交易）
    transfer   转账/资金划拨
"""

from __future__ import annotations

from typing import Any

# 接入方式
KINDS = ("public_api", "deep_link", "browser_login", "file_import", "gateway")
# 自动化程度：auto=后台全自动；semi=用户点一下/扫一次；manual=用户自己做一次导出
AUTOMATION = ("auto", "semi", "manual")

CATEGORIES = (
    ("market", "行情与投研"),
    ("broker", "证券与交易"),
    ("fund", "基金"),
    ("bank", "银行与存款"),
    ("pay", "支付与钱包"),
    ("invoice", "发票与票据"),
    ("company", "公司与财税"),
)


def _c(
    cid: str,
    name: str,
    category: str,
    kind: str,
    automation: str,
    capabilities: list[str],
    *,
    vendor: str = "",
    login_url: str = "",
    data_url: str = "",
    docs_url: str = "",
    note: str = "",
    requires_login: bool = False,
    supports_auto_sync: bool = False,
    supports_trade: bool = False,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": cid,
        "name": name,
        "vendor": vendor or name,
        "category": category,
        "kind": kind,
        "automation": automation,
        "capabilities": capabilities,
        "login_url": login_url,
        "data_url": data_url,
        "docs_url": docs_url,
        "note": note,
        "requires_login": requires_login,
        "supports_auto_sync": supports_auto_sync,
        "supports_trade": supports_trade,
        "fields": fields or [],
    }


CONNECTORS: list[dict[str, Any]] = [
    # ------------------------------------------------------------------
    # 行情与投研（全部免登录公开源，后台自动拉）
    # ------------------------------------------------------------------
    _c(
        "eastmoney_quote",
        "东方财富行情",
        "market",
        "public_api",
        "auto",
        ["quotes"],
        data_url="https://quote.eastmoney.com/",
        note="A 股/ETF/指数实时报价与 K 线；免密钥，已作为默认行情源接入。",
        supports_auto_sync=True,
    ),
    _c(
        "sina_quote",
        "新浪财经行情",
        "market",
        "public_api",
        "auto",
        ["quotes"],
        data_url="https://finance.sina.com.cn/",
        note="新浪 hq.sinajs.cn 备源；东财不可用时自动切换，无需配置。",
        supports_auto_sync=True,
    ),
    _c(
        "eastmoney_fund",
        "天天基金公开净值",
        "fund",
        "public_api",
        "auto",
        ["quotes"],
        data_url="https://fund.eastmoney.com/",
        note="场外基金单位净值/累计净值与历史净值，免登录；已接入基金净值接口。",
        supports_auto_sync=True,
    ),
    _c(
        "eastmoney_movers",
        "东方财富涨跌榜",
        "market",
        "public_api",
        "auto",
        ["quotes"],
        data_url="https://quote.eastmoney.com/center/gridlist.html",
        note="全市场涨跌幅/成交额排行，用于盘面扫描；免密钥。",
        supports_auto_sync=True,
    ),
    _c(
        "cninfo",
        "巨潮资讯网",
        "market",
        "public_api",
        "auto",
        ["statements"],
        data_url="http://www.cninfo.com.cn/",
        note="上市公司公告与定期报告官方披露平台；财报可下载后从「财报」页解析。",
        supports_auto_sync=False,
    ),
    _c(
        "sse",
        "上海证券交易所",
        "market",
        "deep_link",
        "semi",
        ["statements", "quotes"],
        login_url="https://www.sse.com.cn/",
        note="官方披露与行情入口；无开放个人接口，作为公告取数跳转。",
    ),
    _c(
        "szse",
        "深圳证券交易所",
        "market",
        "deep_link",
        "semi",
        ["statements", "quotes"],
        login_url="https://www.szse.cn/",
        note="官方披露入口；公告与定期报告可在站内检索后下载。",
    ),
    _c(
        "stats_gov",
        "国家统计局",
        "company",
        "public_api",
        "auto",
        ["statements"],
        data_url="https://data.stats.gov.cn/",
        note="宏观数据（CPI/PPI/社融等）公开查询入口，用于经营环境对照。",
    ),

    # ------------------------------------------------------------------
    # 证券与交易（真实下单：跳转券商官方页面；本系统只生成交易意图）
    # ------------------------------------------------------------------
    _c(
        "futu",
        "富途 OpenAPI",
        "broker",
        "gateway",
        "semi",
        ["holdings", "trade"],
        login_url="https://openapi.futunn.com/",
        docs_url="https://openapi.futunn.com/futu-api-doc/",
        note="真实 API 通道：需本机运行 Futu OpenD、App Key/Secret 或 OpenD 账号与交易权限；系统默认 dry-run。",
        requires_login=True,
        supports_trade=True,
        fields=["OpenD 地址", "账户 ID", "交易市场", "API 凭据"],
    ),
    _c(
        "longport",
        "长桥 OpenAPI",
        "broker",
        "gateway",
        "semi",
        ["holdings", "trade"],
        login_url="https://open.longbridge.com/",
        docs_url="https://open.longportapp.com/docs/",
        note="官方 OpenAPI：需申请 App Key / App Secret / Access Token；覆盖港美股及权限范围内市场。",
        requires_login=True,
        supports_trade=True,
        fields=["App Key", "App Secret", "Access Token"],
    ),
    _c(
        "tiger",
        "老虎 OpenAPI",
        "broker",
        "gateway",
        "semi",
        ["holdings", "trade"],
        login_url="https://open.itigerup.com/",
        docs_url="https://quant.itigerup.com/openapi/",
        note="官方 OpenAPI：需 Tiger ID / 私钥 / 交易账户；本系统不托管私钥明文。",
        requires_login=True,
        supports_trade=True,
        fields=["Tiger ID", "Private Key", "Account"],
    ),
    _c(
        "ibkr",
        "Interactive Brokers",
        "broker",
        "gateway",
        "semi",
        ["holdings", "trade"],
        login_url="https://www.interactivebrokers.com/",
        docs_url="https://ib-insync.readthedocs.io/",
        note="需本机 TWS / IB Gateway 开启 API（默认 7497）；适合美股/港股等市场。",
        requires_login=True,
        supports_trade=True,
        fields=["TWS 地址", "端口", "Client ID"],
    ),
    _c(
        "eastmoney_sec",
        "东方财富证券",
        "broker",
        "browser_login",
        "semi",
        ["holdings", "bills", "trade"],
        login_url="https://jywg.18.cn/",
        note="在券商官方页面登录后，用配对码回传持仓/对账单；下单走券商页面，系统只生成待执行指令。",
        requires_login=True,
        supports_auto_sync=True,
        supports_trade=True,
        fields=["资金账号", "营业部"],
    ),
    _c(
        "citic_sec",
        "中信证券",
        "broker",
        "deep_link",
        "semi",
        ["holdings", "bills", "trade"],
        login_url="https://etrade.cs.ecitic.com/",
        note="官方交易入口；持仓与对账单可从客户端导出 CSV 后自动导入。",
        requires_login=True,
        supports_trade=True,
    ),
    _c(
        "ht_sec",
        "华泰证券",
        "broker",
        "deep_link",
        "semi",
        ["holdings", "bills", "trade"],
        login_url="https://m.zhangle.com/",
        note="涨乐财富通网页端入口；导出对账单后可自动入账。",
        requires_login=True,
        supports_trade=True,
    ),
    _c(
        "gtja_sec",
        "国泰海通证券",
        "broker",
        "deep_link",
        "semi",
        ["holdings", "bills", "trade"],
        login_url="https://www.gtht.com/",
        note="官方入口；对账单支持导出 CSV。",
        requires_login=True,
        supports_trade=True,
    ),
    _c(
        "ths",
        "同花顺",
        "broker",
        "deep_link",
        "semi",
        ["quotes", "holdings", "trade"],
        login_url="https://www.10jqka.com.cn/",
        note="行情与模拟交易入口；真实交易仍需在绑定券商完成。",
        requires_login=True,
        supports_trade=True,
    ),
    _c(
        "xueqiu",
        "雪球",
        "market",
        "browser_login",
        "semi",
        ["quotes", "holdings"],
        login_url="https://xueqiu.com/",
        note="组合与自选同步入口；登录后可把组合导出为 CSV 再导入。",
        requires_login=True,
    ),

    # ------------------------------------------------------------------
    # 基金
    # ------------------------------------------------------------------
    _c(
        "ttjj",
        "天天基金",
        "fund",
        "browser_login",
        "semi",
        ["holdings", "bills"],
        login_url="https://fund.eastmoney.com/",
        note="官方基金账户入口；净值公开接口已直连，持仓与交易记录需登录后导出。",
        requires_login=True,
    ),
    _c(
        "ant_fund",
        "蚂蚁财富基金",
        "fund",
        "deep_link",
        "semi",
        ["holdings", "bills"],
        login_url="https://www.antfortune.com/",
        note="支付宝内基金入口；账单从支付宝导出后统一导入。",
        requires_login=True,
    ),

    # ------------------------------------------------------------------
    # 银行与存款
    # ------------------------------------------------------------------
    _c(
        "cmb",
        "招商银行",
        "bank",
        "deep_link",
        "semi",
        ["holdings", "bills", "transfer"],
        login_url="https://www.cmbchina.com/",
        note="官方网银/手机银行入口；流水导出 CSV 后可自动入账。",
        requires_login=True,
        fields=["一卡通号后四位"],
    ),
    _c(
        "icbc",
        "工商银行",
        "bank",
        "deep_link",
        "semi",
        ["holdings", "bills", "transfer"],
        login_url="https://www.icbc.com.cn/",
        note="官方入口；支持导出明细 CSV/Excel。",
        requires_login=True,
    ),
    _c(
        "ccb",
        "建设银行",
        "bank",
        "deep_link",
        "semi",
        ["holdings", "bills", "transfer"],
        login_url="https://www.ccb.com/",
        note="官方入口；明细导出后在收件目录自动扫描。",
        requires_login=True,
    ),
    _c(
        "boc",
        "中国银行",
        "bank",
        "deep_link",
        "semi",
        ["holdings", "bills", "transfer"],
        login_url="https://www.boc.cn/",
        note="官方入口；支持导出交易明细。",
        requires_login=True,
    ),

    # ------------------------------------------------------------------
    # 支付与钱包（账单为主，交易与转账走官方 App）
    # ------------------------------------------------------------------
    _c(
        "alipay",
        "支付宝",
        "pay",
        "browser_login",
        "semi",
        ["bills", "holdings", "transfer"],
        login_url="https://www.alipay.com/",
        note="官方账单导出入口（我的-账单-开具交易流水证明）；也可用配对回传。密码不落地。",
        requires_login=True,
        supports_auto_sync=True,
        fields=["账单导出邮箱"],
    ),
    _c(
        "wechat_pay",
        "微信支付",
        "pay",
        "file_import",
        "manual",
        ["bills"],
        login_url="https://pay.weixin.qq.com/",
        note="微信 App → 我 → 服务 → 钱包 → 账单 → 申请导出；导出文件放入收件目录自动入账。",
        requires_login=True,
        fields=["微信号（可选）"],
    ),
    _c(
        "unionpay",
        "云闪付",
        "pay",
        "browser_login",
        "semi",
        ["bills", "holdings"],
        login_url="https://www.95516.com/",
        note="官方入口；可导出银行卡账单。",
        requires_login=True,
    ),

    # ------------------------------------------------------------------
    # 发票与票据
    # ------------------------------------------------------------------
    _c(
        "invoice_check",
        "国家税务总局发票查验平台",
        "invoice",
        "public_api",
        "auto",
        ["invoices"],
        data_url="https://inv-veri.chinatax.gov.cn/",
        note="官方发票查验（发票代码/号码/日期/金额/校验码）；需用户提供票面信息，系统只做查验不代持。",
    ),
    _c(
        "invoice_ocr",
        "发票拍照识别",
        "invoice",
        "file_import",
        "semi",
        ["invoices"],
        note="拍照/截图放入附件，走 OCR 提取票面字段后人工确认入账；不依赖第三方云 OCR。",
    ),

    # ------------------------------------------------------------------
    # 公司与财税
    # ------------------------------------------------------------------
    _c(
        "gsxt",
        "国家企业信用信息公示系统",
        "company",
        "deep_link",
        "semi",
        ["statements"],
        login_url="https://www.gsxt.gov.cn/",
        note="企业工商信息官方入口；用于核对交易对手主体资质。",
    ),
    _c(
        "etax",
        "电子税务局",
        "company",
        "deep_link",
        "semi",
        ["invoices", "statements"],
        login_url="https://etax.chinatax.gov.cn/",
        note="企业申报与发票入口；申报表可下载后导入做税务测算。",
        requires_login=True,
    ),
]


_BY_ID = {c["id"]: c for c in CONNECTORS}


def get_connector(cid: str) -> dict[str, Any] | None:
    """按 id 取连接器定义（返回副本，调用方修改不会污染目录）。"""
    hit = _BY_ID.get(str(cid).strip())
    return dict(hit) if hit else None


def grouped_catalog() -> dict[str, Any]:
    """按分类分组的目录 + 统计，供前端一次渲染。"""
    groups: list[dict[str, Any]] = []
    for key, label in CATEGORIES:
        items = [c for c in CONNECTORS if c["category"] == key]
        if not items:
            continue
        groups.append({"key": key, "label": label, "items": items})
    counts = {
        "total": len(CONNECTORS),
        "auto": sum(1 for c in CONNECTORS if c["automation"] == "auto"),
        "semi": sum(1 for c in CONNECTORS if c["automation"] == "semi"),
        "manual": sum(1 for c in CONNECTORS if c["automation"] == "manual"),
        "trade": sum(1 for c in CONNECTORS if c["supports_trade"]),
    }
    return {"groups": groups, "counts": counts, "kinds": list(KINDS), "automation": list(AUTOMATION)}
