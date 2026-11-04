"""自然语言记账解析：规则引擎优先（本地秒回），AI 兜底（歧义/未知分类）。

入账结果约定：{date: YYYY-MM-DD, item: str, category: str, amount: 正为收入、负为支出}
规则引擎只要拿到「金额 + 收支方向」即可入账（日期默认今天、分类/名称兜底），
拿不到金额才升级给 AI 解析。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import cn2an

# 分类关键词（按序匹配，越靠前越具体；收入词在收入分支单独判断）
CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "交通",
        [
            "打车",
            "滴滴",
            "出租",
            "地铁",
            "公交",
            "高铁",
            "火车",
            "机票",
            "加油",
            "停车",
            "共享单车",
            "骑行",
        ],
    ),
    (
        "餐饮",
        [
            "早餐",
            "午餐",
            "晚餐",
            "夜宵",
            "外卖",
            "火锅",
            "烧烤",
            "咖啡",
            "奶茶",
            "吃饭",
            "早饭",
            "午饭",
            "晚饭",
            "喝",
            "下馆子",
            "零食",
            "水果",
        ],
    ),
    ("居住", ["房租", "房贷", "水电", "物业", "燃气", "宽带", "话费", "供暖"]),
    (
        "购物",
        [
            "淘宝",
            "京东",
            "拼多多",
            "衣服",
            "超市",
            "商场",
            "日用品",
            "家电",
            "买了",
            "购物",
        ],
    ),
    ("订阅", ["会员", "订阅", "视频", "音乐", "网盘", "云盘", "自动续费"]),
    ("投资", ["基金", "股票", "加仓", "买入", "定投", "黄金"]),
    ("还款", ["还款", "信用卡", "花呗", "白条", "还贷"]),
    ("收入", ["工资", "奖金", "报销", "退款", "到账", "分红", "利息", "兼职", "收入"]),
]

INCOME_KEYWORDS = [
    "工资",
    "奖金",
    "报销",
    "退款",
    "到账",
    "分红",
    "利息",
    "收入",
    "兼职",
    "赚了",
]

# 从句子中剔除的语气词 / 动词，用于提炼「名称」
NOISE_WORDS = [
    "今天",
    "昨天",
    "前天",
    "大前天",
    "花了",
    "消费",
    "支出",
    "用了",
    "付了",
    "扫码",
    "支付",
    "块钱",
    "块",
    "元",
    "钱",
    "大概",
    "约",
]

# 金额识别：带货币单位的优先；无单位时先剔掉易混淆的数字片段再取第一个
_AMOUNT_PREFIX = re.compile(r"(?:¥|￥)\s*(\d[\d,]*(?:\.\d+)?)\s*(万|w|W|k|K)?")
_AMOUNT_SUFFIX = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(万|w|W|k|K)?\s*(?:元|块钱|块|人民币)")
_AMOUNT_PLAIN = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(万|w|W|k|K)?")
# 月份、时间点（3点/5分/2时）、字母型号（iPhone15）、数量单位（10股）——都不是金额
_NON_AMOUNT_DIGITS = re.compile(
    r"\d{1,2}\s*月|[A-Za-z]+\d+|\d+\s*(?:点|时|分|股|份|手|个|件|人|天|次|张|瓶|斤|米|码|楼|号)"
)

# 中文数字金额（cn2an）：口语记账里「三十块」「一万二」「五毛」比阿拉伯数字更常见
_CN = "零一二三四五六七八九十百千万亿两"
_CN_WITH_UNIT = re.compile(rf"([{_CN}]+)\s*(块|元|钱|圆|毛|角)\s*([{_CN}]+)?")
_CN_BARE = re.compile(rf"[{_CN}]+")
# 紧跟量词/时间单位的中文数字不是金额：「三件衣服」「三天前」「二月」「十点半」
_CN_NOT_MONEY = re.compile(
    rf"[{_CN}]+\s*(?:月|日|号|点|半|时|分|天|周|年|件|个|次|张|杯|碗|份|斤|袋|瓶|盒|套|双|把|台|部|趟|岁|人|口|家|顿)"
)


def _to_amount(m: re.Match) -> float:
    num = float(m.group(1).replace(",", ""))
    unit = m.group(2) or ""
    if unit in ("万", "w", "W"):
        num *= 10000
    elif unit in ("k", "K"):
        num *= 1000
    return round(num, 2)


def _cn_amount(text: str) -> float | None:
    """中文数字金额 → 元。带货币单位优先（「十五块五」= 15.5）；无单位时只认
    含十/百/千/万/亿 的复合数（「二十」「八千」「一万二」），避免把「三件」「三天」当钱。"""
    m = _CN_WITH_UNIT.search(text)
    if m:
        base = _cn_to_float(m.group(1))
        if base is not None:
            unit = m.group(2)
            frac = _cn_to_float(m.group(3)) if m.group(3) else None
            # 「三块半」：半 = 0.5（半不在中文数字字符集里）
            if frac is None and text[m.end() :].startswith("半"):
                frac = 5
            if unit in ("毛", "角"):
                return round(base / 10 + (frac or 0) / 100, 2)
            return round(base + (frac / 10 if frac is not None else 0), 2)
    for m in _CN_BARE.finditer(text):
        token = m.group(0)
        if not re.search(r"[十百千万亿]", token):
            continue
        # 紧跟时间词（十点半/三点/五分）不是金额
        if _CN_NOT_MONEY.match(text[m.end() :]) or re.match(r"[点时半分]", text[m.end() :]):
            continue
        val = _cn_to_float(token)
        if val:
            return round(val, 2)
    return None


def _cn_to_float(token: str) -> float | None:
    try:
        return float(cn2an.transform(token, "cn2an"))
    except Exception:  # noqa: BLE001 — 非法中文数字（如「零」）返回 None
        return None


def _parse_amount(text: str) -> float | None:
    """提取金额：阿拉伯数字带货币单位 → 阿拉伯数字 → 中文数字。返回元，None 表示没有金额。"""
    for pattern in (_AMOUNT_PREFIX, _AMOUNT_SUFFIX):
        m = pattern.search(text)
        if m:
            return _to_amount(m)
    m = _AMOUNT_PLAIN.search(_NON_AMOUNT_DIGITS.sub(" ", text))
    if m:
        return _to_amount(m)
    return _cn_amount(text)


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


def _clean_item(rest: str, category: str, hit: str | None) -> str:
    """从剩余文本提炼名称：命中关键词用关键词，否则去噪词后取主干。"""
    if hit:
        return hit
    t = rest
    for w in NOISE_WORDS:
        t = t.replace(w, " ")
    t = re.sub(r"\d[\d,.]*", " ", t)  # 去掉残留金额数字
    t = re.sub(r"\s+", " ", t).strip(" ，。！？、")
    t = re.sub(r"^[,，:：\-]+|[,，:：\-]+$", "", t).strip()
    return t[:40] or category


# 咨询/意图词：命中且无记账动作词时，不当作一句话记账（避免「我月收入24800，想
# 开始理财」被记成收入、分析/建议类提问被入账等语义劫持）。
QUERY_MARKERS = (
    "想", "建议", "推荐", "分析", "怎么样", "如何", "怎么", "计划", "适合",
    "配置", "帮我", "看看", "优化", "能否", "可以吗", "理财", "投资", "评估",
    "规划", "目标", "策略",
)
# 明确记账动作词：命中其一即认定是记账语气（咨询词同时命中时仍记账）。
RECORD_VERBS = (
    "记一笔", "花了", "买了", "买", "消费", "支付", "付了", "交", "充值",
    "打车", "吃饭", "喝了", "工资", "奖金", "报销", "退款", "到账", "分红",
    "利息", "发了", "转了", "存了", "还了", "扣了",
)


# 空格分隔的多笔：「午餐 45 打车 28」→ 两笔。
# 判定要严：日期/时间/量词都可能长得像「文字+数字」，误切会把一笔拆成多笔，
# 比不拆更糟（凭空多记假账）。先排日期形态，再要求至少两组「像条目的词 + 合理金额」。
_MULTI_RE = re.compile(
    r"(?<![年月日\d])([\u4e00-\u9fa5A-Za-z]{1,10})\s*(\d+(?:\.\d{1,2})?)\s*(?:元|块)?"
)

# 出现在数字前说明是日期/时间/计量，不是记账条目
_NOT_ITEM_WORDS = frozenset({
    "年", "月", "日", "号", "时", "点", "分", "秒",
    "第", "共", "约", "近", "前", "后", "折", "期",
})


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
