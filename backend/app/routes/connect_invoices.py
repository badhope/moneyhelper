"""连接中心·发票：上传（文本/图片/PDF 文本层）、识别、列表与增删改。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import db
from ..auth import get_current_user
from ._responses import bad as _bad

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.post("/api/connect/invoices")
async def upload_invoice(request: Request) -> Any:
    """上传发票（multipart，字段 file）：OFD / PDF / 文本；同一文件幂等。"""
    from ..import_parsers.invoice import parse_invoice

    content_type = (request.headers.get("content-type") or "").lower()
    if not content_type.startswith("multipart/form-data"):
        return _bad("请使用 multipart/form-data 上传（字段名 file）")
    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001
        return _bad(f"表单解析失败：{exc}")
    upload = form.get("file")
    if upload is None or not hasattr(upload, "filename"):
        return _bad("缺少 file 字段")
    raw = await upload.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        return _bad("发票文件超过 20MB")
    # pypdf/OFD 解析是 CPU 密集的同步调用：直接跑会独占事件循环，
    # 让并发的 SSE 问答与轮询全部停摆（本仓库对 CPU-bound 一律 to_thread，
    # 见 vault.py / routes/export.py）。
    parsed = await asyncio.to_thread(parse_invoice, raw, str(upload.filename or ""))
    record = await db.save_invoice(
        file_name=str(upload.filename or "invoice"),
        raw=raw,
        parsed=parsed.to_dict(),
    )
    return {
        "ok": True,
        "invoice": record,
        "parsed": parsed.to_dict(),
        "duplicate": record.get("duplicate", False),
    }


@router.post("/api/connect/invoices/text")
async def upload_invoice_text(payload: dict[str, Any]) -> Any:
    """粘贴票面文本解析（无文件场景）。"""
    from ..import_parsers.invoice import parse_invoice_text

    text = str((payload or {}).get("text") or "")
    if not text.strip():
        return _bad("请粘贴发票票面文本")
    parsed = parse_invoice_text(text)
    record = await db.save_invoice(
        file_name=str((payload or {}).get("file_name") or "invoice-text"),
        raw=text.encode("utf-8"),
        parsed=parsed.to_dict(),
    )
    return {
        "ok": True,
        "invoice": record,
        "parsed": parsed.to_dict(),
        "duplicate": record.get("duplicate", False),
    }


@router.get("/api/connect/invoices")
async def list_invoices(status: str = "", limit: int = 100) -> dict[str, Any]:
    return {"items": await db.list_invoices(limit, status), "summary": await db.invoice_summary()}


@router.patch("/api/connect/invoices/{iid}")
async def patch_invoice(iid: str, payload: dict[str, Any]) -> Any:
    try:
        return await db.update_invoice_status(
            iid,
            str((payload or {}).get("status") or "archived"),
            str((payload or {}).get("note") or ""),
        )
    except ValueError as exc:
        return _bad(str(exc), 404)


@router.delete("/api/connect/invoices/{iid}")
async def remove_invoice(iid: str) -> dict[str, Any]:
    ok = await db.delete_invoice(iid)
    if not ok:
        raise HTTPException(404, "发票不存在")
    return {"deleted": iid}


# ---------------------------------------------------------------------------
# 条件单
# ---------------------------------------------------------------------------

@router.post("/api/connect/invoices/image")
async def upload_invoice_image(request: Request) -> Any:
    """图片发票识别：先读二维码（最准），再 OCR 兜底；都不行时给安装提示。"""
    from ..import_parsers.invoice_vision import invoice_from_image

    content_type = (request.headers.get("content-type") or "").lower()
    if not content_type.startswith("multipart/form-data"):
        return _bad("请使用 multipart/form-data 上传（字段名 file）")
    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001
        return _bad(f"表单解析失败：{exc}")
    upload = form.get("file")
    if upload is None or not hasattr(upload, "filename"):
        return _bad("缺少 file 字段")
    raw = await upload.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        return _bad("图片超过 20MB")

    # 二维码解码 + tesseract OCR 均为阻塞调用（秒级），必须推入线程池。
    result = await asyncio.to_thread(invoice_from_image, raw)
    if not result["ok"]:
        return {
            "ok": False,
            "method": result["method"],
            "invoice": {},
            "warnings": [w for w in result["warnings"] if w],
            "install_hint": result["install_hint"],
        }
    record = await db.save_invoice(
        file_name=str(upload.filename or "invoice-image"),
        raw=raw,
        parsed=result["invoice"],
    )
    return {
        "ok": True,
        "method": result["method"],
        "invoice": record,
        "parsed": result["invoice"],
        "qr": result["qr"],
        "duplicate": record.get("duplicate", False),
        "install_hint": result["install_hint"],
    }


@router.get("/api/connect/invoices/vision/status")
async def vision_status() -> dict[str, Any]:
    """发票视觉能力探测：二维码解码器 / OCR 引擎 / PDF 表格是否可用。"""
    from ..import_parsers.invoice_vision import ocr_available
    from ..import_parsers.pdf_statement import parse_pdf_statement  # noqa: F401

    qr = {"available": False, "decoders": []}
    for name, module in (("opencv", "cv2"), ("pyzbar", "pyzbar.pyzbar")):
        try:
            __import__(module)
            qr["available"] = True
            qr["decoders"].append(name)
        except ImportError:
            continue
    pdf_available = False
    try:
        import pdfplumber  # type: ignore  # noqa: F401

        pdf_available = True
    except ImportError:
        pass
    ocr = ocr_available()
    return {
        "qr": qr,
        "ocr": ocr,
        "pdf_tables": {
            "available": pdf_available,
            "note": "" if pdf_available else "安装 pdfplumber 可解析 PDF 表格对账单",
        },
        "hint": "三者全不可用时仍可用 OFD/PDF 文本层/手动粘贴",
    }
