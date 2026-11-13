"""支付宝账单 CSV 解析器。

CSV 结构（支付宝导出）：
  - 前 ~5 行为说明文本（以"支付宝"开头）
  - 真正的表头行：交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注
  - 数据行后可能有备注行

关键列：
  - 收/支：收入 / 支出 / 不计收支（或不计收支相关值）
  - 金额：纯数字（无货币符号），如 32.00
  - 交易分类：支付宝自带的分类名
  - 交易对方：商户 / 个人名
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

# 支付宝 CSV 表头特征
_ALIPAY_HEADER_MARKERS = {"交易时间", "交易分类", "交易对方", "商品说明", "收/支", "金额"}

# 不计收支 → 跳过
_ALIPAY_SKIP_TYPE = {"不计收支", ""}


def _find_header_row(rows: list[list[str]]) -> int:
    """找到支付宝真正表头行的索引。"""
    for i, row in enumerate(rows):
        cell_set = {c.strip() for c in row if c.strip()}
        if len(cell_set & _ALIPAY_HEADER_MARKERS) >= 2:
            return i
    return -1


class AlipayParser(TransactionParser):
    """支付宝账单解析器。"""

    @classmethod
    def label(cls) -> str:
        return "支付宝"

    @classmethod
    def description(cls) -> str:
        return "支付宝账单导出 CSV（自动跳过前导元信息行）。"

    @classmethod
    def sample_columns(cls) -> list[str]:
        return ["交易时间", "交易分类", "交易对方", "商品说明", "收/支", "金额", "交易状态"]

    def parse(self, csv_text: str, **kwargs: object) -> ParseResult:
        result = ParseResult()

        if not csv_text or not csv_text.strip():
            result.errors.append("CSV 内容为空")
            return result

        try:
            reader = csv.reader(io.StringIO(csv_text))
            # 不过滤空行：行号必须与原始文件一一对应（见 wechat.py 同名注释）
            rows = list(reader)
        except Exception as exc:
            result.errors.append(f"CSV 解析失败：{exc}")
            return result

        if not rows:
            result.errors.append("CSV 内容为空")
            return result

        header_idx = _find_header_row(rows)
        if header_idx < 0:
            result.errors.append(
                "未找到支付宝账单表头（期望包含：交易时间, 金额, 收/支 等列）"
            )
            return result

        columns = [str(c).strip() for c in rows[header_idx]]
        data_rows = rows[header_idx + 1 :]

        # 定位列索引（支付宝列名前后可能带空格/全角）
        col_idx: dict[str, int] = {}
        col_aliases = {
            "交易时间": ["交易时间"],
            "交易分类": ["交易分类"],
            "交易对方": ["交易对方"],
            "对方账号": ["对方账号"],
            "商品说明": ["商品说明"],
            "收/支": ["收/支"],
            "金额": ["金额"],
            "收/付款方式": ["收/付款方式", "收/付方式"],
            "交易状态": ["交易状态"],
            "备注": ["备注"],
        }
        for key, aliases in col_aliases.items():
            col_idx[key] = -1
            for alias in aliases:
                for i, c in enumerate(columns):
                    if alias in c:
                        col_idx[key] = i
                        break
                if col_idx[key] >= 0:
                    break

        # 必要列检查
        if col_idx.get("交易时间", -1) < 0 or col_idx.get("金额", -1) < 0:
            result.errors.append(
                f"缺少必要列（交易时间 / 金额），实际表头：{columns}"
            )
            return result

        di = col_idx["交易时间"]
        ai = col_idx["金额"]
        ti = col_idx.get("收/支", -1)
        ci = col_idx.get("交易分类", -1)
        gi = col_idx.get("商品说明", -1)
        pi = col_idx.get("收/付款方式", -1)
        ri = col_idx.get("备注", -1)

        if ti < 0:
            # 缺「收/支」列时每行都会落进空值跳过分支：导入"成功"但 0 笔、0 错误。
            result.errors.append(
                f"缺少「收/支」列，无法判断收入/支出方向，实际表头：{columns}"
            )
            return result

        skip_count = 0
        unknown_direction = 0

        for row_num, row in enumerate(data_rows, start=header_idx + 2):

            joined = "".join(c.strip() for c in row)
            # 跳过空行 / 备注尾巴
            if not joined:
                skip_count += 1
                continue
            if re.match(r"^(备注|说明|支付宝|----)", joined):
                skip_count += 1
                continue

            raw = {columns[i]: row[i] if i < len(row) else "" for i in range(len(columns))}

            # 日期
            date_str = _parse_date(row[di]) if 0 <= di < len(row) else None
            if not date_str or not _is_real_date(date_str):
                result.errors.append(f"第 {row_num} 行：日期无效")
                skip_count += 1
                continue

            # 金额
            amount = _parse_amount(row[ai]) if 0 <= ai < len(row) else None
            if amount is None or amount == 0:
                result.errors.append(f"第 {row_num} 行：金额无效")
                skip_count += 1
                continue

            # 收/支方向
            type_val = row[ti].strip() if 0 <= ti < len(row) else ""
            if type_val in _ALIPAY_SKIP_TYPE:
                skip_count += 1
                continue
            if "收入" in type_val:
                amount = abs(amount)
            elif "支出" in type_val:
                amount = -abs(amount)
            else:
                # 无法识别的方向：跳过并计数，最后回话，不静默吞掉
                unknown_direction += 1
                skip_count += 1
                continue

            # 分类（支付宝自带分类列，优先使用）
            category = ""
            if 0 <= ci < len(row):
                category = row[ci].strip()

            # item：商品说明
            item = ""
            if 0 <= gi < len(row):
                item = row[gi].strip()
            if not item and 0 <= ci < len(row):
                item = row[ci].strip()
            if not item and 0 <= ri < len(row):
                item = row[ri].strip()

            account = row[pi].strip() if 0 <= pi < len(row) else ""

            result.transactions.append(
                ParsedTransaction(
                    date=date_str,
                    amount=round(amount, 2),
                    category=(category or "其他")[:20],
                    item=item[:80] or "未命名",
                    account=account[:40],
                    raw=raw,
                )
            )

        if unknown_direction:
            result.errors.append(
                f"{unknown_direction} 行的「收/支」值无法识别（既非收入也非支出），已跳过"
            )
        result.skipped = skip_count
        result.recalc_totals()
        return result
