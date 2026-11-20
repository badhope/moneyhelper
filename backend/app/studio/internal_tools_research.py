"""科研写作工具：大纲、引用格式化、文献检索规划。

从 internal_tools.py 拆出；确定性计算，不联网、不依赖第三方库。
"""

from __future__ import annotations

import re
from typing import Any

from .internal_tools_common import _fail

STYLE_ALIASES = {
    "gb/t 7714": "gbt7714",
    "gbt7714": "gbt7714",
    "gb7714": "gbt7714",
    "apa": "apa",
    "apa7": "apa",
    "mla": "mla",
    "chicago": "chicago",
}

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
