"""账单 CSV 解析与列映射：解析常见平台导出格式（微信/支付宝/银行 CSV、Excel 另存的 UTF-8 CSV）。

流程：parse_csv 拆出表头+行 → detect_mapping 按表头关键词识别列 → classify 用 nlparse
的分类关键词把「商品说明/交易对方」映射到应用内分类。不做重型数据分析，纯标准库。
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

from . import nlparse

# 列名关键词 → 语义（表头可能带空格/括号，归一化后匹配）
DATE_KEYS = ["交易时间", "交易日期", "记账日期", "日期", "时间"]
AMOUNT_KEYS = ["金额", "交易金额", "发生额"]
TYPE_KEYS = ["收/支", "收支", "交易类型", "资金流向", "收入/支出", "类型", "收/付"]
DESC_KEYS = [
    "商品说明",
    "商品",
    "交易对方",
    "对方户名",
    "对方",
    "备注",
    "摘要",
    "项目",
    "用途",
    "说明",
    "商户",
]
INCOME_TYPE = {"收入", "收款", "收", "转入", "入账", "credit"}
EXPENSE_TYPE = {"支出", "付款", "支", "转出", "消费", "debit"}


def _is_real_date(d: str) -> bool:
    """YYYY-MM-DD 且日历真实（挡掉 2026-13-45 这类永远进不了月度聚合的值）。"""
    try:
        date.fromisoformat(d)
    except ValueError:
        return False
    return True


def parse_csv(content: str) -> dict:
    """解析 CSV 文本 → {columns: [...], rows: [[...], ...]}（跳过空行）。"""
    try:
        reader = csv.reader(io.StringIO(content))
        lines = [row for row in reader if any(str(c).strip() for c in row)]
    except Exception as exc:  # noqa: BLE001 — 编码/格式错误统一报告
        raise ValueError(f"CSV 解析失败：{exc}") from exc
    if not lines:
        raise ValueError("内容为空")
    columns = [str(c).strip() for c in lines[0]]
    rows = [[str(c).strip() for c in row] for row in lines[1:]]
    return {"columns": columns, "rows": rows}


def detect_mapping(columns: list[str]) -> dict:
    """表头关键词匹配 → {date, amount, type, desc} 列索引（-1 表示未识别）。"""
    norm = [re.sub(r"[\s（(）)]", "", c).lower() for c in columns]

    def find(keys: list[str]) -> int:
        for k in keys:
            kk = re.sub(r"[\s（(）)]", "", k).lower()
            for i, c in enumerate(norm):
                if kk in c:
                    return i
        return -1

    return {
        "date": find(DATE_KEYS),
        "amount": find(AMOUNT_KEYS),
        "type": find(TYPE_KEYS),
        "desc": find(DESC_KEYS),
    }


def classify(desc: str) -> str:
    """说明文本 → 应用分类（收入优先，其次按 nlparse 关键词）。"""
    for w in nlparse.INCOME_KEYWORDS:
        if w in desc:
            return "收入"
    for cat, words in nlparse.CATEGORY_KEYWORDS:
        if cat == "收入":
            continue
        for w in words:
            if w in desc:
                return cat
    return "其他"


def _parse_amount(v: str) -> float | None:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", v)
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def _parse_date(v: str) -> str | None:
    """常见日期格式 → YYYY-MM-DD；无法解析返回 None（由调用方决定跳过）。"""
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", v)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})", v)
    if m:
        return f"{int(m.group(1)):02d}-{int(m.group(2)):02d}"  # 缺年份，由调用方补今年
    return None


def build_rows(
    mapping: dict, columns: list[str], rows: list[list[str]], year_fill: str = ""
) -> tuple[list[dict], list[str]]:
    """按映射把原始行转成入账候选 + 跳过原因。

    每行 → {date, item, category, amount}；amount 正为收入、负为支出。
    缺金额的跳过；缺日期的用 year_fill（YYYY-MM）补当月 1 号或跳过。
    """
    out: list[dict] = []
    skips: list[str] = []
    di, ai, ti, si = (
        mapping["date"],
        mapping["amount"],
        mapping["type"],
        mapping["desc"],
    )
    for row in rows:
        desc = row[si] if 0 <= si < len(row) else ""
        label = desc or "—"
        amt = _parse_amount(row[ai] if 0 <= ai < len(row) else "")
        if amt is None:
            skips.append(f"缺金额：{label}")
            continue
        if amt == 0:
            skips.append(f"金额为 0：{label}")
            continue

        # 收支方向：显式类型列优先，其次金额本身的正负。类型值认不出来就跳过——
        # 猜错方向会把转账/不计收支记成收入，污染储蓄率与趋势，宁可少导一行。
        type_raw = row[ti] if 0 <= ti < len(row) else ""
        type_v = type_raw.strip().lower()
        if type_v:
            if type_v in INCOME_TYPE:
                amt = abs(amt)
            elif type_v in EXPENSE_TYPE:
                amt = -abs(amt)
            else:
                skips.append(f"收支类型未识别（{type_raw.strip()}）：{label}")
                continue

        d = _parse_date(row[di] if 0 <= di < len(row) else "")
        if d is None:
            if not year_fill:
                skips.append(f"缺日期：{label}")
                continue
            d = f"{year_fill}-01"
        elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            if not year_fill:
                skips.append(f"日期缺年份：{label}")
                continue
            # 只有月日的格式，补今年
            d = f"{year_fill[:4]}-{d}"
        if not _is_real_date(d):
            skips.append(f"日期非法（{d}）：{label}")
            continue

        out.append(
            {
                "date": d,
                "item": (desc[:40] or "其他"),
                "category": classify(desc),
                "amount": round(amt, 2),
            }
        )
    return out, skips
