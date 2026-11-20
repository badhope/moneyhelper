"""内置连接器清单 · 基金净值与银行存款。

从 catalog_connectors.py 按业务段拆出，顺序与拆分前一致（`CONNECTORS` 是顺序敏感列表）。
"""

from __future__ import annotations

from typing import Any

from .catalog_base import _c

ENTRIES: list[dict[str, Any]] = [

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
]
