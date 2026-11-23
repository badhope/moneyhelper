"""附件：上传（multipart）/ 列出 / 删除。

从 routes/system.py 拆出（M1.4 收尾）：原文件把 9 个互不相关的域塞在一起，
任何一个域的改动都要在 500+ 行里定位。
"""

from __future__ import annotations

import base64
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import db
from ..attachment_text import CONTENT_MAX_CHARS, extract_pdf_text

router = APIRouter()

# 文本 / CSV：2MB 足够；图片 / PDF 单独放宽到 8MB，仍不把整块读进内存两次
MAX_TEXT_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_BINARY_UPLOAD_BYTES = 8 * 1024 * 1024

# 只接受浏览器能安全内联渲染的类型；SVG 明确排除（可携带脚本）
BINARY_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
}


def _matches_type(raw: bytes, ext: str) -> bool:
    """扩展名与文件头必须一致，避免把 exe/HTML 改名成 png 后内联执行。"""
    if ext == ".pdf":
        return raw.startswith(b"%PDF-")
    if ext == ".png":
        return raw.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in {".jpg", ".jpeg"}:
        return raw.startswith(b"\xff\xd8\xff")
    if ext == ".gif":
        return raw.startswith(b"GIF87a") or raw.startswith(b"GIF89a")
    if ext == ".webp":
        return raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    return False


# ---------------------------------------------------------------------------
# 附件（P2 能力扩展）：上传 / 列出 / 删除
# ---------------------------------------------------------------------------


@router.get("/api/attachments")
async def attachments(limit: int = 50) -> dict:
    items = await db.list_attachments(limit)
    for item in items:
        item["has_data"] = bool(item.get("has_data"))
        item["has_text"] = bool(item.get("has_text"))
    return {"attachments": items}


@router.get("/api/attachments/search")
async def search_attachments(q: str = "", limit: int = 30) -> dict:
    query = q.strip()[:200]
    if not query:
        return {"results": []}
    return {"results": await db.search_attachments(query, limit)}


@router.post("/api/attachments")
async def upload_attachment(request: Request) -> dict:
    """上传附件（multipart/form-data，字段 file）。

    文本 / CSV 提取正文；PDF 抽取文本层，扫描件则保留空正文并给出说明；
    PNG/JPG/WEBP/GIF/PDF 原始字节仍存 base64，供工作台预览与下载。
    图片不参与知识库检索，避免把 base64 当正文喂给模型。
    """
    content_type = (request.headers.get("content-type") or "").lower()
    if not content_type.startswith("multipart/form-data"):
        return JSONResponse(
            {"error": "请使用 multipart/form-data 上传（字段名 file）"}, status_code=400
        )
    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001 — 表单解析失败给可读错误
        return JSONResponse({"error": f"表单解析失败：{exc}"}, status_code=400)
    upload = form.get("file")
    if upload is None or not hasattr(upload, "filename"):
        return JSONResponse({"error": "缺少 file 字段"}, status_code=400)
    filename = str(upload.filename or "未命名")
    lower = filename.lower()
    ext = "." + lower.rsplit(".", 1)[-1] if "." in lower else ""

    if ext in BINARY_TYPES:
        raw = await upload.read(MAX_BINARY_UPLOAD_BYTES + 1)
        size = len(raw)
        if size > MAX_BINARY_UPLOAD_BYTES:
            return JSONResponse(
                {"error": f"附件过大（图片/PDF 最多 {MAX_BINARY_UPLOAD_BYTES // 1024 // 1024}MB）"},
                status_code=400,
            )
        if not raw:
            return JSONResponse({"error": "文件为空"}, status_code=400)
        if not _matches_type(raw, ext):
            return JSONResponse(
                {"error": "文件内容与扩展名不一致，已拒绝（仅支持真实 PNG/JPG/WEBP/GIF/PDF）"},
                status_code=415,
            )
        kind = "pdf" if ext == ".pdf" else "image"
        text = ""
        text_note = ""
        if kind == "pdf":
            # pypdf 是同步 CPU 活；放线程池，别让一份 8MB 合同卡住整条事件循环
            text, text_note = await run_in_threadpool(extract_pdf_text, raw, CONTENT_MAX_CHARS)
        saved = await db.add_binary_attachment(
            filename,
            kind,
            size,
            BINARY_TYPES[ext],
            base64.b64encode(raw).decode("ascii"),
            content=text,
        )
        return {
            **saved,
            "kind": kind,
            "mime": BINARY_TYPES[ext],
            "text_extracted": bool(text),
            "text_note": text_note,
        }

    raw = await upload.read(MAX_TEXT_UPLOAD_BYTES + 1)
    size = len(raw)
    if size > MAX_TEXT_UPLOAD_BYTES:
        return JSONResponse(
            {"error": f"附件过大（最多 {MAX_TEXT_UPLOAD_BYTES // 1024 // 1024}MB）"},
            status_code=400,
        )
    text = raw.decode("utf-8", errors="replace")
    if not text.strip():
        return JSONResponse(
            {"error": "无法读取该文件内容（支持 UTF-8 文本 / CSV / 图片 / PDF）"}, status_code=400
        )
    kind = "csv" if lower.endswith(".csv") else "text"
    # 正文截 6000 字只用于预览/检索；原始字节另存，下载出来的才是完整文件。
    saved = await db.add_attachment(
        filename,
        kind,
        size,
        text,
        mime="text/plain; charset=utf-8",
        data_b64=base64.b64encode(raw).decode("ascii"),
    )
    return {**saved, "kind": kind, "mime": "text/plain; charset=utf-8"}


