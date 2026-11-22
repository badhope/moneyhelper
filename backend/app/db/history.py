"""历史域门面：runs / sessions / 摘要与 pending 动作。

实现按域拆到 history_runs / history_sessions / history_pending；
`db` 包与外部调用方仍从 `app.db.history` 取同名函数。
"""

from __future__ import annotations

from .history_pending import (  # noqa: F401,E402
    claim_pending_action,
    clear_conversation_summary,
    create_pending_action,
    force_pending_status,
    fork_session,
    get_conversation_summary,
    get_pending_action,
    mark_pending_action,
    session_usage,
    set_conversation_summary,
)
from .history_runs import (  # noqa: F401,E402
    _hydrate_run,
    claim_pending_nl,
    clear_history,
    delete_last_run,
    delete_run,
    delete_runs_from,
    list_runs,
    list_scheduled_runs,
    save_run,
    search_runs,
)
from .history_sessions import (  # noqa: F401,E402
    create_session,
    delete_session,
    is_system_thread,
    list_sessions,
    move_runs,
    rename_session,
    session_thread_id,
    update_session_flags,
    upsert_session,
)
