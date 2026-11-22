"""附件：上传（multipart）/ 列出 / 删除。

从 routes/system.py 拆出（M1.4 收尾）：原文件把 9 个互不相关的域塞在一起，
任何一个域的改动都要在 500+ 行里定位。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import db

router = APIRouter()

# 附件大小上限：文本/CSV 场景 2MB 足够，超过多半是误传二进制
MAX_UPLOAD_BYTES = 2 * 1024 * 1024


# ---------------------------------------------------------------------------
# 附件（P2 能力扩展）：上传 / 列出 / 删除
# ---------------------------------------------------------------------------


@router.get("/api/attachments")
async def attachments(limit: int = 50) -> dict:
    return {"attachments": await db.list_attachments(limit)}


@router.post("/api/attachments")
async def upload_attachment(request: Request) -> dict:
    """上传附件（multipart/form-data，字段 file）。文本/CSV 直接提取。

    不宣称 PDF 支持：没有 PDF 解析依赖时静默把二进制当文本是更糟的体验，
    这里明确拒绝并给出可行动的提示。
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
    # 只读上限 +1 字节：既能判断是否超限，又不会把超大文件整块读进内存。
    # 注意 Starlette 解析 multipart 时已把内容暂存到临时文件/spooled 缓冲，
    # 所以这里防的是"应用层把整个文件读进内存"，不是网络层的 body 大小
    # （后者需要反代层限制 client_max_body_size）。
    raw = await upload.read(MAX_UPLOAD_BYTES + 1)
    size = len(raw)
    if size > MAX_UPLOAD_BYTES:
        return JSONResponse(
            {"error": f"附件过大（最多 {MAX_UPLOAD_BYTES // 1024 // 1024}MB）"},
            status_code=400,
        )
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return JSONResponse(
            {"error": "暂不支持 PDF 解析，请上传 .txt / .md / .csv 文本文件"},
            status_code=415,
        )
    text = raw.decode("utf-8", errors="replace")
    if not text.strip():
        return JSONResponse(
            {"error": "无法读取该文件内容（仅支持 UTF-8 文本 / CSV）"}, status_code=400
        )
    kind = "csv" if lower.endswith(".csv") else "text"
    return await db.add_attachment(filename, kind, size, text)


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
    }


@router.post("/api/attachments/{att_id}/index")
async def index_attachment(att_id: int, payload: dict | None = None) -> dict:
    """把附件加入/移出知识库。加入后问答时会按 BM25 检索其片段。"""
    indexed = True if payload is None else bool((payload or {}).get("indexed", True))
    try:
        return await db.set_attachment_indexed(att_id, indexed)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


@router.delete("/api/attachments/{att_id}")
async def remove_attachment(att_id: int) -> dict:
    return await db.delete_attachment(att_id)
