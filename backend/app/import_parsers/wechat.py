"""微信支付账单 CSV 解析器。

CSV 结构（微信导出）：
  - 前 ~16 行为说明文字 / 元信息（以"微信支付账单明细"开头）
  - 真正的表头行：交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注
  - 数据行从表头下一行开始
  - 末尾可能有"账单春来...""账单周期"等尾巴

关键列：
  - 收/支：收入 / 支出 / /（斜杠 = 不计收支，跳过）
  - 金额(元)：带 ¥ 前缀，如 ¥100.00
  - 商品：交易的商品 / 服务描述
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

# 微信 CSV 表头特征（至少命中其一即视为真正的表头行）
_WECHAT_HEADER_MARKERS = {"交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)"}

# 不计收支的值 → 跳过
_WECHAT_SKIP_TYPE = {"/", "不计收支", ""}


def _find_header_row(rows: list[list[str]]) -> int:
    """找到真正表头行的索引。微信 CSV 前面有 ~16 行元信息。"""
    for i, row in enumerate(rows):
        cell_set = {c.strip() for c in row if c.strip()}
        # 命中 2+ 个关键列名即判定为表头
        if len(cell_set & _WECHAT_HEADER_MARKERS) >= 2:
            return i
    return -1


class WeChatParser(TransactionParser):
    """微信支付账单解析器。"""

    @classmethod
    def label(cls) -> str:
        return "微信支付"

    @classmethod
    def description(cls) -> str:
        return "微信支付账单导出 CSV（自动跳过前导元信息行）。"

    @classmethod
    def sample_columns(cls) -> list[str]:
        return ["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式"]

    def parse(self, csv_text: str, **kwargs: object) -> ParseResult:
        result = ParseResult()

        if not csv_text or not csv_text.strip():
            result.errors.append("CSV 内容为空")
            return result

        try:
            reader = csv.reader(io.StringIO(csv_text))
            # 不过滤空行：报错里的行号必须与用户看到的原始文件一一对应。
            # 旧实现先 filter 掉空行、再手工 +1 累加行号，两处偏差叠加，
            # 「第 N 行日期无效」会指向错误的行（用户按行号去查，查到的是别的交易）。
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
                "未找到微信账单表头（期望包含：交易时间, 金额(元), 收/支 等列）"
            )
            return result

        columns = [str(c).strip() for c in rows[header_idx]]
        data_rows = rows[header_idx + 1 :]

        # 定位列索引
        col_idx: dict[str, int] = {}
        for key in ("交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式", "备注"):
            for i, c in enumerate(columns):
                if key in c:
                    col_idx[key] = i
                    break
            else:
                col_idx[key] = -1

        # 必要列：交易时间 + 金额
        if col_idx.get("交易时间", -1) < 0 or col_idx.get("金额(元)", -1) < 0:
            result.errors.append(
                f"缺少必要列（交易时间 / 金额(元)），实际表头：{columns}"
            )
            return result

        di = col_idx["交易时间"]
        ai = col_idx["金额(元)"]
        ti = col_idx.get("收/支", -1)
        gi = col_idx.get("商品", -1)
        pi = col_idx.get("支付方式", -1)
        ri = col_idx.get("备注", -1)

        if ti < 0:
            # 没有「收/支」列就无法判断每笔的正负号。旧实现让每行都落到
            # type_val == "" 的跳过分支：导入"成功"、0 笔、0 条错误，
            # 用户以为账单是空的。必须显式失败。
            result.errors.append(
                f"缺少「收/支」列，无法判断收入/支出方向，实际表头：{columns}"
            )
            return result

        skip_count = 0
        unknown_direction = 0

        for row_num, row in enumerate(data_rows, start=header_idx + 2):

            # 跳过汇总行 / 空行 / 尾巴
            joined = "".join(c.strip() for c in row)
            if not joined:
                skip_count += 1
                continue
            # 尾巴文案特征
            if re.match(r"^(账单|微信|导出|备注：|温馨提示)", joined):
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
            if type_val in _WECHAT_SKIP_TYPE:
                skip_count += 1
                continue
            if "收入" in type_val:
                amount = abs(amount)
            elif "支出" in type_val:
                amount = -abs(amount)
            else:
                # 无法识别的方向：跳过并计数。整批都落在这里通常意味着
                # 传进来的不是账单明细（或表头被改过），必须回话，不能静默。
                unknown_direction += 1
                skip_count += 1
                continue

            # item：商品列优先，缺则用备注
            item = ""
            if 0 <= gi < len(row):
                item = row[gi].strip()
            if not item and 0 <= ri < len(row):
                item = row[ri].strip()

            account = row[pi].strip() if 0 <= pi < len(row) else ""

            result.transactions.append(
                ParsedTransaction(
                    date=date_str,
                    amount=round(amount, 2),
                    category="其他",  # 由分类器后置处理
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
