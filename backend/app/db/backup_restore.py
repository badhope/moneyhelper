"""备份导入的各域还原组件门面：总账、报销、支付、采购、银行流水与对账。

实现按域拆到 backup_restore_gl / _settle / _procure / _bank，共享写回原语在
backup_restore_table；写入语义与顺序不变（仍是同一个事务内逐域落库），
backup.py 与 backup_restore_core/extra/prefs 继续从本模块取同名符号。
"""

from __future__ import annotations

from .backup_restore_bank import (  # noqa: F401,E402
    _restore_bank_reconciliations,
    _restore_bank_transactions,
)
from .backup_restore_gl import _restore_gl  # noqa: F401,E402
from .backup_restore_procure import _restore_procurement  # noqa: F401,E402
from .backup_restore_settle import (  # noqa: F401,E402
    _restore_expenses,
    _restore_payments,
)
from .backup_restore_table import _restore_table  # noqa: F401,E402
