"""记账解析入口：多笔拆分、规则解析、模型兜底。"""

from __future__ import annotations

import re
from datetime import datetime

from .nlparse_date import _parse_date
from .nlparse_item import (
    _MULTI_RE,
    _NOT_ITEM_WORDS,
    QUERY_MARKERS,
    RECORD_VERBS,
    _clean_item,
)
from .nlparse_lexicon import CATEGORY_KEYWORDS, INCOME_KEYWORDS, _parse_amount


def parse_many(text: str) -> list[dict] | None:
    """把一句话拆成多笔；不是多笔时返回 None（交给 parse 走单笔逻辑）。

    为什么需要：parse() 只取第一个金额，而条目名/分类取全文最后匹配的关键词——
    「午餐 45 打车 28」会变成「打车 −45」：金额来自午餐、名称来自打车，
    既丢了一笔，又把两笔混成一条错数据。
    """
    t = text.strip()
    if not t:
        return None
    # 已有显式分隔符时交给上层分段，避免双重切分
    if re.search(r"[，,。;；、和及]", t):
        return None
    # 日期/时间形态直接放弃多笔判定，交给 parse 的日期解析
    if re.search(r"\d{4}\s*年|\d{1,2}\s*月\s*\d{1,2}\s*[日号]", t):
        return None
    hits = _MULTI_RE.findall(t)
    pairs = [
        (w.strip(), n)
        for w, n in hits
        if w.strip() and w.strip() not in _NOT_ITEM_WORDS
    ]
    if len(pairs) < 2:
        return None
    out: list[dict] = []
    for word, num in pairs:
        one = parse(f"{word} {num}")
        if one is not None and abs(one["amount"]) > 0:
            out.append(one)
    return out if len(out) >= 2 else None


def parse(text: str) -> dict | None:
    """规则解析。失败（拿不到金额）返回 None。"""
    t = text.strip()
    if not t:
        return None

    today = datetime.now().astimezone().date()
    d, rest = _parse_date(t, today)
    amount = _parse_amount(rest)
    if amount is None:
        return None

    # 咨询语气优先于记账：例如「想开始理财」「给我点建议」不应入账。
    if any(m in t for m in QUERY_MARKERS) and not any(v in t for v in RECORD_VERBS):
        return None

    # 6 位数字是 A 股代码形态（600519/000001…），不是记账金额：出现代码语境时不做记账。
    if re.search(r"\d{6}", t) and any(k in t for k in ("股", "买入", "卖出", "清仓", "建仓", "加仓", "股票", "基金", "ETF")):
        return None

    is_income = any(k in t for k in INCOME_KEYWORDS)
    category, hit = "其他", None
    for cat, words in CATEGORY_KEYWORDS:
        if cat == "收入":
            continue
        for w in words:
            if w in t:
                category, hit = cat, w
                break
        if hit:
            break
    if is_income:
        category = "收入"
        hit = next((w for w in INCOME_KEYWORDS if w in t), None)
        amount = abs(amount)
    else:
        amount = -abs(amount)

    return {
        "date": d or today.isoformat(),
        "item": _clean_item(rest, category, hit),
        "category": category,
        "amount": amount,
    }


async def parse_with_ai(text: str) -> dict | None:
    """AI 兜底：交给配置的模型解析，严格校验后返回；失败返回 None。"""
    from . import llm

    today = datetime.now().astimezone().date().isoformat()
    system = (
        "你是记账解析器。从用户的一句话里提取 JSON，字段："
        '{"type":"expense|income","category":"餐饮|居住|交通|购物|订阅|投资|还款|收入|其他",'
        '"amount":数字(元，只写数字), "date":"YYYY-MM-DD", "item":"简短名称(≤10字)"}。'
        "只输出 JSON，不要任何解释。今天日期：" + today
    )
    data = await llm.json_complete(system, text, timeout=20.0)
    if not isinstance(data, dict):
        return None
    try:
        amount = float(data.get("amount", 0))
        if amount <= 0:
            return None
        cat = str(data.get("category", "其他")).strip() or "其他"
        cat = (
            cat
            if cat
            in {"餐饮", "居住", "交通", "购物", "订阅", "投资", "还款", "收入", "其他"}
            else "其他"
        )
        item = str(data.get("item", "")).strip()[:40] or cat
        # 日期校验：允许今天/昨天/前天等相对词（AI 已给绝对日期则校验格式）
        d = str(data.get("date", "")).strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            d = datetime.now().astimezone().date().isoformat()
        amount = abs(amount) if data.get("type") == "income" else -abs(amount)
        return {"date": d, "item": item, "category": cat, "amount": amount}
    except Exception:  # noqa: BLE001 — 模型输出不规整时回退规则结果
        return None
