"""内置连接器清单 · 支付钱包、发票票据与公司财税。

从 catalog_connectors.py 按业务段拆出，顺序与拆分前一致（`CONNECTORS` 是顺序敏感列表）。
"""

from __future__ import annotations

from typing import Any

from .catalog_base import _c

ENTRIES: list[dict[str, Any]] = [

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
    # 电商经营（开放平台只做授权后的订单/结算读取，不代运营、不代下单）
    # ------------------------------------------------------------------
    _c(
        "douyin_shop",
        "抖店开放平台",
        "commerce",
        "browser_login",
        "semi",
        ["orders", "statements", "invoices"],
        login_url="https://fxg.jinritemai.com/",
        docs_url="https://op.jinritemai.com/",
        note="商家授权后读取订单、结算与账单；用于电商测算与月度对账，不下单、不改价、不投流。",
        requires_login=True,
        supports_auto_sync=True,
    ),
    _c(
        "taobao_open",
        "淘宝开放平台 / 千牛",
        "commerce",
        "browser_login",
        "semi",
        ["orders", "statements", "invoices"],
        login_url="https://myseller.taobao.com/",
        docs_url="https://open.taobao.com/",
        note="授权后导出订单与账单做经营测算；平台服务市场需商家自开权限。",
        requires_login=True,
        supports_auto_sync=True,
    ),
    _c(
        "pdd_open",
        "拼多多商家后台 / 开放平台",
        "commerce",
        "browser_login",
        "semi",
        ["orders", "statements", "invoices"],
        login_url="https://mms.pinduoduo.com/",
        docs_url="https://open.pinduoduo.com/",
        note="商家后台导出订单与结算单；开放平台应用需审核授权。",
        requires_login=True,
    ),
    _c(
        "youzan_open",
        "有赞云 / 微商城后台",
        "commerce",
        "browser_login",
        "semi",
        ["orders", "statements", "invoices"],
        login_url="https://www.youzan.com/",
        docs_url="https://doc.youzanyun.com/",
        note="店铺授权后读取订单、账单与结算；适合私域电商对账。",
        requires_login=True,
        supports_auto_sync=True,
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
