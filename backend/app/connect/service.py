"""连接中心业务服务门面：同步 / 收件箱 / 交易意图 / 书签脚本。

这里只做「编排」：具体取数在 marketdata，落库在 store，账本写入复用既有 db 层。
所有外部失败都转成可读的 job.result，不向调用方抛 5xx。
"""

from __future__ import annotations

from ..logging_utils import get_logger

log = get_logger(__name__)

__all__ = [
    "MAX_INBOX_FILE_BYTES",
    "build_bookmarklet",
    "execute_trade_intent",
    "import_text",
    "inbox_dir",
    "scan_import_inbox",
    "sync_connection",
]

from .service_bookmarklet import build_bookmarklet  # noqa: F401,E402
from .service_common import inbox_dir  # noqa: F401,E402
from .service_inbox import (  # noqa: F401,E402
    MAX_INBOX_FILE_BYTES,
    _detect_source,
    _existing_keys,
    _read_text,
    import_text,
    scan_import_inbox,
)
from .service_intents import _pick_paper_account, execute_trade_intent  # noqa: F401,E402
from .service_sync import _handoff, _sync_public, sync_connection  # noqa: F401,E402
