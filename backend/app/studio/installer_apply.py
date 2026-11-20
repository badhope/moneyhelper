"""把 importer 解析出的资产条目批量落库（单条失败不拖累整包）。"""

from __future__ import annotations

from typing import Any

from . import store


async def _apply_entries(entries: list[dict[str, Any]], *, source: str) -> dict[str, Any]:
    saved: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for entry in entries:
        if "__zip_errors__" in entry:
            errors.extend(entry["__zip_errors__"])
            continue
        try:
            asset = await store.upsert_asset(entry["kind"], entry["id"], entry["asset"])
            saved.append({"kind": entry["kind"], "id": entry["id"], "name": asset.get("name", "")})
        except Exception as exc:  # noqa: BLE001 — 单条失败不拖累整包
            errors.append({"file": entry.get("source") or source, "error": str(exc)})
    return {"ok": not errors or bool(saved), "saved": saved, "errors": errors, "source": source}
