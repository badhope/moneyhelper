"""连接器目录的枚举与条目构造器（纯数据，无 I/O）。"""

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
