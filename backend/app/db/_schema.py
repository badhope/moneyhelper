"""数据库 schema 与种子数据门面。

DDL 见 schema_tables.py（按域分三段），示例数据见 schema_seed.py。
"""

from __future__ import annotations

from .schema_seed import (  # noqa: F401
    DEFAULT_SETTINGS,
    SEED_DEBTS,
    SEED_POSITIONS,
    SEED_SETTINGS,
    SEED_SUBSCRIPTIONS,
    SEED_TRANSACTIONS,
)
from .schema_tables import SCHEMA  # noqa: F401

assert SCHEMA.count("CREATE TABLE") >= 50  # 防误删：建表语句数量下限
