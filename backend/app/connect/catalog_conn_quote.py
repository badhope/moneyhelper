"""内置连接器清单 · 行情与投研（免登录公开源）。

从 catalog_connectors.py 按业务段拆出，顺序与拆分前一致（`CONNECTORS` 是顺序敏感列表）。
"""

from __future__ import annotations

from typing import Any

from .catalog_base import _c

ENTRIES: list[dict[str, Any]] = [
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
]
