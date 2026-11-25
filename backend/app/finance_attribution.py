"""收支归因候选（4.17.1）：规则与历史只给候选，不直接改账。

设计约束：
- 规则来自 `categorize.py`，不在这里复制关键词表；
- 历史只统计“用户账本里已经有明确分类”的同类摘要，避免把“其他”学成新分类；
- 每条候选都带来源、规则 id、命中维度、置信度；用户确认后才写回分类；
- 没有命中时明确返回 `fallback`，不编一个看起来合理的分类。
"""

from __future__ import annotations

import re
from typing import Any

from .categorize import BUILTIN_RULES, classify_with_rules

MAX_CATEGORY_LEN = 20
_SPACE = re.compile(r"\s+")


def _clean_text(value: Any) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()


def _normalize_item(value: Any) -> str:
    """同类商户归并：去空白、去尾部订单号/日期，避免每笔都被当成新商户。"""
    text = _clean_text(value).lower()
    text = re.sub(r"[0-9]{6,}", "", text)
    text = re.sub(r"[（(].*?[）)]", "", text)
    return text[:40]


def _direction(amount: float) -> str:
    return "收入" if float(amount or 0) > 0 else "支出"


def _history_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    index: dict[str, dict[str, int]] = {}
    for tx in rows:
        key = _normalize_item(tx.get("item"))
        cat = _clean_text(tx.get("category"))
        if not key or not cat or cat in {"其他", "未分类"}:
            continue
        bucket = index.setdefault(key, {})
        bucket[cat] = bucket.get(cat, 0) + 1
    return index


def _top_history(bucket: dict[str, int], limit: int = 3) -> list[tuple[str, int]]:
    return sorted(bucket.items(), key=lambda x: (-x[1], x[0]))[:limit]


def _rule_specificity(rule_id: str, matched: list[str]) -> int:
    # matched 是规则的非空维度名，直接作为具体度；不依赖规则对象内部状态。
    return max(1, len(matched))


def _match_custom_rule(
    item: str,
    direction: str,
    custom_rules: list[dict[str, Any]],
    amount: float = 0,
    owner_id: int | None = None,
) -> dict[str, Any] | None:
    text = _clean_text(item).lower()
    amount_cents = abs(round(float(amount or 0) * 100))
    ordered = sorted(
        custom_rules,
        key=lambda r: (-int(r.get("priority") or 0), str(r.get("created_at") or "")),
    )
    for rule in ordered:
        if int(rule.get("enabled", 1) or 0) != 1:
            continue
        keyword = _clean_text(rule.get("keyword")).lower()
        category = _clean_text(rule.get("category"))
        rule_direction = _clean_text(rule.get("direction"))
        merchant = _clean_text(rule.get("merchant")).lower()
        if not keyword or not category:
            continue
        if rule_direction and rule_direction != direction:
            continue
        if keyword not in text:
            continue
        if merchant and merchant not in text:
            continue
        min_cents = int(rule.get("min_amount_cents") or 0)
        max_cents = int(rule.get("max_amount_cents") or 0)
        if min_cents > 0 and amount_cents < min_cents:
            continue
        if max_cents > 0 and amount_cents > max_cents:
            continue
        member_id = rule.get("member_id")
        if member_id not in (None, "", 0) and int(member_id) != int(owner_id or 0):
            continue
        return rule
    return None


def category_options(custom_rules: list[dict[str, Any]] | None = None) -> list[str]:
    seen: list[str] = []
    for rule in [*BUILTIN_RULES, *(custom_rules or [])]:
        cat = _clean_text(rule.get("category"))
        if cat and cat not in seen:
            seen.append(cat)
    return seen


