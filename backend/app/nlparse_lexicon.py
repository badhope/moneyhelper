"""记账词表与金额解析：分类关键词、噪声词、中文数字与单位换算。"""

from __future__ import annotations

import re

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
