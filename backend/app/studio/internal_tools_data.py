"""数据探查工具：字段推断、数据集画像、统计摘要、敏感性分析、实验设计检查。

从 internal_tools.py 拆出；确定性计算，不联网、不依赖第三方库。
"""

from __future__ import annotations

import csv
import io
import math
import re
import statistics
from typing import Any

from .internal_tools_common import _fail


def _infer_column(values: list[str]) -> str:
    non_empty = [v for v in values if v.strip() != ""]
    if not non_empty:
        return "empty"
    numeric = 0
    for v in non_empty:
        try:
            float(v.replace(",", "").replace("%", ""))
            numeric += 1
        except ValueError:
            pass
    if numeric / len(non_empty) >= 0.9:
        return "numeric"
    dates = 0
    for v in non_empty[:50]:
        if re.match(r"^\d{4}[-/]\d{1,2}([-/]\d{1,2})?$", v.strip()):
            dates += 1
    if dates / max(1, len(non_empty[:50])) >= 0.8:
        return "date"
    return "text"

def dataset_profile(args: dict[str, Any]) -> str:
    """对 CSV 文本做结构画像：行列数、缺失率、类型、数值分布、分类取值。"""
    csv_text = str(args.get("csv_text") or "")
    if not csv_text.strip():
        return _fail("csv_text 必填")
    try:
        rows = list(csv.reader(io.StringIO(csv_text.strip())))
    except csv.Error as exc:
        return _fail(f"CSV 解析失败：{exc}")
    if len(rows) < 2:
        return _fail("至少需要表头与一行数据")
    header = [h.strip() or f"col{i + 1}" for i, h in enumerate(rows[0])]
    data = rows[1:]
    total = len(data)
    lines = [f"数据画像：{total} 行 × {len(header)} 列"]
    max_cols = int(args.get("max_columns") or 20)
    for idx, name in enumerate(header[:max_cols]):
        col = [r[idx] if idx < len(r) else "" for r in data]
        missing = sum(1 for v in col if not v.strip())
        kind = _infer_column(col)
        detail = f"- {name}：类型 {kind}，缺失 {missing}/{total}（{missing / total:.1%}）"
        if kind == "numeric":
            nums = []
            for v in col:
                try:
                    nums.append(float(v.replace(",", "").replace("%", "")))
                except ValueError:
                    continue
            if nums:
                detail += (
                    f"，均值 {statistics.mean(nums):.4g}，中位数 {statistics.median(nums):.4g}，"
                    f"最小 {min(nums):.4g}，最大 {max(nums):.4g}"
                )
        elif kind == "text":
            counts: dict[str, int] = {}
            for v in col:
                if v.strip():
                    counts[v.strip()] = counts.get(v.strip(), 0) + 1
            top = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
            detail += "，高频值：" + "、".join(f"{k}({v})" for k, v in top)
        lines.append(detail)
    if len(header) > max_cols:
        lines.append(f"（仅显示前 {max_cols} 列，共 {len(header)} 列）")
    return "\n".join(lines)

def _floats(raw: Any) -> list[float]:
    if isinstance(raw, list):
        vals = raw
    else:
        vals = re.split(r"[,，\s;；]+", str(raw or "").strip())
    out: list[float] = []
    for v in vals:
        if isinstance(v, (int, float)):
            out.append(float(v))
            continue
        try:
            out.append(float(str(v).strip()))
        except ValueError:
            continue
    return out

