"""付款与银行流水（切片 6）。

付款是出纳执行记录，不重复生成总账凭证（报销审批时已生成）。
银行流水按 tenant/bank_account 隔离，金额存整数分；匹配只允许同账户、
同金额、方向为支出的未匹配流水，且一张付款最多匹配一条流水。
"""

from __future__ import annotations

# 时间戳策略测试要求门面暴露统一时钟
from ..timeutil import now_str as _now  # noqa: F401,E402

# 付款 / 流水 / 对账三组已拆出；门面保持 db.banking.* 全部可用
from .banking_bank import (  # noqa: F401,E402
    _bank,
    _bind_entry,
    _entries_for_import,
    _parse_csv_rows,
    bank_create,
    bank_get,
    bank_import_csv,
    bank_list,
    bank_match,
    bank_match_batch,
    bank_match_candidates,
    bank_unmatch,
)
from .banking_payments import (  # noqa: F401,E402
    _money,
    _payment,
    payment_create,
    payment_get,
    payment_list,
)
from .banking_recon import (  # noqa: F401,E402
    _book_balance_cents,
    _recon,
    _unmatched_bank_count,
    bank_summary,
    reconciliation_close,
    reconciliation_create,
    reconciliation_get,
    reconciliation_list,
)