@router.get("/api/attachments/{att_id}")
async def attachment_detail(att_id: int) -> dict:
    """单个附件正文：右侧工作台的「预览」读这里。

    列表接口只回元数据（文件名/大小/时间），正文可能 6000 字；把所有正文
    塞进列表会让文件栏越用越慢。这里按需取，并且只回预览需要的字段。
    """
    row = await db.get_attachment(int(att_id))
    if not row:
        return JSONResponse({"error": "附件不存在"}, status_code=404)
    return {
        "id": row["id"],
        "filename": row["filename"],
        "kind": row["kind"],
        "size": row["size"],
        "indexed": row["indexed"],
        "created_at": row["created_at"],
        "content": row["content"],
        "mime": row.get("mime", ""),
        "has_data": bool(row.get("data")),
    }


@router.get("/api/attachments/{att_id}/raw")
async def attachment_raw(att_id: int) -> Response:
    """原始字节：图片/PDF 预览与下载。

    只返回数据库里已校验过的受限 MIME；不允许 SVG/HTML 等可执行内容内联。
    """
    row = await db.get_attachment_blob(int(att_id))
    if not row or not row.get("data"):
        return JSONResponse({"error": "附件不存在或没有原始数据"}, status_code=404)
    try:
        payload = base64.b64decode(row["data"], validate=True)
    except Exception:  # noqa: BLE001 — 数据损坏给 404 而不是崩
        return JSONResponse({"error": "附件数据损坏"}, status_code=404)
    name = quote(str(row.get("filename") or "attachment"))
    return Response(
        content=payload,
        media_type=str(row.get("mime") or "application/octet-stream"),
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{name}",
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/api/attachments/{att_id}/index")
async def index_attachment(att_id: int, payload: dict | None = None) -> dict:
    """把附件加入/移出知识库。加入后问答时会按 BM25 检索其片段。"""
    indexed = True if payload is None else bool((payload or {}).get("indexed", True))
    if indexed:
        row = await db.get_attachment(att_id)
        if not row:
            return JSONResponse({"error": "附件不存在"}, status_code=404)
        if not str(row.get("content") or "").strip():
            return JSONResponse(
                {"error": "该附件没有可检索正文，无法加入知识库（扫描件请先做图片识别）"},
                status_code=400,
            )
    try:
        return await db.set_attachment_indexed(att_id, indexed)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


@router.delete("/api/attachments/{att_id}")
async def remove_attachment(att_id: int) -> dict:
    return await db.delete_attachment(att_id)