def stats_summary(args: dict[str, Any]) -> str:
    """描述统计：集中趋势、离散度、分位数、95% 置信区间、异常值。"""
    vals = _floats(args.get("values"))
    if len(vals) < 2:
        return _fail("至少需要两个数值")
    n = len(vals)
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals)
    q = statistics.quantiles(vals, n=4) if n >= 4 else [min(vals), statistics.median(vals), max(vals)]
    iqr = q[2] - q[0]
    lo, hi = q[0] - 1.5 * iqr, q[2] + 1.5 * iqr
    outliers = [v for v in vals if v < lo or v > hi]
    se = sd / math.sqrt(n)
    ci = (mean - 1.96 * se, mean + 1.96 * se)
    skew = 0.0
    if sd:
        skew = sum((v - mean) ** 3 for v in vals) / (n * sd**3)
    lines = [
        f"样本量 n = {n}",
        f"均值 {mean:.4f}，中位数 {statistics.median(vals):.4f}，标准差 {sd:.4f}",
        f"最小 {min(vals):.4f}，Q1 {q[0]:.4f}，Q3 {q[2]:.4f}，最大 {max(vals):.4f}",
        f"95% 置信区间（正态近似）[{ci[0]:.4f}, {ci[1]:.4f}]",
        f"IQR {iqr:.4f}，异常值 {len(outliers)} 个" + (f"：{outliers[:10]}" if outliers else ""),
        f"偏度 {skew:.3f}（|偏度|>1 提示分布明显偏斜，均值解释需谨慎）",
    ]
    return "\n".join(lines)

def sensitivity_analysis(args: dict[str, Any]) -> str:
    """单变量敏感性分析：基准值在 ±N% 网格内的结果变化。"""
    try:
        base = float(args.get("base_value"))
    except (TypeError, ValueError):
        return _fail("base_value 必须是数字")
    pct = float(args.get("pct_range") or 20)
    steps = int(args.get("steps") or 4)
    if pct <= 0 or pct > 200:
        return _fail("pct_range 需在 (0, 200]")
    steps = max(1, min(20, steps))
    label = str(args.get("variable") or "变量")
    lines = [f"{label} 敏感性分析（基准 {base:.4g}，范围 ±{pct:g}%，{steps * 2 + 1} 档）"]
    for i in range(-steps, steps + 1):
        factor = 1 + (pct / 100) * (i / steps)
        value = base * factor
        lines.append(f"- {factor * 100:6.1f}% → {value:.4f}（变化 {value - base:+.4f}）")
    return "\n".join(lines)

def experiment_design_check(args: dict[str, Any]) -> str:
    """实验设计自查：设计类型、样本量、随机化、盲法、偏倚风险清单。"""
    design = str(args.get("design") or "").strip().lower()
    sample = int(args.get("sample_size") or 0)
    randomize = bool(args.get("randomized", False))
    blinded = str(args.get("blinding") or "none").lower()
    valid = {
        "rct": "随机对照试验",
        "quasi": "准实验",
        "cohort": "队列研究",
        "case-control": "病例对照",
        "cross-section": "横断面",
        "ab-test": "A/B 测试",
        "pre-post": "前后测",
    }
    if design not in valid:
        return _fail(f"design 仅支持 {'/'.join(valid)}")
    issues: list[str] = []
    if design in ("rct", "ab-test") and not randomize:
        issues.append("声称随机但未随机化：结论只能作为准实验证据")
    if design in ("rct", "ab-test", "cohort") and blinded == "none":
        issues.append("无盲法：存在测量偏倚与期望效应，建议至少评估者盲")
    if sample < 30:
        issues.append("样本量 <30：估计不稳定，置信区间会过宽")
    if design == "case-control":
        issues.append("病例对照需明确对照来源与匹配变量，避免选择偏倚")
    checklist = [
        "预注册或分析计划（防止事后挑结果）",
        "主要结局与次要结局事先定义",
        "样本量/功效计算依据",
        "随机化与分配隐藏（如适用）",
        "缺失数据处理方案",
        "多重比较校正",
        "效应量与置信区间（不只报 p 值）",
        "数据与代码可复现材料",
    ]
    lines = [
        f"设计类型：{valid[design]}",
        f"样本量：{sample}",
        f"随机化：{'是' if randomize else '否'}；盲法：{blinded}",
        "",
        "风险提示：" + ("无" if not issues else ""),
    ]
    lines.extend(f"- {x}" for x in issues)
    lines.append("")
    lines.append("设计自查清单：")
    lines.extend(f"□ {x}" for x in checklist)
    return "\n".join(lines)
