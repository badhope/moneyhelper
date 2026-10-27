"""内置科研工具：确定性计算，不联网、不依赖第三方库。

这些是项目自研的「优势工具」，只在内部 Agent 工具面暴露，不通过 MCP Server 对外开放。
用户可在「设置 → 内置工具」逐个开关；关闭后对应工具从模型工具面移除。
"""

from __future__ import annotations

import csv
import io
import math
import re
import statistics
from typing import Any

STYLE_ALIASES = {
    "gb/t 7714": "gbt7714",
    "gbt7714": "gbt7714",
    "gb7714": "gbt7714",
    "apa": "apa",
    "apa7": "apa",
    "mla": "mla",
    "chicago": "chicago",
}


def _fail(msg: str) -> str:
    return f"错误：{msg}"


def research_outline(args: dict[str, Any]) -> str:
    """按论文类型生成结构大纲（含每节写作要点）。"""
    topic = str(args.get("topic") or "").strip()
    ptype = str(args.get("paper_type") or "empirical").strip().lower()
    if not topic:
        return _fail("topic 必填")
    templates = {
        "empirical": [
            ("摘要", "背景一句、方法一句、主要结果（含效应量与置信区间）、结论一句"),
            ("引言", "研究问题、现实意义、文献缺口、本文贡献"),
            ("文献综述与假设", "理论框架、竞争性假设、可检验的预测"),
            ("数据与方法", "样本来源与筛选、变量定义、识别策略、稳健性设计"),
            ("描述性统计", "样本分布、主要变量均值/标准差、相关性矩阵"),
            ("实证结果", "主回归、机制检验、异质性分析"),
            ("稳健性检验", "替换度量、子样本、安慰剂检验、内生性处理"),
            ("讨论", "结果解释、与文献对话、理论与管理启示"),
            ("局限与未来研究", "数据局限、外部效度、未解释的变异"),
            ("参考文献", "统一引用格式，正文与文献表一一对应"),
        ],
        "review": [
            ("摘要", "综述范围、检索策略、主要发现、研究空白"),
            ("引言", "为何此时需要综述、与既有综述的差异"),
            ("方法", "数据库、检索式、纳排标准、筛选流程（PRISMA）"),
            ("文献特征", "年份/地区/方法/样本分布"),
            ("主题综合", "按主题或理论聚类，比较结论冲突"),
            ("证据质量", "偏倚风险、证据等级、异质性来源"),
            ("研究空白与议程", "可操作的未来研究问题"),
            ("结论", "对实践与政策的含义"),
            ("参考文献", "统一引用格式"),
        ],
        "thesis": [
            ("摘要", "研究目的、方法、结果、贡献"),
            ("绪论", "背景、问题、目标、研究问题、章节安排"),
            ("文献综述", "概念界定、理论、实证进展、缺口"),
            ("研究设计", "框架、变量、数据、方法"),
            ("数据分析", "描述统计、假设检验、稳健性"),
            ("结论与建议", "主要结论、理论贡献、实践建议、局限"),
            ("参考文献与附录", "问卷、代码、补充表"),
        ],
        "grant": [
            ("立项依据", "科学问题、现状与缺口、假说"),
            ("研究目标", "总体目标与可考核的分目标"),
            ("研究内容", "3-4 个相互支撑的工作包"),
            ("研究方案", "技术路线、实验设计、关键参数"),
            ("可行性分析", "团队、平台、预实验数据"),
            ("创新点", "理论/方法/数据层面的增量"),
            ("预期成果", "论文、专利、数据集、政策建议"),
            ("进度与预算", "里程碑、经费科目"),
        ],
    }
    sections = templates.get(ptype)
    if sections is None:
        return _fail(f"paper_type 仅支持 {'/'.join(templates)}")
    lines = [f"《{topic}》结构大纲（{ptype}）"]
    for i, (title, hint) in enumerate(sections, 1):
        lines.append(f"{i}. {title} —— {hint}")
    return "\n".join(lines)


