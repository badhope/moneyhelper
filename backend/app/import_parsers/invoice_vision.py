"""发票二维码 / OCR / PDF 增强识别（v4.6）：把「图片发票识别不了」这个边界补上。

三层能力，按依赖从轻到重，全部可选、全部可降级：

1. **二维码直读**（零重依赖）：中国增值税发票的二维码内容是一串逗号分隔字段，
   依次为 `01,发票代码,发票号码,金额(不含税),开票日期(YYYYMMDD),校验码,随机码`。
   拿到二维码就等于拿到最关键的四个字段，比 OCR 更准、更快。
   - 优先 `opencv-python` 的 `QRCodeDetector`（体积大但常见）；
   - 退而用 `pyzbar`（Windows 需 zbar DLL，装不上就跳过）；
   - 都不可用时返回明确提示，不假装识别。

2. **OCR 兜底**（可选重依赖）：`PaddleOCR` / `RapidOCR` / `cnocr` 任一可用即可；
   识别出的文本交给 `parse_invoice_text()` 做字段抽取（与 OFD/PDF 同一套正则），
   不重复实现字段逻辑。

3. **PDF 表格/文本**（可选）：`pdfplumber` 抽表格（银行对账单），`pypdf` 抽文本层；
   都没有时明确报「需要安装」。

为什么不做「训练发票检测模型」：发票版式随地区/年份变化，训练成本高且不可控；
二维码 + 正则 + 人工复核的组合在真实场景里准确率更高、可解释性更好。
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

# 发票二维码字段顺序（国家税务总局口径）：
# 01, 发票代码(10/12位), 发票号码(8位), 金额(不含税), 开票日期(YYYYMMDD), 校验码(后6位), 随机码
_QR_HEADER = "01"


@dataclass
class QrInvoice:
    raw: str
    invoice_code: str = ""
    invoice_number: str = ""
    amount: float | None = None
    invoice_date: str = ""
    checksum: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw[:200],
            "invoice_code": self.invoice_code,
            "invoice_number": self.invoice_number,
            "amount": self.amount,
            "invoice_date": self.invoice_date,
            "checksum": self.checksum,
            "warnings": self.warnings,
        }


def parse_invoice_qr(payload: str) -> QrInvoice:
    """解析发票二维码字符串。

    兼容两种实际形态：
    - `01,011002100311,12345678,100.00,20261015,123456,abc`
    - 带前缀的 URL 形态（部分省份）：取 `,` 分隔后仍按位解析。
    """
    raw = (payload or "").strip()
    out = QrInvoice(raw=raw)
    if not raw:
        out.warnings.append("二维码内容为空")
        return out
    parts = [p.strip() for p in raw.split(",")]
    if parts and parts[0] == _QR_HEADER:
        parts = parts[1:]
    if len(parts) < 4:
        out.warnings.append(f"二维码字段不足（{len(parts)} 段），可能不是发票码")
        return out

    out.invoice_code = re.sub(r"\D", "", parts[0])[:20]
    out.invoice_number = re.sub(r"\D", "", parts[1])[:20]
    try:
        out.amount = round(float(parts[2]), 2)
    except (TypeError, ValueError):
        out.warnings.append(f"金额字段无法解析：{parts[2]}")
    date_raw = re.sub(r"\D", "", parts[3])[:8]
    if len(date_raw) == 8:
        out.invoice_date = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
    else:
        out.warnings.append(f"日期字段无法解析：{parts[3]}")
    if len(parts) > 4:
        out.checksum = re.sub(r"\s", "", parts[4])[:12]
    if not out.invoice_number or not out.invoice_date:
        out.warnings.append("缺少发票号码或开票日期，建议人工核对")
    return out


def decode_qr_from_image(raw: bytes) -> dict[str, Any]:
    """从图片字节解出二维码内容。

    返回 {available, payload, decoder, note}：
    - available=False 表示本机没有任何解码器（不是图片问题）；
    - payload 为空表示有解码器但没找到二维码。
    """
    if not raw:
        return {"available": True, "payload": "", "decoder": "", "note": "空文件"}

    cv_error = ""
    # 1) OpenCV（最常见，识别率最高）
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            data, _points, _straight = cv2.QRCodeDetector().detectAndDecode(img)
            if data:
                return {"available": True, "payload": data, "decoder": "opencv", "note": ""}
            return {"available": True, "payload": "", "decoder": "opencv", "note": "图片中未检测到二维码"}
        return {"available": True, "payload": "", "decoder": "opencv", "note": "图片解码失败（格式不支持？）"}
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 — 解码失败换下一个解码器
        cv_error = f"{type(exc).__name__}: {exc}"
    else:
        cv_error = ""

    # 2) pyzbar（需要 zbar 动态库）
    try:
        from PIL import Image  # type: ignore
        from pyzbar.pyzbar import decode as zbar_decode  # type: ignore

        img = Image.open(io.BytesIO(raw))
        codes = zbar_decode(img)
        if codes:
            return {
                "available": True,
                "payload": codes[0].data.decode("utf-8", errors="replace"),
                "decoder": "pyzbar",
                "note": "",
            }
        return {"available": True, "payload": "", "decoder": "pyzbar", "note": "图片中未检测到二维码"}
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        return {
            "available": True,
            "payload": "",
            "decoder": "pyzbar",
            "note": f"pyzbar 不可用（Windows 常见缺 zbar DLL）：{type(exc).__name__}",
        }

    return {
        "available": False,
        "payload": "",
        "decoder": "",
        "note": "未安装二维码解码器；安装 opencv-python 或 pyzbar 后可自动识别"
        + (f"（OpenCV 报错：{cv_error}）" if cv_error else ""),
    }


def ocr_available() -> dict[str, Any]:
    """探测本机可用的 OCR 引擎。"""
    engines = []
    for name in ("paddleocr", "rapidocr_onnxruntime", "rapidocr", "cnocr", "pytesseract"):
        try:
            __import__(name)
            engines.append(name)
        except ImportError:
            continue
    return {
        "available": bool(engines),
        "engines": engines,
        "note": "" if engines else "未安装 OCR 引擎；安装 paddleocr / rapidocr-onnxruntime / cnocr 任一即可",
    }


def ocr_image(raw: bytes) -> dict[str, Any]:
    """对图片做 OCR，返回 {available, text, engine, note}。"""
    probe = ocr_available()
    if not probe["available"]:
        return {"available": False, "text": "", "engine": "", "note": probe["note"]}

    # RapidOCR：体积小、离线、API 简单，优先
    if "rapidocr_onnxruntime" in probe["engines"] or "rapidocr" in probe["engines"]:
        try:
            if "rapidocr_onnxruntime" in probe["engines"]:
                from rapidocr_onnxruntime import RapidOCR  # type: ignore
            else:
                from rapidocr import RapidOCR  # type: ignore
            engine = RapidOCR()
            result, _ = engine(raw)
            text = "\n".join(item[1] for item in (result or []) if len(item) > 1)
            return {"available": True, "text": text, "engine": "rapidocr", "note": ""}
        except Exception as exc:  # noqa: BLE001 — 换下一个引擎
            rapid_error = f"{type(exc).__name__}: {exc}"
    else:
        rapid_error = ""

    if "paddleocr" in probe["engines"]:
        try:
            from paddleocr import PaddleOCR  # type: ignore

            ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
            import numpy as np  # type: ignore
            from PIL import Image  # type: ignore

            arr = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
            result = ocr.ocr(arr, cls=True)
            lines: list[str] = []
            for page in result or []:
                for row in page or []:
                    if len(row) > 1 and isinstance(row[1], (list, tuple)):
                        lines.append(str(row[1][0]))
            return {"available": True, "text": "\n".join(lines), "engine": "paddleocr", "note": ""}
        except Exception as exc:  # noqa: BLE001
            paddle_error = f"{type(exc).__name__}: {exc}"
    else:
        paddle_error = ""

    return {
        "available": False,
        "text": "",
        "engine": "",
        "note": f"OCR 引擎调用失败（rapid={rapid_error or 'N/A'}，paddle={paddle_error or 'N/A'}）",
    }


def extract_pdf_tables(raw: bytes) -> dict[str, Any]:
    """用 pdfplumber 抽 PDF 表格（银行对账单场景）。"""
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return {
            "available": False,
            "tables": [],
            "note": "未安装 pdfplumber；安装后可解析 PDF 表格对账单",
        }
    try:
        tables: list[list[list[str]]] = []
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages[:10]:
                for table in page.extract_tables() or []:
                    rows = [[(c or "").strip() for c in row] for row in table if any(row)]
                    if len(rows) >= 2:
                        tables.append(rows)
        return {"available": True, "tables": tables, "note": "" if tables else "PDF 中没有识别到表格"}
    except Exception as exc:  # noqa: BLE001
        return {"available": True, "tables": [], "note": f"PDF 表格解析失败：{type(exc).__name__}: {exc}"}


def invoice_from_image(raw: bytes) -> dict[str, Any]:
    """图片发票一体化识别：先二维码（准），再 OCR（全）。

    返回：
      {ok, method, invoice:{...}, qr:{...}, ocr_text, warnings, install_hint}
    """
    from .invoice import parse_invoice_text

    warnings: list[str] = []
    qr_info = decode_qr_from_image(raw)
    qr_parsed = None
    if qr_info.get("payload"):
        qr_parsed = parse_invoice_qr(qr_info["payload"])
        warnings.extend(qr_parsed.warnings)

    ocr_info = ocr_image(raw)
    ocr_parsed = None
    if ocr_info.get("text"):
        ocr_parsed = parse_invoice_text(ocr_info["text"], source_format="image-ocr")

    if qr_parsed and qr_parsed.invoice_number:
        data = qr_parsed.to_dict()
        # 字段名对齐：二维码叫 amount，发票归档表叫 total_amount（漏映射会导致金额丢失）
        if data.get("amount") is not None and not data.get("total_amount"):
            data["total_amount"] = data["amount"]
        data.setdefault("kind", "vat_normal")
        data.setdefault("source_format", "image-qr")
        data.setdefault("confidence", "high" if data.get("invoice_code") else "medium")
        # OCR 只用来补二维码没有的字段（购买方/销售方/税额），不覆盖更可信的二维码值
        if ocr_parsed:
            for key in ("buyer", "seller", "item", "tax_amount", "tax_rate"):
                value = getattr(ocr_parsed, key, None)
                if value and not data.get(key):
                    data[key] = value
        return {
            "ok": True,
            "method": f"qr+{qr_info.get('decoder') or 'ocr'}",
            "invoice": data,
            "qr": qr_info,
            "ocr_text": (ocr_info.get("text") or "")[:2000],
            "warnings": warnings,
            "install_hint": "",
        }

    if ocr_parsed:
        data = ocr_parsed.to_dict()
        return {
            "ok": bool(data.get("invoice_number") or data.get("total_amount")),
            "method": f"ocr:{ocr_info.get('engine')}",
            "invoice": data,
            "qr": qr_info,
            "ocr_text": (ocr_info.get("text") or "")[:2000],
            "warnings": data.get("warnings", []),
            "install_hint": "",
        }

    hints = []
    if not qr_info.get("available"):
        hints.append("安装 opencv-python 可自动读取发票二维码（最准）")
    if not ocr_info.get("available"):
        hints.append("安装 rapidocr-onnxruntime 可离线识别发票文字")
    return {
        "ok": False,
        "method": "",
        "invoice": {},
        "qr": qr_info,
        "ocr_text": "",
        "warnings": [qr_info.get("note") or "", ocr_info.get("note") or ""],
        "install_hint": "；".join(h for h in hints if h) or "建议上传 OFD/PDF，或手动粘贴票面文本",
    }
