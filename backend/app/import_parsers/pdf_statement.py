"""PDF 对账单/流水解析（v4.6）：把「银行只给 PDF」这个边界补上。

两条路径：
1. **文本层表格**（pdfplumber）：电子对账单通常是表格结构，直接抽表格 → 复用通用 CSV 列映射。
2. **文本行回退**：没有表格结构但文本层可读时，按「日期 + 摘要 + 金额」的宽松规则抽行
   （与书签回传共用同一套抽取逻辑，避免两套规则漂移）。

明确不做：扫描件 OCR。扫描件没有任何文本层，属于 OCR 场景，由 invoice_vision 的
`ocr_image()` 处理，不要在这里把二进制当文本读。

所有失败都返回结构化 warnings + 安装提示，绝不抛 500。
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

MAX_PAGES = 30

# 表头关键词 → 语义（与 csvimport 的 detect_mapping 同口径）
_DATE_KEYS = ("交易日期", "记账日期", "日期", "交易时间", "时间", "date")
_DESC_KEYS = ("摘要", "对方户名", "交易对方", "用途", "备注", "商品", "说明", "description", "memo")
_AMOUNT_KEYS = ("金额", "交易金额", "发生额", "收支金额", "amount")
_INCOME_KEYS = ("收入", "贷方", "转入", "credit")
_EXPENSE_KEYS = ("支出", "借方", "转出", "debit")


@dataclass
class PdfRow:
    date: str
    item: str
    amount: float
    category: str = "其他"
    raw: list[str] = field(default_factory=list)


@dataclass
class PdfStatementResult:
    rows: list[PdfRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    method: str = ""
    pages: int = 0

    def to_preview(self) -> dict[str, Any]:
        return {
            "rows": [
                {"date": r.date, "item": r.item, "amount": r.amount, "category": r.category}
                for r in self.rows
            ],
            "count": len(self.rows),
            "method": self.method,
            "pages": self.pages,
            "warnings": self.warnings,
        }


def _norm_date(text: str) -> str | None:
    """把 PDF 里常见的日期写法归一成 YYYY-MM-DD。"""
    raw = str(text or "").strip()
    if not raw:
        return None
    m = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _norm_amount(text: str) -> float | None:
    """金额归一：支持千分位、括号负数、尾部「-」表示支出。"""
    raw = str(text or "").strip()
    if not raw:
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[¥￥,\s]", "", raw.strip("()"))
    m = re.search(r"([+-]?\d+(?:\.\d{1,2})?)", cleaned)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    if negative:
        value = -abs(value)
    elif cleaned.rstrip().endswith("-"):
        value = -abs(value)
    return round(value, 2)


def _pick_col(header: list[str], keys: tuple[str, ...]) -> int:
    norm = [re.sub(r"[\s（）()]", "", str(c)).lower() for c in header]
    for k in keys:
        kk = re.sub(r"[\s（）()]", "", k).lower()
        for i, cell in enumerate(norm):
            if kk and kk in cell:
                return i
    return -1


def _rows_from_table(table: list[list[str]], result: PdfStatementResult) -> int:
    """从一张表格里抽交易行；返回抽到的条数。"""
    if len(table) < 2:
        return 0
    header = table[0]
    di = _pick_col(header, _DATE_KEYS)
    si = _pick_col(header, _DESC_KEYS)
    ai = _pick_col(header, _AMOUNT_KEYS)
    inc = _pick_col(header, _INCOME_KEYS)
    exp = _pick_col(header, _EXPENSE_KEYS)

    if di < 0 or (ai < 0 and inc < 0 and exp < 0):
        return 0

    added = 0
    for row in table[1:]:
        if not row or not any(str(c).strip() for c in row):
            continue
        dtxt = row[di] if di < len(row) else ""
        d = _norm_date(dtxt)
        if not d:
            continue
        amount = _norm_amount(row[ai]) if 0 <= ai < len(row) else None
        if amount is None:
            inc_v = _norm_amount(row[inc]) if 0 <= inc < len(row) else None
            exp_v = _norm_amount(row[exp]) if 0 <= exp < len(row) else None
            if inc_v:
                amount = abs(inc_v)
            elif exp_v:
                amount = -abs(exp_v)
        if amount is None or amount == 0:
            continue
        desc = str(row[si]).strip() if 0 <= si < len(row) else ""
        result.rows.append(
            PdfRow(date=d, item=(desc or "PDF 导入")[:80], amount=amount, raw=[str(c) for c in row])
        )
        added += 1
    return added


def _rows_from_text(text: str, result: PdfStatementResult) -> int:
    """无表格时的文本行回退：日期 + 描述 + 金额。"""
    added = 0
    for line in text.splitlines():
        raw = line.strip()
        if len(raw) < 8 or len(raw) > 300:
            continue
        d = _norm_date(raw)
        if not d:
            continue
        tail = raw[raw.find(d[-2:]) + 2 :] if d[-2:] in raw else raw
        amounts = re.findall(r"[+-]?\s*[¥￥]?\s*\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|[+-]?\s*[¥￥]?\s*\d+(?:\.\d{1,2})?", tail)
        if not amounts:
            continue
        value = _norm_amount(amounts[-1])
        if value is None or value == 0:
            continue
        desc = re.sub(r"[+-]?\s*[¥￥]?\s*[\d,]+\.\d{1,2}", "", raw)
        desc = re.sub(r"\s+", " ", desc).strip(" ,，|")[:80] or "PDF 导入"
        result.rows.append(PdfRow(date=d, item=desc, amount=value, raw=[raw]))
        added += 1
        if len(result.rows) >= 2000:
            break
    return added


def parse_pdf_statement(raw: bytes) -> PdfStatementResult:
    """解析 PDF 对账单：先抽表格，再回退文本行。"""
    result = PdfStatementResult()
    if not raw:
        result.warnings.append("文件为空")
        return result
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        result.warnings.append(
            "未安装 pdfplumber，无法解析 PDF 对账单；安装后重试：pip install pdfplumber"
        )
        return result

    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            result.pages = min(len(pdf.pages), MAX_PAGES)
            all_text: list[str] = []
            for page in pdf.pages[:MAX_PAGES]:
                for table in page.extract_tables() or []:
                    rows = [[(c or "").strip() for c in row] for row in table if any(row)]
                    if rows:
                        _rows_from_table(rows, result)
                text = page.extract_text() or ""
                if text:
                    all_text.append(text)
    except Exception as exc:  # noqa: BLE001 — 损坏 PDF 给可读错误
        result.warnings.append(f"PDF 解析失败：{type(exc).__name__}: {exc}")
        return result

    if result.rows:
        result.method = "table"
    else:
        added = _rows_from_text("\n".join(all_text), result)
        result.method = "text" if added else ""
        if not added:
            result.warnings.append(
                "PDF 中既没有可识别的表格也没有可解析的流水行；若是扫描件，请改用图片识别（OCR）"
            )
    if result.rows:
        from ..csvimport import classify as auto_classify

        for row in result.rows:
            row.category = auto_classify(row.item) or "其他"
    return result


def statement_reconcile(rows: list[dict[str, Any]], ledger: list[dict[str, Any]]) -> dict[str, Any]:
    """对账单与账本核对：找出「账本有对账单没有」「对账单有账本没有」的差异。

    匹配口径：日期 + 金额（保留 2 位）。摘要不参与匹配——银行摘要与用户记账摘要
    几乎不可能一致，强行匹配会制造大量假差异。
    """
    def key(r: dict[str, Any]) -> tuple[str, float]:
        return (str(r.get("date") or ""), round(float(r.get("amount") or 0), 2))

    stmt_keys = {}
    for r in rows:
        stmt_keys.setdefault(key(r), []).append(r)
    ledger_keys = {}
    for r in ledger:
        ledger_keys.setdefault(key(r), []).append(r)

    missing_in_ledger = []
    for k, items in stmt_keys.items():
        diff = len(items) - len(ledger_keys.get(k, []))
        for _ in range(max(0, diff)):
            missing_in_ledger.append(items[0])

    missing_in_statement = []
    for k, items in ledger_keys.items():
        diff = len(items) - len(stmt_keys.get(k, []))
        for _ in range(max(0, diff)):
            missing_in_statement.append(items[0])

    return {
        "statement_count": len(rows),
        "ledger_count": len(ledger),
        "matched": sum(min(len(v), len(ledger_keys.get(k, []))) for k, v in stmt_keys.items()),
        "missing_in_ledger": missing_in_ledger[:100],
        "missing_in_statement": missing_in_statement[:100],
        "balanced": not missing_in_ledger and not missing_in_statement,
        "note": "按「日期+金额」匹配；摘要不参与，避免假差异",
    }


__all__ = [
    "PdfRow",
    "PdfStatementResult",
    "parse_pdf_statement",
    "statement_reconcile",
]
