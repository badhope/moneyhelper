"""来源可信度评分：同行评议、层级、方法透明度、时效与引用。

从 internal_tools.py 拆出；确定性计算，不联网、不依赖第三方库。
"""

from __future__ import annotations

from typing import Any


def source_quality_score(args: dict[str, Any]) -> str:
    """来源可信度评分（0-100）：同行评议、期刊层级、方法透明度、时效、引用。"""
    peer = bool(args.get("peer_reviewed", False))
    tier = str(args.get("venue_tier") or "unknown").lower()
    methods = str(args.get("methods_detail") or "partial").lower()
    year = int(args.get("year") or 0)
    citations = int(args.get("citations") or 0)
    score = 0
    reasons: list[str] = []
    if peer:
        score += 30
        reasons.append("同行评议 +30")
    else:
        reasons.append("非同行评议 +0")
    tier_pts = {"top": 25, "q1": 22, "q2": 16, "q3": 10, "q4": 6, "unknown": 8}
    pts = tier_pts.get(tier, 8)
    score += pts
    reasons.append(f"期刊层级 {tier} +{pts}")
    method_pts = {"full": 25, "partial": 15, "none": 5}
    mpts = method_pts.get(methods, 10)
    score += mpts
    reasons.append(f"方法透明度 {methods} +{mpts}")
    if year:
        import datetime as _dt

        age = _dt.date.today().year - year
        if age <= 2:
            score += 15
            reasons.append("近 2 年 +15")
        elif age <= 5:
            score += 10
            reasons.append("近 5 年 +10")
        elif age <= 10:
            score += 5
            reasons.append("近 10 年 +5")
    if citations >= 100:
        score += 10
        reasons.append("引用 ≥100 +10")
    elif citations >= 20:
        score += 6
        reasons.append("引用 ≥20 +6")
    score = max(0, min(100, score))
    if score >= 80:
        band = "高可信（可作为主要证据）"
    elif score >= 60:
        band = "中高（可用，需交叉验证）"
    elif score >= 40:
        band = "中等（作为补充证据）"
    else:
        band = "低（谨慎使用，优先找替代来源）"
    return f"来源可信度 {score}/100 —— {band}\n" + "\n".join(f"- {r}" for r in reasons)
