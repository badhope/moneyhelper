"""日期识别：相对词优先于显式日期，非法日历退回剩余文本。"""

from __future__ import annotations

import re
from datetime import date, timedelta


def _parse_date(text: str, today: date) -> tuple[str | None, str]:
    """返回 (YYYY-MM-DD, 去掉日期后的剩余文本)。"""
    # 相对日期（长词优先，否则「大前天」会被「前天」抢走）
    for offset, word in ((3, "大前天"), (2, "前天"), (1, "昨天"), (0, "今天")):
        if word in text:
            d = today - timedelta(days=offset)
            return d.isoformat(), text.replace(word, " ", 1)
    # 显式：YYYY-MM-DD / YYYY年M月D日
    m = re.search(r"(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})日?", text)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None, text  # 日历非法（如 13月40日）：不当日期，留给金额解析
        return d.isoformat(), re.sub(
            r"\d{4}[-年/]\d{1,2}[-月/]\d{1,2}日?", " ", text, count=1
        )
    # 今年内：M月D日 / M月D号
    m = re.search(r"(\d{1,2})月(\d{1,2})[日号]", text)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
            return d.isoformat(), re.sub(r"\d{1,2}月\d{1,2}[日号]", " ", text, count=1)
        except ValueError:
            return None, text
    return None, text
