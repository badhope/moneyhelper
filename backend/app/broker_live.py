"""可配置的真实券商 API 适配器门面（v4.7）。

- futu：富途 OpenD（futu-api），需要本机 OpenD 11111 端口与交易权限；
- longport：长桥 OpenAPI（longport），需要 App Key/Secret/Access Token；
- tiger：老虎 OpenAPI（tigeropen），需要 Tiger ID/私钥/账户；
- ib：盈透 TWS/IB Gateway（ib_insync），需要本机 7496/7497 连接；
- xtquant / easytrader：延续 v4.6 的 QMT 与 GUI 通道。

各通道按券商拆到 broker_live_base / _futu / _longport / _tiger / _ibkr，
本模块保留同名类导出（broker_adapter 的注册表按名取类）。
每个适配器都支持：probe → connect → cash/positions → preview → submit → poll。
真实凭据由上层通过 vault 解密后以 dict 传入；本模块不从请求体记录密码，不打印凭据。
"""

from __future__ import annotations

from .broker_live_base import LiveAdapterBase  # noqa: F401,E402
from .broker_live_futu import FutuBroker  # noqa: F401,E402
from .broker_live_ibkr import IBKRBroker  # noqa: F401,E402
from .broker_live_longport import LongPortBroker  # noqa: F401,E402
from .broker_live_tiger import TigerBroker  # noqa: F401,E402
