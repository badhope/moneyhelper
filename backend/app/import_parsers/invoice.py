"""发票解析：OFD（zip+XML）、PDF（可选 pypdf）、图片占位。

中国电子发票三类载体：
- **OFD**：本质是 zip，正文在 `Doc_0/Doc_1.xml` 之类的 XML 里，字段是
  `发票代码 / 发票号码 / 开票日期 / 价税合计 / 购买方名称 / 销售方名称` 等文本节点。
  用标准库 zipfile + ElementTree 就能读，不引入第三方依赖。
- **PDF**：需要文本层。装了 pypdf 才能解析；没装时明确报「不可解析」，
  而不是把二进制当文本塞进知识库。
- **图片**：本机没有 OCR 引擎，因此返回结构化「待人工录入」条目（票面字段留空），
  由前端提示用户手填或接入外部 OCR。

设计原则：解析不确定就返回 warnings，绝不编造发票号与金额。
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

MAX_BYTES = 20 * 1024 * 1024

# 发票常见字段：标签 → 归一字段名
_FIELD_ALIASES: tuple[tuple[str, str], ...] = (
    ("发票代码", "invoice_code"),
    ("发票号码", "invoice_number"),
    ("开票日期", "invoice_date"),
    ("价税合计", "total_amount"),
    ("合计金额", "amount"),
    ("合计税额", "tax_amount"),
    ("税率", "tax_rate"),
    ("购买方名称", "buyer"),
    ("销售方名称", "seller"),
    ("项目名称", "item"),
    ("校验码", "checksum"),
)

_AMOUNT_RE = re.compile(r"[¥￥]?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


@dataclass
class Invoice:
    invoice_code: str = ""
    invoice_number: str = ""
    invoice_date: str = ""
    buyer: str = ""
    seller: str = ""
    item: str = ""
    total_amount: float | None = None
    tax_amount: float | None = None
    tax_rate: str = ""
    checksum: str = ""
    kind: str = ""  # vat_special / vat_normal / electronic / unknown
    source_format: str = ""
    raw_text: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_code": self.invoice_code,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "buyer": self.buyer,
            "seller": self.seller,
            "item": self.item,
            "total_amount": self.total_amount,
            "tax_amount": self.tax_amount,
            "tax_rate": self.tax_rate,
            "checksum": self.checksum,
            "kind": self.kind,
            "source_format": self.source_format,
            "warnings": self.warnings,
            "confidence": self._confidence(),
        }

    def _confidence(self) -> str:
        """字段完整度决定置信度：号码+日期+金额齐全算 high。"""
        have = sum(1 for v in (self.invoice_number, self.invoice_date, self.total_amount) if v)
        if have == 3:
            return "high"
        if have >= 1:
            return "medium"
        return "low"


def _norm_date(text: str) -> str:
    m = _DATE_RE.search(text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def _norm_amount(text: str) -> float | None:
    m = _AMOUNT_RE.search(text.replace(" ", ""))
    if not m:
        return None
    try:
        return round(float(m.group(1).replace(",", "")), 2)
    except ValueError:
        return None


def _classify(text: str) -> str:
    if "增值税专用发票" in text:
        return "vat_special"
    if "增值税普通发票" in text or "增值税电子普通发票" in text:
        return "vat_normal"
    if "电子发票" in text:
        return "electronic"
    return "unknown"


def parse_invoice_text(text: str, source_format: str = "text") -> Invoice:
    """从纯文本里抽发票字段（OFD 抽出的 XML 文本、PDF 文本层都走这里）。"""
    inv = Invoice(source_format=source_format, raw_text=text[:4000])
    compact = re.sub(r"[ \t\r\f\v]+", " ", text)
    for label, attr in _FIELD_ALIASES:
        if getattr(inv, attr, None):
            continue
        # 允许标签与值之间有冒号、全角冒号或直接换行
        m = re.search(rf"{label}\s*[:：]?\s*([^\n]{{1,80}})", compact)
        if not m:
            continue
        raw = m.group(1).strip()
        if attr in ("total_amount", "tax_amount"):
            value = _norm_amount(raw)
            if value is not None:
                setattr(inv, attr, value)
        elif attr == "invoice_date":
            d = _norm_date(raw)
            if d:
                inv.invoice_date = d
        elif attr in ("invoice_code", "invoice_number", "checksum"):
            digits = re.sub(r"\D", "", raw)
            if digits:
                setattr(inv, attr, digits[:20])
        elif attr == "tax_rate":
            m2 = re.search(r"(\d+(?:\.\d+)?)\s*%", raw)
            if m2:
                inv.tax_rate = f"{m2.group(1)}%"
        else:
            setattr(inv, attr, raw[:60])

    inv.kind = _classify(compact)
    if not inv.invoice_number:
        inv.warnings.append("未识别到发票号码")
    if inv.total_amount is None:
        inv.warnings.append("未识别到价税合计")
    if not inv.invoice_date:
        inv.warnings.append("未识别到开票日期")
    return inv


def parse_ofd(raw: bytes) -> Invoice:
    """解析 OFD：zip 内所有 .xml 拼成文本后按普通发票文本抽取。"""
    if len(raw) > MAX_BYTES:
        return Invoice(source_format="ofd", warnings=["文件超过 20MB"])
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return Invoice(source_format="ofd", warnings=["不是合法的 OFD（zip）文件"])
    chunks: list[str] = []
    try:
        for name in zf.namelist():
            if not name.lower().endswith(".xml"):
                continue
            try:
                root = ElementTree.fromstring(zf.read(name))
            except ElementTree.ParseError:
                continue
            # 文本节点 + 属性值都要，发票字段有时放在属性里
            texts = [el.text.strip() for el in root.iter() if el.text and el.text.strip()]
            texts += [v.strip() for el in root.iter() for v in el.attrib.values() if v.strip()]
            chunks.extend(texts)
    finally:
        zf.close()
    if not chunks:
        return Invoice(source_format="ofd", warnings=["OFD 内没有可读文本（可能是纯图片版）"])
    inv = parse_invoice_text("\n".join(chunks), source_format="ofd")
    return inv


def parse_pdf(raw: bytes) -> Invoice:
    """解析 PDF 文本层（需 pypdf）。未安装时明确返回不可解析。"""
    if len(raw) > MAX_BYTES:
        return Invoice(source_format="pdf", warnings=["文件超过 20MB"])
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return Invoice(
            source_format="pdf",
            warnings=["未安装 pypdf，无法解析 PDF；可改用 OFD 或安装 pypdf 后重试"],
        )
    try:
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:5])
    except Exception as exc:  # noqa: BLE001 — 损坏 PDF 给可读错误
        return Invoice(source_format="pdf", warnings=[f"PDF 解析失败：{exc}"])
    if not text.strip():
        return Invoice(source_format="pdf", warnings=["PDF 没有文本层（扫描件），需要 OCR"])
    return parse_invoice_text(text, source_format="pdf")


def parse_invoice(raw: bytes, filename: str = "") -> Invoice:
    """按扩展名分派：.ofd / .pdf / 其他（文本）。"""
    lower = (filename or "").lower()
    if raw[:2] == b"PK" and (lower.endswith(".ofd") or lower == ""):
        return parse_ofd(raw)
    if lower.endswith(".ofd"):
        return parse_ofd(raw)
    if lower.endswith(".pdf") or raw[:4] == b"%PDF":
        return parse_pdf(raw)
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
        return Invoice(
            source_format="image",
            warnings=["本机无 OCR 引擎，无法从图片识别发票；请上传 OFD/PDF 或手动录入"],
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="replace")
    return parse_invoice_text(text, source_format="text")
