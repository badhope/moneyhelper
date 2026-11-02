"""连接中心（Connect Hub）：外部数据源与资金账户的统一接入层。

四类接入方式，按「用户操作成本」从低到高排列：

1. public_api    公开数据源，免登录、免密钥，后台直接拉（行情 / 基金净值 / 财报 /
                 发票查验 / 企业工商信息）。
2. deep_link     官方站点跳转：我们没有接口，但把用户送到正确页面并记录状态，
                 不让用户自己找入口。
3. browser_login 浏览器代登录：用户在自己的浏览器完成登录，页面内捕获 / 书签脚本
                 回传数据（配对码一次性授权，不保存平台密码）。
4. file_import   文件导入：官方 App 导出账单 CSV 后放进收件目录，后台自动扫描入账
                 （用户唯一要做的动作是「导出」）。

边界：本模块不代持用户密码、不绕过平台风控、不自动下单到真实券商。
实盘交易一律生成「交易意图」→ 用户确认 → 跳转券商页面，成交后回填。
"""

from __future__ import annotations

from .catalog import CATEGORIES, CONNECTORS, get_connector, grouped_catalog
from .marketdata import (
    fund_history,
    fund_nav,
    index_snapshot,
    market_movers,
    source_status,
)
from .service import (
    build_bookmarklet,
    execute_trade_intent,
    scan_import_inbox,
    sync_connection,
)
from .store import (
    CONNECTION_STATUSES,
    INTENT_STATUSES,
    create_connection,
    create_intent,
    create_job,
    delete_connection,
    finish_job,
    get_connection,
    get_intent,
    issue_pairing_code,
    list_connections,
    list_intents,
    list_jobs,
    redeem_pairing_code,
    update_connection,
    update_intent,
)

__all__ = [
    "CATEGORIES",
    "CONNECTION_STATUSES",
    "CONNECTORS",
    "INTENT_STATUSES",
    "build_bookmarklet",
    "create_connection",
    "create_intent",
    "create_job",
    "delete_connection",
    "execute_trade_intent",
    "finish_job",
    "fund_history",
    "fund_nav",
    "get_connection",
    "get_connector",
    "get_intent",
    "grouped_catalog",
    "index_snapshot",
    "issue_pairing_code",
    "list_connections",
    "list_intents",
    "list_jobs",
    "market_movers",
    "redeem_pairing_code",
    "scan_import_inbox",
    "source_status",
    "sync_connection",
    "update_connection",
    "update_intent",
]
