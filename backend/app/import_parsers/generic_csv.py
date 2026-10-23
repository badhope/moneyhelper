"""通用 CSV 交易解析器：自动识别列名（中英文）、收支方向、编码。

列名关键词对照（归一化后模糊匹配）：
  日期：date / 交易日期 / 记账日期 / 交易时间 / 时间 / date
  金额：amount / 金额 / 交易金额 / 发生额
  收入列：收入 / income / credit / 贷方
  支出列：支出 / expense / debit / 借方
  分类：category / 分类 / 类别 / 交易分类
  备注：item / notes / 商品 / 备注 / 摘要 / 用途 / 说明 / 商户 / 交易对方
  账户：account / 卡号 / 账户 / 账号 / 来源
  类型：type / 收/支 / 收支 / 交易类型 / 资金流向 / 收入/支出 / 收/付
"""

from __future__ import annotations

import csv
import io
import re

from .base import (
    ParsedTransaction,
    ParseResult,
    TransactionParser,
    _is_real_date,
    _parse_amount,
    _parse_date,
)

# 列名关键词族（lower-case、去空格后匹配）
# 列名候选按优先级排列成元组（不是 set）：find() 按声明顺序匹配，
# 保证同一文件在不同进程（PYTHONHASHSEED 不同）下列映射完全一致。
_DATE_KEYS = ("date", "交易日期", "记账日期", "交易时间", "日期", "时间")
_AMOUNT_KEYS = ("amount", "金额", "交易金额", "发生额")
_INCOME_KEYS = ("收入", "income", "credit", "贷方")
_EXPENSE_KEYS = ("支出", "expense", "debit", "借方", "消费")
_CATEGORY_KEYS = ("category", "分类", "类别", "交易分类")
_ITEM_KEYS = (
    "item", "notes", "商品", "备注", "摘要", "用途", "说明",
    "商户", "交易对方", "对方", "对方户名", "描述", "交易说明",
)
_ACCOUNT_KEYS = ("account", "卡号", "账户", "账号", "来源", "账户名")
_TYPE_KEYS = ("type", "收/支", "收支", "交易类型", "资金流向", "收入/支出", "收/付")

# 收支方向关键词
_INCOME_TYPE_VALS = {"收入", "收款", "收", "转入", "入账", "credit"}
_EXPENSE_TYPE_VALS = {"支出", "付款", "支", "转出", "消费", "debit"}


def _normalize(s: str) -> str:
    """归一化列名：去空格 / 括号 / 转小写。"""
    return re.sub(r"[\s（(）)¥￥]", "", s).lower()


def _build_column_map(columns: list[str]) -> dict[str, int]:
    """列名 → 列索引（-1 表示未识别）。"""
    norm = [_normalize(c) for c in columns]
    mapping: dict[str, int] = {}

    def find(keys: tuple[str, ...]) -> int:
        for k in keys:
            nk = _normalize(k)
            for i, c in enumerate(norm):
                if nk in c or c in nk:
                    return i
        return -1

    mapping["date"] = find(_DATE_KEYS)
    mapping["amount"] = find(_AMOUNT_KEYS)
    mapping["income_col"] = find(_INCOME_KEYS)
    mapping["expense_col"] = find(_EXPENSE_KEYS)
    mapping["category"] = find(_CATEGORY_KEYS)
    mapping["item"] = find(_ITEM_KEYS)
    mapping["account"] = find(_ACCOUNT_KEYS)
    mapping["type"] = find(_TYPE_KEYS)

    return mapping


def _looks_like_summary(row: list[str]) -> bool:
    """判断是否为汇总行 / 空行。"""
    joined = "".join(c.strip() for c in row)
    if not joined:
        return True
    # 常见汇总行特征：以"合计""总计""小计""汇总"开头
    if re.match(r"^(合计|总计|小计|汇总|统计)", joined):
        return True
    # 只有一个非空单元格的行
    nonempty = [c for c in row if c.strip()]
    return len(nonempty) <= 1


