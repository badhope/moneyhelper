"""复式总账数据层（切片 4）：科目、期间、凭证、过账、反冲、试算表。

金额在库里一律存整数分；API 层再转成元。所有操作按 tenant_id 隔离，
不读写现有单式 `transactions`。
"""

from __future__ import annotations

# 时间戳策略测试要求门面暴露统一时钟（实际写入在 gl_* 子模块）
from ..timeutil import now_str as _now  # noqa: F401,E402

# ---------------------------------------------------------------------------
# 科目
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 会计期间
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 凭证
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 试算表
# ---------------------------------------------------------------------------
# 科目/期间与凭证两组已拆出；门面保持 db.gl.* 全部可用
from .gl_accounts import (  # noqa: F401,E402
    _account_payload,
    _open_period_for_date,
    _parse_date,
    gl_bootstrap,
    gl_close_period,
    gl_create_account,
    gl_create_period,
    gl_get_account,
    gl_get_period,
    gl_list_accounts,
    gl_list_periods,
)
from .gl_entries import (  # noqa: F401,E402
    _entry_payload,
    _insert_entry_locked,
    _line_payload,
    _validate_lines,
    gl_create_entry,
    gl_delete_draft_entry,
    gl_get_entry,
    gl_list_entries,
    gl_post_entry,
    gl_reverse_entry,
    gl_trial_balance,
)
