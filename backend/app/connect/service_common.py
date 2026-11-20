"""连接中心服务共用：账单收件目录只放这里，按租户分目录。"""

from __future__ import annotations

from pathlib import Path

from .. import db
from ..logging_utils import get_logger

log = get_logger(__name__)

def inbox_dir(user_id: int | None = None) -> Path:
    """账单收件目录：用户把导出的 CSV 放进来，后台自动扫描入账。

    按租户分目录（import-inbox/u<id>/）：多用户实例下各自看到各自的收件箱，
    不会把别人的账单扫进自己账本。
    """
    from ..db.tenant import current_user_id

    uid = current_user_id() if user_id is None else int(user_id)
    path = db.data_dir() / "import-inbox" / f"u{uid}"
    path.mkdir(parents=True, exist_ok=True)
    return path