class GenericCSVParser(TransactionParser):
    """通用 CSV 解析：自动列名映射 + 借贷分列支持。"""

    @classmethod
    def label(cls) -> str:
        return "通用 CSV"

    @classmethod
    def description(cls) -> str:
        return "自动识别表头的通用 CSV；支持银行借贷分列、中英文列名。"

    @classmethod
    def sample_columns(cls) -> list[str]:
        return ["交易日期", "交易类型", "交易对方", "金额", "备注"]

    def parse(self, csv_text: str, **kwargs: object) -> ParseResult:
        result = ParseResult()

        if not csv_text or not csv_text.strip():
            result.errors.append("CSV 内容为空")
            return result

        try:
            reader = csv.reader(io.StringIO(csv_text))
            rows = [r for r in reader if r]  # 过滤 None
        except Exception as exc:
            result.errors.append(f"CSV 解析失败：{exc}")
            return result

        if not rows:
            result.errors.append("CSV 内容为空")
            return result

        columns = [str(c).strip() for c in rows[0]]
        data_rows = rows[1:]
        col_map = _build_column_map(columns)

        if col_map["date"] < 0:
            result.errors.append(
                f"未识别日期列（可用：日期 / date / 交易日期），实际表头：{columns}"
            )
        if col_map["amount"] < 0 and (
            col_map["income_col"] < 0 and col_map["expense_col"] < 0
        ):
            result.errors.append(
                f"未识别金额列（可用：金额 / amount / 收入 / 支出），实际表头：{columns}"
            )
        if result.errors:
            return result

        di = col_map["date"]
        ai = col_map["amount"]
        ii = col_map["income_col"]
        ei = col_map["expense_col"]
        ci = col_map["category"]
        si = col_map["item"]
        ti = col_map["type"]

        skip_count = 0
        for idx, row in enumerate(data_rows, start=2):
            # 跳过汇总 / 空行
            if _looks_like_summary(row):
                skip_count += 1
                continue

            raw = {columns[i]: row[i] if i < len(row) else "" for i in range(len(columns))}

            # 日期
            date_str = _parse_date(row[di]) if 0 <= di < len(row) else None
            if not date_str or not _is_real_date(date_str):
                result.errors.append(f"第 {idx} 行：日期无效（{row[di] if di < len(row) else ''}）")
                skip_count += 1
                continue

            # 金额：单一金额列 或 借贷分列
            amount = 0.0
            has_amount = False

            if 0 <= ai < len(row):
                amt = _parse_amount(row[ai])
                if amt is not None:
                    amount = amt
                    has_amount = True

            if not has_amount:
                # 借贷分列（银行格式）
                inc = _parse_amount(row[ii]) if 0 <= ii < len(row) else None
                exp = _parse_amount(row[ei]) if 0 <= ei < len(row) else None
                if inc is not None and inc > 0:
                    amount = inc  # 贷方 = 收入
                    has_amount = True
                elif exp is not None and exp > 0:
                    amount = -exp  # 借方 = 支出
                    has_amount = True

            if not has_amount:
                label = row[si] if si >= 0 and si < len(row) else ""
                result.errors.append(f"第 {idx} 行：金额无法解析（{label or row}）")
                skip_count += 1
                continue

            # 收支方向：显式类型列优先
            type_val = row[ti].strip().lower() if 0 <= ti < len(row) else ""
            if type_val:
                if type_val in _INCOME_TYPE_VALS:
                    amount = abs(amount)
                elif type_val in _EXPENSE_TYPE_VALS:
                    amount = -abs(amount)
                # 若类型值不识别则保持原金额符号（可能是已带正负号的列）

            # 分类 / 备注 / 账户
            category = row[ci].strip() if 0 <= ci < len(row) and row[ci].strip() else "其他"
            item = row[si].strip() if 0 <= si < len(row) and row[si].strip() else "未命名"
            account = ""
            if 0 <= col_map["account"] < len(row):
                account = row[col_map["account"]].strip()

            result.transactions.append(
                ParsedTransaction(
                    date=date_str,
                    amount=round(amount, 2),
                    category=category[:20],
                    item=item[:80],
                    account=account[:40],
                    raw=raw,
                )
            )

        result.skipped = skip_count
        result.recalc_totals()
        return result
