"""账单收件箱：扫描 → 解析 → 去重 → 入账 → 归档。"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import db
from ..csvimport import classify as auto_classify
from ..import_parsers import get_parser
from ..logging_utils import get_logger
from ..provenance import record_provenance
from .service_common import inbox_dir

log = get_logger(__name__)


MAX_INBOX_FILE_BYTES = 20 * 1024 * 1024


def _detect_source(filename: str, head: str) -> str:
    """按文件名与表头猜来源，命中失败走通用解析。"""
    low = filename.lower()
    if "alipay" in low or "支付宝" in filename or "交易时间,交易分类" in head:
        return "alipay"
    if "wechat" in low or "微信" in filename:
        return "wechat"
    return "generic"


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


async def _existing_keys() -> set[tuple[str, float, str]]:
    rows = await db.list_transactions()
    return {(r["date"], round(float(r["amount"]), 2), r["item"]) for r in rows}


async def import_text(
    text: str, source: str = "generic", filename: str = "", account: str = ""
) -> dict[str, Any]:
    """解析一段账单文本并入账：返回 {imported, duplicated, skipped, errors, source}。"""
    parser = get_parser(source)
    result = parser.parse(text)
    for t in result.transactions:
        if t.category in ("", "其他", "未分类"):
            t.category = auto_classify(t.item) or "其他"

    seen = await _existing_keys()
    imported = 0
    duplicated = 0
    for t in result.transactions:
        key = (t.date, round(t.amount, 2), t.item)
        if key in seen:
            duplicated += 1
            continue
        try:
            await db.add_transaction(
                date=t.date,
                item=(t.item or "未命名")[:80],
                category=(t.category or "其他")[:20],
                amount=t.amount,
            )
            seen.add(key)
            imported += 1
        except Exception as exc:  # noqa: BLE001 — 单行失败不阻断整批
            result.errors.append(f"{t.date} {t.item}: {exc}")
    if imported:
        await record_provenance(
            action="connect_import",
            entity_type="transaction",
            entity_id=f"batch:{imported}",
            before=None,
            after={"imported": imported, "duplicated": duplicated, "source": source, "file": filename},
            source="connect",
        )
    return {
        "ok": True,
        "source": source,
        "file": filename,
        "account": account,
        "imported": imported,
        "duplicated": duplicated,
        "skipped": result.skipped,
        "errors": result.errors[:20],
    }


async def scan_import_inbox() -> dict[str, Any]:
    """扫描收件目录并自动入账；处理完的文件移到 done/ 子目录。"""
    root = inbox_dir()
    done = root / "done"
    done.mkdir(parents=True, exist_ok=True)
    files = sorted(
        [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in (".csv", ".txt")],
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        return {"ok": True, "message": "收件目录没有新账单", "files": [], "imported": 0}

    outcomes = []
    total = 0
    for path in files:
        if path.stat().st_size > MAX_INBOX_FILE_BYTES:
            outcomes.append({"file": path.name, "ok": False, "error": "文件超过 20MB"})
            continue
        try:
            text = _read_text(path)
            source = _detect_source(path.name, text[:500])
            res = await import_text(text, source=source, filename=path.name)
            total += int(res.get("imported") or 0)
            outcomes.append(res)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.move(str(path), str(done / f"{stamp}-{path.name}"))
        except Exception as exc:  # noqa: BLE001 — 坏文件留在原地，等用户处理
            outcomes.append({"file": path.name, "ok": False, "error": str(exc)})
    return {
        "ok": True,
        "message": f"处理 {len(files)} 个文件，入账 {total} 笔",
        "files": outcomes,
        "imported": total,
    }
