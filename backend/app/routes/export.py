"""数据导出 / 备份恢复 / CSV 导出。

从 routes/system.py 拆出（M1.4 收尾）：原文件把 9 个互不相关的域塞在一起，
任何一个域的改动都要在 500+ 行里定位。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .. import auth, backup, db
from ..artifact_export import docx_bytes, html_document
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
        # PBKDF2 600k 次派生是纯 CPU 同步操作，直接在 async 里跑会卡住
        # 整个事件循环（期间所有请求含 SSE 心跳一起停摆）。丢到线程池。
        import asyncio

        return await asyncio.to_thread(backup.encrypt_export, data, passphrase)
    return data


@router.post("/api/import/backup")
async def import_backup(
    payload: dict,
    _admin: dict = Depends(auth.require_instance_admin),
) -> dict:
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
        # 金额不套 _safe：负数是支出常态，加前导单引号会让 Excel 整列变文本、
        # SUM 全为 0（实测 '-35.5）。数字本身也不可能被当成公式执行。
        writer.writerow(
            [
                _safe(r["date"]),
                _safe(r["item"]),
                _safe(r["category"]),
                r["amount"],
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
    filename = f"moneyhelper-report-{datetime.now().strftime('%Y%m%d')}.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _artifact_filename(title: str, ext: str) -> str:
    """附件名：ASCII 回退 + RFC 5987，中文标题在浏览器里也能保留。"""
    import re
    from urllib.parse import quote

    base = re.sub(r'[\\/:*?"<>|\r\n]+', "-", str(title or "canvas")).strip()[:80] or "canvas"
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-")[:80] or "canvas"
    return f"attachment; filename=\"{fallback}.{ext}\"; filename*=UTF-8''{quote(base + '.' + ext)}"


@router.post("/api/canvas/export")
async def export_canvas(payload: dict = Body(...)) -> Response:
    """回答画布导出：Markdown / HTML / Word 三档，不新增独立产物页面。

    HTML 与 DOCX 都走共享安全渲染；DOCX 用标准库生成，不把 python-docx /
    reportlab 塞进运行时依赖，保持轻量安装。
    """
    title = str((payload or {}).get("title") or "").strip()[:120] or "未命名文档"
    body = str((payload or {}).get("body") or "")
    if len(body) > 200_000:
        return JSONResponse({"error": "正文过长（最多 20 万字符）"}, status_code=400)
    fmt = str((payload or {}).get("format") or "md").strip().lower()
    if fmt == "md":
        return Response(
            body.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": _artifact_filename(title, "md")},
        )
    if fmt == "html":
        return Response(
            html_document(title, body).encode("utf-8"),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": _artifact_filename(title, "html")},
        )
    if fmt == "docx":
        return Response(
            docx_bytes(title, body),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": _artifact_filename(title, "docx")},
        )
    return JSONResponse({"error": "不支持的导出格式"}, status_code=400)
