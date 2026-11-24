"""连接器目录的枚举与条目构造器（纯数据，无 I/O）。"""

from __future__ import annotations

from typing import Any

# 接入方式
KINDS = ("public_api", "deep_link", "browser_login", "file_import", "gateway")
# 自动化程度：auto=后台全自动；semi=用户点一下/扫一次；manual=用户自己做一次导出
AUTOMATION = ("auto", "semi", "manual")
# 控制级别：read=后台只读；import=导出文件入账；handoff=官方页面配对回传；
# manual=只给官方入口；confirm=只能起草/逐笔确认，绝不代下单或代转账。
CONTROL_TIERS = ("read", "import", "handoff", "manual", "confirm")

CATEGORIES = (
    ("market", "行情与投研"),
    ("broker", "证券与交易"),
    ("fund", "基金"),
    ("bank", "银行与存款"),
    ("pay", "支付与钱包"),
    ("invoice", "发票与票据"),
    ("company", "公司与财税"),
    ("commerce", "电商经营"),
)


def control_tier(kind: str, automation: str, supports_trade: bool) -> str:
    """把接入方式收敛成用户能理解的控制级别。

    交易能力优先：即使入口是全自动的行情源，只要涉及下单，也只能到“逐笔确认”。
    其余按 kind/automation 判定，不额外推断权限。
    """
    if supports_trade:
        return "confirm"
    if kind == "file_import":
        return "import"
    if automation == "auto":
        return "read"
    if kind == "browser_login":
        return "handoff"
    return "manual"



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
        "control": control_tier(kind, automation, supports_trade),
        "login_url": login_url,
        "data_url": data_url,
        "docs_url": docs_url,
        "note": note,
        "requires_login": requires_login,
        "supports_auto_sync": supports_auto_sync,
        "supports_trade": supports_trade,
        "fields": fields or [],
    }
