"""连接中心·持仓导入：券商持仓/对账单合并与导入历史。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import db
from ..auth import get_current_user
from ._responses import bad as _bad

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.post("/api/connect/import/holdings")
async def import_holdings(payload: dict[str, Any]) -> Any:
    """解析券商持仓/对账单并（可选）合并进持仓表。

    content 传 CSV 文本；apply=true 时按 symbol upsert。
    同一文件内容重复导入会被 record_brokerage_import 识别为 duplicate。
    """
    from ..analysis import invalidate_dashboard_cache
    from ..import_parsers.broker_holdings import parse_holdings
    from ..provenance import record_provenance

    payload = payload or {}
    content = str(payload.get("content") or "")
    if not content.strip():
        return _bad("请粘贴券商导出的持仓 CSV 内容")
    result = parse_holdings(content)
    preview = result.to_preview()
    if not payload.get("apply"):
        return {"ok": True, **preview}

    applied = 0
    errors: list[str] = []
    for p in result.positions:
        try:
            await db.add_position(
                {
                    "symbol": p.symbol,
                    "name": p.name,
                    "kind": p.kind,
                    "industry": "未分类",
                    "shares": p.shares,
                    "cost": p.cost,
                    "last": p.last,
                }
            )
            applied += 1
        except Exception as exc:  # noqa: BLE001 — 单行失败不阻断整批
            errors.append(f"{p.symbol} {p.name}: {exc}")

    record = await db.record_brokerage_import(
        file_name=str(payload.get("file_name") or "holdings.csv"),
        raw=content.encode("utf-8"),
        account=result.account,
        position_count=len(result.positions),
        applied=applied,
        warnings=result.warnings + errors,
    )
    await record_provenance(
        action="import_brokerage_holdings",
        entity_type="position",
        entity_id=f"batch:{applied}",
        before=None,
        after={"applied": applied, "count": len(result.positions), "account": result.account},
        source="connect",
    )
    invalidate_dashboard_cache()
    return {"ok": True, **preview, "applied": applied, "errors": errors, "record": record}


@router.get("/api/connect/import/holdings/history")
async def holdings_import_history(limit: int = 30) -> dict[str, Any]:
    return {"items": await db.list_brokerage_imports(limit)}


# ---------------------------------------------------------------------------
# 发票归档
# ---------------------------------------------------------------------------


