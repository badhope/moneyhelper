"""账单归类规则引擎（v4.6）：把「分类」从硬编码关键词升级为可配置规则。

设计参照 double-entry-generator 的成熟做法（https://github.com/deb-sig/double-entry-generator）：
- 规则维度正交：peer（交易对方）/ item（摘要）/ category（账单自带分类）/ type（收支方向）/
  amount（金额区间），任一维度可留空表示不参与匹配；
- 优先级由「具体度」决定，而非声明顺序：命中的非空维度越多越优先，同分时精确匹配优先于正则；
- 必须有兜底规则，且兜底命中要打标 `fallback`，由前端提示人工复核；
- 每条结果可解释：返回命中的规则 id、匹配到的维度与原始文本；
- 正则编译缓存 + 长度上限，防 ReDoS。

与 double-entry-generator 的差异：那个项目输出 Beancount 复式分录，我们只做「分类 + 标签」，
因为本系统的账本是单式（收入/支出 + 分类），不引入复式账户体系。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

MAX_PATTERN_LEN = 200
MAX_RULES = 500
DEFAULT_CATEGORY = "其他"

# 内置规则（按具体度自动排序，这里只保证「同分时精确优先」的声明顺序稳定）
BUILTIN_RULES: list[dict[str, Any]] = [
    # 收入
    {"id": "income-salary", "type": "收入", "item": r"工资|薪资|薪酬|月薪|奖金|年终奖", "category": "收入"},
    {"id": "income-refund", "type": "收入", "item": r"退款|退货|返现|返利", "category": "退款"},
    {"id": "income-reimburse", "type": "收入", "item": r"报销", "category": "报销"},
    {"id": "income-dividend", "type": "收入", "item": r"分红|派息|股息", "category": "投资收益"},
    {"id": "income-interest", "type": "收入", "item": r"利息|结息|理财收益", "category": "投资收益"},
    # 居住
    {"id": "home-rent", "item": r"房租|租金|物业管理费|物业费|水费|电费|燃气费|暖气费", "category": "居住"},
    # 餐饮
    {"id": "food-delivery", "peer": r"美团|饿了么|肯德基|麦当劳|星巴克|瑞幸|喜茶|奈雪", "category": "餐饮"},
    {"id": "food-dining", "item": r"餐|饭|咖啡|奶茶|外卖|食堂|小吃|烧烤|火锅", "category": "餐饮"},
    # 交通
    {"id": "transport-ridehail", "peer": r"滴滴|高德|T3|曹操|首汽|花小猪", "category": "交通"},
    # 同一平台也可能只出现在摘要里（银行账单常见），补一条 item 维度规则
    {"id": "transport-ridehail-item", "item": r"滴滴|快车|专车|优享|顺风车|花小猪", "category": "交通"},
    {"id": "transport-public", "item": r"地铁|公交|轨道交通|出租车|打车|加油|停车|高速|ETC", "category": "交通"},
    # 购物
    {"id": "shop-ecommerce", "peer": r"淘宝|天猫|京东|拼多多|唯品会|抖音商城|苏宁", "category": "购物"},
    {"id": "shop-general", "item": r"超市|便利店|商场|百货|购物|服饰|鞋|数码|家电", "category": "购物"},
    # 订阅
    {"id": "sub-streaming", "item": r"会员|订阅|VIP|视频|音乐|云盘|网盘|iCloud|Netflix|Spotify", "category": "订阅"},
    # 医疗
    {"id": "health-medical", "item": r"医院|药店|诊所|体检|医疗|挂号|药品|牙科", "category": "医疗"},
    # 教育
    {"id": "edu-general", "item": r"学费|培训|课程|教育|书店|图书|考试|报名费", "category": "教育"},
    # 投资
    {"id": "invest-fund", "item": r"基金|定投|理财|股票|证券|黄金|债券", "category": "投资"},
    # 还款
    {"id": "debt-repay", "item": r"还款|信用卡还款|花呗|借呗|白条|贷款", "category": "还款"},
    # 转账
    {"id": "transfer-general", "item": r"转账|红包|AA|收款", "category": "转账"},
]


@lru_cache(maxsize=1024)
def _compile(pattern: str) -> re.Pattern[str] | None:
    """编译正则（带长度上限与异常兜底）。缓存避免每次匹配重复编译。"""
    if not pattern or len(pattern) > MAX_PATTERN_LEN:
        return None
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None


def _matches(pattern: str, text: str) -> bool:
    if not pattern:
        return True  # 空维度 = 不参与匹配
    rx = _compile(pattern)
    if rx is None:
        return False
    return bool(rx.search(text or ""))


@dataclass
class Rule:
    id: str
    category: str
    peer: str = ""
    item: str = ""
    category_match: str = ""
    type: str = ""
    min_amount: float | None = None
    max_amount: float | None = None
    tags: list[str] = field(default_factory=list)

    def specificity(self) -> int:
        """具体度 = 非空维度数；维度越多越优先，避免宽泛规则吞掉全部交易。"""
        return sum(
            1
            for v in (self.peer, self.item, self.category_match, self.type)
            if v
        ) + (1 if self.min_amount is not None or self.max_amount is not None else 0)

    def is_regex(self) -> bool:
        """含正则元字符则视为正则规则（同分时精确匹配优先）。"""
        return any(ch in (self.peer + self.item + self.category_match) for ch in r".*+?[](){}|\\^$")


def compile_rules(raw_rules: list[dict[str, Any]] | None = None) -> list[Rule]:
    """把配置字典编译成 Rule 列表，并按「具体度降序 + 非正则优先」排序。"""
    source = raw_rules if raw_rules is not None else BUILTIN_RULES
    rules: list[Rule] = []
    for idx, raw in enumerate(source[:MAX_RULES]):
        if not isinstance(raw, dict):
            continue
        category = str(raw.get("category") or "").strip()
        if not category:
            continue
        try:
            min_amount = float(raw["min_amount"]) if raw.get("min_amount") is not None else None
            max_amount = float(raw["max_amount"]) if raw.get("max_amount") is not None else None
        except (TypeError, ValueError):
            min_amount = max_amount = None
        rules.append(
            Rule(
                id=str(raw.get("id") or f"rule-{idx}"),
                category=category,
                peer=str(raw.get("peer") or ""),
                item=str(raw.get("item") or ""),
                category_match=str(raw.get("category_match") or raw.get("bill_category") or ""),
                type=str(raw.get("type") or ""),
                min_amount=min_amount,
                max_amount=max_amount,
                tags=[str(t) for t in (raw.get("tags") or [])][:5],
            )
        )
    rules.sort(key=lambda r: (-r.specificity(), r.is_regex(), r.id))
    return rules


@dataclass
class ClassifyResult:
    category: str
    rule_id: str
    matched: list[str]
    fallback: bool
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "rule_id": self.rule_id,
            "matched": self.matched,
            "fallback": self.fallback,
            "tags": self.tags,
        }


def classify_with_rules(
    *,
    peer: str = "",
    item: str = "",
    bill_category: str = "",
    direction: str = "",
    amount: float = 0.0,
    rules: list[Rule] | None = None,
    fallback_category: str = DEFAULT_CATEGORY,
) -> ClassifyResult:
    """按规则匹配，返回可解释结果。

    direction: "收入" / "支出"（空表示不参与）。amount 取绝对值参与区间比较。
    """
    compiled = rules if rules is not None else compile_rules()
    text_peer = peer or ""
    text_item = item or ""
    text_cat = bill_category or ""
    abs_amount = abs(float(amount or 0))

    for rule in compiled:
        if not _matches(rule.peer, text_peer):
            continue
        if not _matches(rule.item, text_item):
            continue
        if not _matches(rule.category_match, text_cat):
            continue
        if rule.type and rule.type not in direction:
            continue
        if rule.min_amount is not None and abs_amount < rule.min_amount:
            continue
        if rule.max_amount is not None and abs_amount > rule.max_amount:
            continue
        matched = [
            name
            for name, value in (
                ("peer", rule.peer),
                ("item", rule.item),
                ("bill_category", rule.category_match),
                ("type", rule.type),
                ("amount", "range" if rule.min_amount is not None or rule.max_amount is not None else ""),
            )
            if value
        ]
        return ClassifyResult(
            category=rule.category,
            rule_id=rule.id,
            matched=matched,
            fallback=False,
            tags=rule.tags,
        )

    return ClassifyResult(
        category=fallback_category,
        rule_id="fallback",
        matched=[],
        fallback=True,
        tags=["needs_review"],
    )


def explain(
    transactions: list[dict[str, Any]], rules: list[Rule] | None = None
) -> dict[str, Any]:
    """批量归类并给出统计：各分类命中数、兜底比例、命中规则分布。

    用于「规则调优」：兜底比例高说明规则覆盖不足，应补规则而不是继续人工改分类。
    """
    compiled = rules if rules is not None else compile_rules()
    results = []
    by_category: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    fallback = 0
    for t in transactions:
        r = classify_with_rules(
            peer=str(t.get("peer") or t.get("counterparty") or ""),
            item=str(t.get("item") or t.get("description") or ""),
            bill_category=str(t.get("bill_category") or t.get("category") or ""),
            direction=str(t.get("direction") or ("收入" if float(t.get("amount") or 0) > 0 else "支出")),
            amount=float(t.get("amount") or 0),
            rules=compiled,
        )
        results.append({**t, **r.to_dict()})
        by_category[r.category] = by_category.get(r.category, 0) + 1
        by_rule[r.rule_id] = by_rule.get(r.rule_id, 0) + 1
        if r.fallback:
            fallback += 1
    total = len(transactions)
    return {
        "results": results,
        "total": total,
        "fallback": fallback,
        "fallback_pct": round(fallback / total * 100, 1) if total else 0.0,
        "by_category": by_category,
        "by_rule": by_rule,
        "rule_count": len(compiled),
        "hint": "兜底比例偏高时优先补 peer/item 规则，而不是继续人工改分类"
        if total and fallback / total > 0.3
        else "",
    }