def suggest_attributions(
    rows: list[dict[str, Any]],
    confirmations: dict[int, dict[str, Any]] | None = None,
    limit: int = 50,
    custom_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    confirmed = confirmations or {}
    history = _history_index(rows)
    pending: list[dict[str, Any]] = []
    resolved = 0
    rule_hits: dict[str, int] = {}

    for tx in rows:
        try:
            tx_id = int(tx.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if tx_id <= 0:
            continue
        if tx_id in confirmed:
            resolved += 1
            continue

        item = _clean_text(tx.get("item"))
        amount = float(tx.get("amount") or 0)
        current = _clean_text(tx.get("category")) or "其他"
        direction = _direction(amount)
        rule = classify_with_rules(
            item=item,
            bill_category=current,
            direction=direction,
            amount=amount,
        )
        custom = _match_custom_rule(
            item, direction, custom_rules or [], amount=amount, owner_id=tx.get("owner_id")
        )
        if custom is not None:
            custom_id = str(custom.get("rule_id") or "")
            rule_hits[custom_id] = rule_hits.get(custom_id, 0) + 1

        bucket = history.get(_normalize_item(item), {})
        history_top = _top_history(bucket)
        history_cat, history_count = history_top[0] if history_top else ("", 0)

        candidate_category = (
            _clean_text(custom.get("category")) if custom is not None else rule.category
        )
        alternatives: list[dict[str, Any]] = []
        if not rule.fallback and rule.category != candidate_category:
            alternatives.append({"category": rule.category, "source": "rule", "confidence": 0.7})
        for cat, count in history_top:
            if cat == candidate_category:
                continue
            if cat == history_cat and custom is None and rule.fallback:
                continue
            alternatives.append(
                {
                    "category": cat,
                    "source": "history",
                    "confidence": round(min(0.72, 0.5 + 0.05 * min(count, 6)), 2),
                    "count": count,
                }
            )

        if custom is not None:
            custom_id = str(custom.get("rule_id") or "")
            keyword = _clean_text(custom.get("keyword"))
            name = _clean_text(custom.get("name")) or keyword
            dimensions = [f"keyword:{keyword}"[:24]]
            detail = [f"关键词「{keyword}」"]
            merchant = _clean_text(custom.get("merchant"))
            if merchant:
                dimensions.append(f"merchant:{merchant}"[:24])
                detail.append(f"商户「{merchant}」")
            min_cents = int(custom.get("min_amount_cents") or 0)
            max_cents = int(custom.get("max_amount_cents") or 0)
            if min_cents or max_cents:
                dimensions.append("amount")
                if min_cents and max_cents:
                    detail.append(f"金额 {min_cents / 100:.2f}-{max_cents / 100:.2f} 元")
                elif min_cents:
                    detail.append(f"金额 ≥ {min_cents / 100:.2f} 元")
                else:
                    detail.append(f"金额 ≤ {max_cents / 100:.2f} 元")
            if custom.get("member_id") not in (None, "", 0):
                dimensions.append(f"member:{int(custom['member_id'])}")
                detail.append(f"成员 #{int(custom['member_id'])}")
            candidate = {
                "category": _clean_text(custom.get("category")),
                "source": "custom_rule",
                "confidence": 0.92,
                "rule_id": custom_id,
                "matched": dimensions,
                "reason": f"自定义规则「{name}」命中" + "、".join(detail),
            }
        elif not rule.fallback:
            specificity = _rule_specificity(rule.rule_id, rule.matched)
            candidate = {
                "category": rule.category,
                "source": "rule",
                "confidence": round(min(0.92, 0.64 + 0.07 * specificity), 2),
                "rule_id": rule.rule_id,
                "matched": rule.matched,
                "reason": f"命中规则 {rule.rule_id}（{'/'.join(rule.matched) or '兜底维度'}）",
            }
        elif history_count >= 2:
            candidate = {
                "category": history_cat,
                "source": "history",
                "confidence": round(min(0.78, 0.5 + 0.05 * min(history_count, 6)), 2),
                "rule_id": "",
                "matched": ["history"],
                "reason": f"历史同类 {history_count} 笔多为「{history_cat}」",
            }
        elif current not in {"其他", "未分类"}:
            candidate = {
                "category": current,
                "source": "existing",
                "confidence": 0.9,
                "rule_id": "",
                "matched": ["ledger"],
                "reason": "账本已有明确分类，仅待确认",
            }
        else:
            candidate = {
                "category": "",
                "source": "fallback",
                "confidence": 0.0,
                "rule_id": "fallback",
                "matched": [],
                "reason": "无规则命中，需人工选择",
            }

        alternatives = [a for a in alternatives if a["category"] != candidate["category"]]
        needs_review = current in {"其他", "未分类"} or candidate["source"] == "fallback"
        if not needs_review:
            continue

        pending.append(
            {
                "transaction_id": tx_id,
                "date": _clean_text(tx.get("date")),
                "item": item,
                "amount": round(amount, 2),
                "direction": direction,
                "current_category": current,
                "candidate": candidate,
                "alternatives": alternatives[:3],
                "needs_review": True,
            }
        )

    total = len(rows)
    return {
        "transactions": pending[: max(1, min(int(limit or 50), 200))],
        "pending": len(pending),
        "resolved": resolved,
        "total": total,
        "coverage": round((total - len(pending)) / total * 100, 1) if total else 0.0,
        "categories": category_options(custom_rules),
        "custom_rule_hits": rule_hits,
        "source": "rules+history",
        "boundary": (
            "候选来自自定义规则、内置规则与账本历史，不是模型猜测；未命中时返回 fallback，"
            "确认前不改动流水分类。"
        ),
    }


def validate_category(value: Any) -> str:
    cat = _clean_text(value)
    if not cat or cat in {"其他", "未分类"}:
        raise ValueError("分类不能为空或“其他”")
    if len(cat) > MAX_CATEGORY_LEN:
        raise ValueError(f"分类不能超过 {MAX_CATEGORY_LEN} 个字")
    if any(ord(ch) < 32 for ch in cat):
        raise ValueError("分类不能包含控制字符")
    return cat


__all__ = ["category_options", "suggest_attributions", "validate_category"]
