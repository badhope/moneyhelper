"""企业域建表 DDL 门面：按表组拆在 `schema_enterprise_org/gl/fin/proc.py`，
此处按原顺序拼接为单一 `SCHEMA_ENTERPRISE`（执行方无需感知拆分）。
"""

from __future__ import annotations

from .schema_attribution import SQL as _attribution
from .schema_automation import SQL as _automation
from .schema_autopilot import SQL as _autopilot
from .schema_consolidation import SQL as _consolidation
from .schema_ecommerce import SQL as _ecommerce
from .schema_enterprise_fin import SQL as _fin
from .schema_enterprise_gl import SQL as _gl
from .schema_enterprise_org import SQL as _org
from .schema_enterprise_proc import SQL as _proc
from .schema_external import SQL as _external
from .schema_plan import SQL as _plan

SCHEMA_ENTERPRISE = (
    _org
    + _gl
    + _fin
    + _proc
    + _attribution
    + _automation
    + _consolidation
    + _external
    + _plan
    + _autopilot
    + _ecommerce
)