def _authors(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    parts = re.split(r"[;,，；]\s*", text)
    return [p.strip() for p in parts if p.strip()]


def citation_format(args: dict[str, Any]) -> str:
    """把文献元数据格式化为指定引用样式。"""
    items = args.get("items")
    if not isinstance(items, list) or not items:
        return _fail("items 必须是非空数组")
    style_raw = str(args.get("style") or "gbt7714").strip().lower()
    style = STYLE_ALIASES.get(style_raw)
    if style is None:
        return _fail("style 仅支持 GB/T 7714、APA 7、MLA 9、Chicago")
    out: list[str] = []
    for idx, item in enumerate(items, 1):
        if not isinstance(item, dict):
            return _fail(f"第 {idx} 条不是对象")
        authors = _authors(item.get("authors"))
        title = str(item.get("title") or "").strip()
        if not title:
            return _fail(f"第 {idx} 条缺 title")
        container = str(item.get("journal") or item.get("publisher") or "").strip()
        year = str(item.get("year") or "").strip()
        volume = str(item.get("volume") or "").strip()
        issue = str(item.get("issue") or "").strip()
        pages = str(item.get("pages") or "").strip()
        doi = str(item.get("doi") or "").strip()
        url = str(item.get("url") or "").strip()
        if style == "gbt7714":
            a = ", ".join(authors[:3]) + (", 等" if len(authors) > 3 else "")
            seg = f"{a}. {title}[J]. {container}"
            if year:
                seg += f", {year}"
            if volume:
                seg += f", {volume}"
            if issue:
                seg += f"({issue})"
            if pages:
                seg += f": {pages}"
            seg += "."
            if doi:
                seg += f" DOI: {doi}."
        elif style == "apa":
            if not authors:
                a = ""
            elif len(authors) == 1:
                a = authors[0]
            elif len(authors) <= 20:
                a = ", ".join(authors[:-1]) + ", & " + authors[-1]
            else:
                a = ", ".join(authors[:19]) + ", ... " + authors[-1]
            seg = f"{a} ({year}). {title}. {container}"
            if volume:
                seg += f", {volume}"
            if issue:
                seg += f"({issue})"
            if pages:
                seg += f", {pages}"
            seg += "."
            if doi:
                seg += f" https://doi.org/{doi}"
            elif url:
                seg += f" {url}"
        elif style == "mla":
            a = ", ".join(authors[:2]) + (", et al" if len(authors) > 2 else "")
            seg = f'{a}. "{title}." {container}'
            if volume:
                seg += f", vol. {volume}"
            if issue:
                seg += f", no. {issue}"
            if year:
                seg += f", {year}"
            if pages:
                seg += f", pp. {pages}"
            seg += "."
            if doi:
                seg += f" DOI: {doi}."
        else:
            a = ", ".join(authors)
            seg = f'{a}. "{title}." {container}'
            if year:
                seg += f" ({year})"
            if volume:
                seg += f", {volume}"
            if issue:
                seg += f"({issue})"
            if pages:
                seg += f": {pages}"
            seg += "."
            if doi:
                seg += f" https://doi.org/{doi}"
        out.append(f"[{idx}] {seg}")
    return "\n".join(out)


def literature_search_plan(args: dict[str, Any]) -> str:
    """生成 PICO / 布尔检索式与纳排标准。"""
    question = str(args.get("question") or "").strip()
    if not question:
        return _fail("question 必填")
    databases = str(args.get("databases") or "Web of Science, Scopus, PubMed, CNKI, Google Scholar")
    years = str(args.get("years") or "近 10 年")
    keywords = [k.strip() for k in re.split(r"[,，;；、\s]+", question) if len(k.strip()) > 1][:8]
    if not keywords:
        keywords = [question[:20]]
    bool_query = " AND ".join(f'"{k}"' for k in keywords[:3]) or f'"{question[:20]}"'
    or_block = " OR ".join(f'"{k}"' for k in keywords)
    lines = [
        "检索方案",
        f"研究问题：{question}",
        f"数据库：{databases}",
        f"时间范围：{years}",
        "",
        "PICO 拆解：",
        "- P（人群/对象）：请在问题中补齐样本特征（行业、地区、年龄、数据层级）",
        f"- I（干预/暴露）：{keywords[0] if keywords else '待补'}",
        f"- C（对照）：{keywords[1] if len(keywords) > 1 else '待补'}",
        f"- O（结局）：{keywords[2] if len(keywords) > 2 else '待补'}",
        "",
        f"核心布尔式：({or_block}) AND ({bool_query})",
        '限定：TI/AB 字段，document type = Article/Review（视数据库）',
        "",
        "纳入标准：",
        "1. 直接回答研究问题或提供关键机制证据；",
        "2. 数据与方法可核查（样本、测量、统计方法完整）；",
        "3. 同行评议期刊或权威工作论文；",
        "4. 语言：中/英文。",
        "排除标准：",
        "1. 缺少方法细节的评论、社论、新闻稿；",
        "2. 样本与目标人群明显不匹配；",
        "3. 重复发表或同一数据源的冗余报告（保留信息量最大的一篇）。",
        "",
        "筛选流程：标题/摘要初筛 → 全文复筛 → 滚雪球（前向引用 + 参考文献）→ 记录排除原因与数量（PRISMA）。",
    ]
    return "\n".join(lines)


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


INTERNAL_TOOL_SPECS: dict[str, dict[str, Any]] = {
    "research_outline": {
        "description": "科研大纲生成器：按论文类型（empirical/review/thesis/grant）输出结构化大纲与每节写作要点。",
        "impl": research_outline,
    },
    "citation_format": {
        "description": "引用格式化：把文献元数据批量格式化为 GB/T 7714、APA 7、MLA 9 或 Chicago。",
        "impl": citation_format,
    },
    "literature_search_plan": {
        "description": "检索式构造器：按研究问题生成 PICO 拆解、布尔检索式与纳排标准。",
        "impl": literature_search_plan,
    },
    "dataset_profile": {
        "description": "数据画像：对 CSV 文本输出行列数、类型、缺失率、数值分布与高频取值。",
        "impl": dataset_profile,
    },
    "stats_summary": {
        "description": "统计摘要：样本量、均值/中位数/标准差、分位数、95% 置信区间、异常值与偏度。",
        "impl": stats_summary,
    },
    "sensitivity_analysis": {
        "description": "敏感性分析：对基准值做 ±N% 网格，输出各档结果与变化量。",
        "impl": sensitivity_analysis,
    },
    "experiment_design_check": {
        "description": "实验设计核查：设计类型、随机化、盲法、样本量与偏倚风险清单。",
        "impl": experiment_design_check,
    },
    "source_quality_score": {
        "description": "来源可信度评分：按同行评议、期刊层级、方法透明度、时效与引用给出 0-100 分与理由。",
        "impl": source_quality_score,
    },
}

INTERNAL_TOOL_INPUTS: dict[str, dict[str, Any]] = {
    "research_outline": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "研究主题/论文标题"},
            "paper_type": {
                "type": "string",
                "enum": ["empirical", "review", "thesis", "grant"],
                "description": "论文类型，默认 empirical",
            },
        },
        "required": ["topic"],
        "additionalProperties": False,
    },
    "citation_format": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "文献数组，每项含 title/authors/year/journal/volume/issue/pages/doi",
                "items": {"type": "object"},
            },
            "style": {"type": "string", "description": "gbt7714/APA/MLA/Chicago，默认 gbt7714"},
        },
        "required": ["items"],
        "additionalProperties": False,
    },
    "literature_search_plan": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "研究问题"},
            "databases": {"type": "string", "description": "数据库，可省略"},
            "years": {"type": "string", "description": "时间范围，可省略"},
        },
        "required": ["question"],
        "additionalProperties": False,
    },
    "dataset_profile": {
        "type": "object",
        "properties": {
            "csv_text": {"type": "string", "description": "CSV 文本（含表头）"},
            "max_columns": {"type": "integer", "description": "最多分析列数，默认 20"},
        },
        "required": ["csv_text"],
        "additionalProperties": False,
    },
    "stats_summary": {
        "type": "object",
        "properties": {"values": {"type": "array", "items": {"type": "number"}, "description": "数值数组"}},
        "required": ["values"],
        "additionalProperties": False,
    },
    "sensitivity_analysis": {
        "type": "object",
        "properties": {
            "base_value": {"type": "number", "description": "基准值"},
            "variable": {"type": "string", "description": "变量名称"},
            "pct_range": {"type": "number", "description": "波动百分比，默认 20"},
            "steps": {"type": "integer", "description": "单侧档数，默认 4"},
        },
        "required": ["base_value"],
        "additionalProperties": False,
    },
    "experiment_design_check": {
        "type": "object",
        "properties": {
            "design": {"type": "string", "description": "rct/quasi/cohort/case-control/cross-section/ab-test/pre-post"},
            "sample_size": {"type": "integer", "description": "样本量"},
            "randomized": {"type": "boolean", "description": "是否随机化"},
            "blinding": {"type": "string", "description": "none/single/double"},
        },
        "required": ["design"],
        "additionalProperties": False,
    },
    "source_quality_score": {
        "type": "object",
        "properties": {
            "peer_reviewed": {"type": "boolean", "description": "是否同行评议"},
            "venue_tier": {"type": "string", "description": "top/q1/q2/q3/q4/unknown"},
            "methods_detail": {"type": "string", "description": "full/partial/none"},
            "year": {"type": "integer", "description": "发表年份"},
            "citations": {"type": "integer", "description": "被引次数"},
        },
        "required": [],
        "additionalProperties": False,
    },
}

INTERNAL_FUNCTION_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": spec["description"],
            "parameters": INTERNAL_TOOL_INPUTS[name],
        },
    }
    for name, spec in INTERNAL_TOOL_SPECS.items()
]


def run_internal_tool(name: str, args: dict[str, Any]) -> str | None:
    spec = INTERNAL_TOOL_SPECS.get(name)
    if spec is None:
        return None
    try:
        return spec["impl"](args or {})
    except Exception as exc:  # noqa: BLE001 — 工具失败回填错误串，不炸主循环
        return f"工具执行失败：{type(exc).__name__}: {exc}"
