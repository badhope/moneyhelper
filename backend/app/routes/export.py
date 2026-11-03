"""数据导出 / 备份恢复 / CSV 导出。

从 routes/system.py 拆出（M1.4 收尾）：原文件把 9 个互不相关的域塞在一起，
任何一个域的改动都要在 500+ 行里定位。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from .. import backup, db
from ..logging_utils import get_logger as _get_logger
from .settings import _mask_secret

log = _get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# 数据导出 / 导入恢复 / CSV 导出
# ---------------------------------------------------------------------------


@router.get("/api/export")
async def export_data(passphrase: str | None = None) -> dict:
    """全量导出：无口令 → 明文 JSON（兼容旧版）；有口令 → 加密备份包（推荐）。"""
    data = await db.export_data()
    _mask_secret(data.get("settings", {}))
    if passphrase:
        return backup.encrypt_export(data, passphrase)
    return data


@router.post("/api/import/backup")
async def import_backup(payload: dict) -> dict:
    """从 /api/export 的 JSON 恢复全量数据（AI Key 除外，需重新填写）。

    加密备份包（encrypted=true）必须携带 passphrase 字段，口令错误会拒绝并回滚。
    """
    from ..quotes import invalidate_quotes_cache

    payload = payload or {}
    if not isinstance(payload, dict):
        return JSONResponse({"error": "备份格式不正确"}, status_code=400)
    if payload.get("encrypted"):
        passphrase = str(payload.get("passphrase") or "")
        if not passphrase:
            return JSONResponse({"error": "加密备份需要口令"}, status_code=400)
        try:
            data = backup.decrypt_export(payload, passphrase)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
    else:
        data = payload
    version = str((data.get("meta") or {}).get("version") or data.get("version") or "")
    # 2 = 旧版（无家庭成员/审计），3 = 当前版。两者都能恢复，向后兼容。
    if not (version.startswith(("wealth-office-v", "moneyhelper-v")) or version in ("2", "3")):
        return JSONResponse(
            {"error": f"备份格式不被识别（version={version or '空'}）"}, status_code=400
        )
    try:
        counts = await db.import_backup(data)
    except Exception as exc:  # noqa: BLE001 — 恢复失败要回滚并给可读错误
        log.exception("import backup failed")
        return JSONResponse({"error": f"恢复失败，数据已回滚：{exc}"}, status_code=400)
    await invalidate_quotes_cache()
    return {"ok": True, "counts": counts}


@router.get("/api/export/csv")
async def export_csv() -> StreamingResponse:
    """流水导出为 CSV（带 BOM，Excel 直接打开不乱码）。"""
    import csv
    import io

    rows = await db.list_transactions()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["日期", "项目", "分类", "金额"])

    # 防 CSV 公式注入：以 = + - @ 开头的单元格加单引号前缀，避免 Excel 打开执行公式
    def _safe(v: str) -> str:
        v = str(v or "")
        return "'" + v if v and v[0] in "=+-@" else v

    for r in rows:
        writer.writerow(
            [
                _safe(r["date"]),
                _safe(r["item"]),
                _safe(r["category"]),
                _safe(r["amount"]),
            ]
        )
    data = "\ufeff" + buf.getvalue()
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="ledger.csv"'},
    )


@router.get("/api/export/report")
async def export_report(lang: str = "zh") -> Response:
    """导出单文件 HTML 报告（自包含、离线可看、可打印为 PDF）。

    数据源与总览一致（同一 collect_dashboard 口径），不额外联网。
    """
    from datetime import datetime

    from fastapi.responses import Response

    from .. import analysis
    from ..report import build_report

    dash = await analysis.collect_dashboard(lang, use_cache=True)
    accounts = None
    try:
        from .paper import accounts_overview

        accounts = await accounts_overview(lang)
    except Exception:  # noqa: BLE001 — 合并视图失败不阻断报告主体
        accounts = None
    actions = dash.get("actions")
    title = "财务报告" if not str(lang).lower().startswith("en") else "Financial report"
    html = build_report(
        dashboard=dash,
        accounts=accounts,
        actions=actions if isinstance(actions, dict) else None,
        title=title,
        lang=lang,
        generated_at=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
    )
    filename = "moneyhelper-report-%s.html" % datetime.now().strftime("%Y%m%d")
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="%s"' % filename},
    )
