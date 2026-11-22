"""数据库表结构（DDL）门面：三段按原序拼接成 SCHEMA。

个人账本 / 投资与连接 / 企业与总账 / 远程控制四段各自成模块（`schema_personal.py`、
`schema_invest.py`、`schema_enterprise.py`），这里只做拼接与转出；拼接顺序即建表
顺序，改动会导致外键/初始化顺序变化，勿调换。
"""

from __future__ import annotations

from .schema_enterprise import SCHEMA_ENTERPRISE  # noqa: F401
from .schema_invest import SCHEMA_INVEST  # noqa: F401
from .schema_personal import SCHEMA_PERSONAL  # noqa: F401
from .schema_remote import SCHEMA_REMOTE  # noqa: F401

SCHEMA = SCHEMA_PERSONAL + SCHEMA_INVEST + SCHEMA_ENTERPRISE + SCHEMA_REMOTE
