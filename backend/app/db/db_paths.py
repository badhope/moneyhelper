"""数据库路径解析：数据目录、库文件位置、旧库搬移。

默认 `backend/data`（与 Dockerfile 的 VOLUME 一致），可用
`MONEYHELPER_DATA_DIR` / `MONEYHELPER_DB_PATH` 覆盖。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..compat_env import getenv
from ..logging_utils import get_logger


def data_dir() -> Path:
    """运行期数据目录（数据库 / 备份 / checkpoint）。

    默认 `backend/data`（与 Dockerfile 的 VOLUME 一致），可用
    `MONEYHELPER_DATA_DIR` 覆盖。

    历史坑：默认值原先是 `backend/app/data`，而 Docker 卷挂的是
    `backend/data` —— 容器内账本写在卷外，重建即丢。统一到一处后，
    本地与容器看到的是同一个目录语义。

    覆盖值不允许指向程序自身目录（源码 / .git / 依赖清单）：否则一个环境变量
    就能让整个应用把数据写进源码树。最高权限需显式
    MONEYHELPER_ALLOW_SYSTEM_ACCESS=1。
    """
    raw = getenv("MONEYHELPER_DATA_DIR").strip()
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        from ..pathguard import assert_not_protected

        assert_not_protected(path, operation="把数据目录指向")
    else:
        path = Path(__file__).resolve().parent.parent.parent / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_db_path() -> Path:
    """解析数据库路径：MONEYHELPER_DB_PATH 优先，空串视为未设置。

    空串直接交给 Path("") 会退化成当前目录，导致建库失败或写错位置，
    因此这里显式过滤空值，并展开 ~ 与相对路径。
    """
    raw = getenv("MONEYHELPER_DB_PATH").strip()
    if not raw:
        return data_dir() / "wealth.db"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    from ..pathguard import assert_not_protected

    assert_not_protected(path, operation="把数据库放到")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# 旧版数据目录（backend/app/data）。2.4.2 起统一到 backend/data，
# 这里在首次启动时把老库搬过去，避免升级后"账本消失"。
_LEGACY_DB = Path(__file__).resolve().parent.parent / "data" / "wealth.db"


def _migrate_legacy_db(target: Path) -> None:
    """若新位置还没有库、但旧位置有，且没有显式指定 MONEYHELPER_DB_PATH，则搬移。

    WAL 模式下副本必须连带 -wal/-shm 一起搬，否则已提交但未 checkpoint
    的事务会丢。
    """
    if getenv("MONEYHELPER_DB_PATH").strip():
        return  # 用户显式指定了路径，不猜
    if target.exists() or not _LEGACY_DB.exists():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(_LEGACY_DB) + suffix)
            if src.exists():
                shutil.copy2(src, Path(str(target) + suffix))
        log = get_logger("db")
        log.info("db.migrated legacy=%s -> %s", _LEGACY_DB, target)
    except Exception as exc:  # noqa: BLE001 — 迁移失败不该阻断启动
        get_logger("db").warning("db.migrate_failed: %s", exc)

DB_PATH = _resolve_db_path()
_migrate_legacy_db(DB_PATH)
