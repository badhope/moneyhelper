"""审计追踪路由：查询操作来龙去脉 + 导出可归档的审计底稿。

端点：
- GET /api/provenance — 按实体类型/ID/时间范围过滤查询审计记录
- GET /api/provenance/{entry_id} — 查询单条审计记录详情
- GET /api/audit-report — 导出 HTML 审计底稿（浏览器可直接打印为 PDF）
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse, Response

from ..audit_report import MAX_ENTRIES, render_audit_report
from ..provenance import get_provenance_by_id, get_provenances

router = APIRouter()


@router.get("/api/provenance")
async def list_provenances(
    entity_type: str = Query(default="", description="按实体类型过滤 (position/transaction/budget/goal 等)"),
    entity_id: str = Query(default="", description="按实体 ID 过滤 (如股票代码 600519)"),
    limit: int = Query(default=50, ge=1, le=500, description="返回条数上限"),
    date_from: str = Query(default="", description="起始时间（YYYY-MM-DD 或完整 ISO）"),
    date_to: str = Query(default="", description="截止时间（YYYY-MM-DD 或完整 ISO）"),
) -> dict:
    """查询审计追踪记录。

    支持按 entity_type (实体类型)、entity_id (实体 ID) 与时间范围过滤。
    不传过滤条件时返回最新的审计记录（默认 50 条）。
    """
    rows = await get_provenances(
        entity_type=entity_type or None,
        entity_id=entity_id or None,
        limit=limit,
        date_from=date_from,
        date_to=date_to,
    )
    return {
        "count": len(rows),
        "provenances": rows,
    }


@router.get("/api/audit-report")
async def audit_report(
    entity_type: str = Query(default=""),
    entity_id: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    title: str = Query(default="Moneyhelper · 审计底稿", max_length=80),
    generated_by: str = Query(default="", max_length=40),
) -> Response:
    """导出 HTML 审计底稿。

    这是"可复核"定位的落点：任何金额操作都能导出一份带 before/after 的底稿，
    交给会计或审计方核对。HTML 而非 PDF 是为了不引入几十 MB 的渲染依赖。
    """
    rows = await get_provenances(
        entity_type=entity_type or None,
        entity_id=entity_id or None,
        limit=MAX_ENTRIES + 1,  # 多取一条用于判断是否截断
        date_from=date_from,
        date_to=date_to,
    )
    body = render_audit_report(
        rows,
        title=title,
        entity_type=entity_type,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
        generated_by=generated_by,
    )
    filename = f"moneyhelper-audit-{date_from or 'all'}-{date_to or 'now'}.html"
    return Response(
        content=body,
        media_type="text/html; charset=utf-8",
        headers={
            # 用 RFC 5987 编码文件名：中文标题不会在下载时变乱码
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            # 底稿是纯静态 HTML（内容已转义），禁掉脚本执行面
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'",
        },
    )


@router.get("/api/provenance/{entry_id}")
async def get_provenance(
    entry_id: str = Path(..., description="审计记录 UUID"),
) -> dict:
    """查询单条审计记录详情。"""
    row = await get_provenance_by_id(entry_id)
    if row is None:
        return JSONResponse({"error": "审计记录不存在", "id": entry_id}, status_code=404)
    return {"provenance": row}
