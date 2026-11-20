"""Studio 目录条目：技能包：文档处理、元能力、写作与科研技能。

条目是纯数据（dict 字面量），按站内顺序切段拆出，拼接顺序与原文件一致。
"""

from __future__ import annotations

from typing import Any

from .market_sources import (
    _ACADEMIC,
    _ANTHROPIC,
    _PAPER,
    _RESEARCH,
)

ITEMS: tuple[dict[str, Any], ...] = (
    {
        "id": "skill-pdf",
        "name": "PDF 工具链",
        "kind": "skills",
        "aliases": ["pdf"],
        "category": "文档",
        "source": _ANTHROPIC,
        "url": "https://github.com/anthropics/skills/blob/main/skills/pdf/SKILL.md",
        "stars": 184000,
        "description": "读取、拆分、合并、填写 PDF 表单与提取表格；官方 Agent Skills 参考实现。",
        "asset": {
            "name": "PDF 工具链",
            "description": "读取、拆分、合并、填写 PDF 表单与提取表格",
            "content": "处理 PDF 时：1）先确认页数与是否可提取文本；2）表格优先用结构化提取而不是整页 OCR；3）合并/拆分后核对页序与书签；4）填写表单后回读字段值验证。输出时说明使用的工具与已知局限（扫描件 OCR 误差）。",
            "enabled": True,
        },
    },

    {
        "id": "skill-docx",
        "name": "Word 文档工程",
        "kind": "skills",
        "aliases": ["word", "docx", "文档"],
        "category": "文档",
        "source": _ANTHROPIC,
        "url": "https://github.com/anthropics/skills/blob/main/skills/docx/SKILL.md",
        "stars": 184000,
        "description": "生成与编辑 .docx：样式、页码、目录、批注与修订。",
        "asset": {
            "name": "Word 文档工程",
            "description": "生成与编辑 docx，保留样式与目录",
            "content": "编辑 docx 时：保留既有样式表，不硬编码字体；目录用域更新；插入表格后统一列宽与对齐；交付前检查分页、页眉页脚与编号连续性。",
            "enabled": True,
        },
    },

    {
        "id": "skill-xlsx",
        "name": "电子表格分析",
        "kind": "skills",
        "aliases": ["excel", "xlsx", "表格"],
        "category": "文档",
        "source": _ANTHROPIC,
        "url": "https://github.com/anthropics/skills/blob/main/skills/xlsx/SKILL.md",
        "stars": 184000,
        "description": "Excel 读写、公式、透视与数据清洗的稳定做法。",
        "asset": {
            "name": "电子表格分析",
            "description": "Excel 读写、公式与数据清洗",
            "content": "处理 xlsx：读入时保留原始类型（日期/百分比不要转成字符串）；写入公式后必须重算并核对关键单元格；数据清洗记录每步删除/填充的行数；交付附数据字典。",
            "enabled": True,
        },
    },

    {
        "id": "skill-skill-creator",
        "name": "技能生成器",
        "kind": "skills",
        "aliases": ["技能生成", "skill creator"],
        "category": "元能力",
        "source": _ANTHROPIC,
        "url": "https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md",
        "stars": 184000,
        "description": "按官方规范设计新 skill：命名、触发描述、边界与验收。",
        "asset": {
            "name": "技能生成器",
            "description": "按官方规范设计新 skill",
            "content": "设计新技能时：1）写清触发条件（Use when…）与不适用场景（Do NOT…）；2）步骤可执行、每步有产物；3）给出验收标准与失败处理；4）避免与既有技能重叠，重叠时说明分工。",
            "enabled": True,
        },
    },

    {
        "id": "skill-mcp-builder",
        "name": "MCP 服务构建器",
        "kind": "skills",
        "aliases": ["mcp 构建", "mcp builder"],
        "category": "元能力",
        "source": _ANTHROPIC,
        "url": "https://github.com/anthropics/skills/blob/main/skills/mcp-builder/SKILL.md",
        "stars": 184000,
        "description": "设计并实现 MCP Server：工具粒度、schema、错误语义与安全边界。",
        "asset": {
            "name": "MCP 服务构建器",
            "description": "设计并实现 MCP Server",
            "content": "构建 MCP Server：工具按任务粒度拆分，不要一个工具做所有事；inputSchema 用 additionalProperties:false；失败返回结构化错误而不是抛异常；明确标注写操作并实现审批。",
            "enabled": True,
        },
    },

    {
        "id": "skill-doc-coauthoring",
        "name": "文档协作",
        "kind": "skills",
        "aliases": ["文档协作", "coauthoring"],
        "category": "写作",
        "source": _ANTHROPIC,
        "url": "https://github.com/anthropics/skills/blob/main/skills/doc-coauthoring/SKILL.md",
        "stars": 184000,
        "description": "长文档协作：大纲对齐、分段迭代、版本对比。",
        "asset": {
            "name": "文档协作",
            "description": "长文档协作与版本对比",
            "content": "长文档协作：先对齐大纲与读者；每次只改一个章节并给出改动理由；保留原文版本用于对比；交付时列出未解决的开放问题。",
            "enabled": True,
        },
    },

    {
        "id": "skill-academic-paper",
        "name": "学术论文写作",
        "kind": "skills",
        "aliases": ["论文写作", "academic paper", "写论文"],
        "category": "科研",
        "source": _RESEARCH,
        "url": f"{_RESEARCH}/blob/main/academic-paper/SKILL.md",
        "stars": 54128,
        "description": "从研究问题到成稿的学术论文写作流程（摘要/引言/方法/结果/讨论）。",
        "asset": {
            "name": "学术论文写作",
            "description": "学术论文全流程写作",
            "content": "学术论文写作：摘要写背景-方法-结果-结论四句；引言交代缺口与贡献；方法写到可复现（样本、变量、模型、软件版本）；结果先报效应量与置信区间再报显著性；讨论区分结果解释与推测。",
            "enabled": True,
        },
    },

    {
        "id": "skill-academic-reviewer",
        "name": "论文审稿",
        "kind": "skills",
        "aliases": ["审稿", "reviewer", "同行评审"],
        "category": "科研",
        "source": _RESEARCH,
        "url": f"{_RESEARCH}/blob/main/academic-paper-reviewer/SKILL.md",
        "stars": 54128,
        "description": "按期刊审稿标准给出结构化评审意见（重大/次要问题）。",
        "asset": {
            "name": "论文审稿",
            "description": "结构化审稿意见",
            "content": "审稿：先给 3 句摘要复述证明读懂；再列重大意见（识别、推断、外部效度）；次要意见按页码定位；最后给总体建议（接收/小修/大修/拒稿）与理由。",
            "enabled": True,
        },
    },

    {
        "id": "skill-academic-pipeline",
        "name": "科研流水线",
        "kind": "skills",
        "aliases": ["科研流水线", "pipeline"],
        "category": "科研",
        "source": _RESEARCH,
        "url": f"{_RESEARCH}/blob/main/academic-pipeline/SKILL.md",
        "stars": 54128,
        "description": "检索 → 筛选 → 综合 → 成稿的端到端科研流水线。",
        "asset": {
            "name": "科研流水线",
            "description": "端到端科研工作流",
            "content": "科研流水线：问题界定 → 检索式 → 纳排筛选（记录数量与原因）→ 证据表 → 主题综合 → 成稿 → 复现材料。每阶段产出可核查的中间物，不跳步。",
            "enabled": True,
        },
    },

    {
        "id": "skill-paper-writing",
        "name": "论文写作（彭思达体系）",
        "kind": "skills",
        "aliases": ["论文写作方法", "writing"],
        "category": "科研",
        "source": _PAPER,
        "url": f"{_PAPER}/blob/main/research-paper-writing/SKILL.md",
        "stars": 7850,
        "description": "ML/CV/NLP 论文写作方法：故事线、贡献点与实验设计。",
        "asset": {
            "name": "论文写作（彭思达体系）",
            "description": "ML/CV/NLP 论文写作方法",
            "content": "论文写作：先用一句话讲清「什么问题、为什么难、你怎么做、为什么work」；贡献点不超过三条且可验证；实验围绕贡献点设计消融；写作时每段只讲一件事。",
            "enabled": True,
        },
    },

    {
        "id": "skill-literature-review",
        "name": "文献综述",
        "kind": "skills",
        "aliases": ["文献综述", "literature review"],
        "category": "科研",
        "source": _ACADEMIC,
        "url": f"{_ACADEMIC}/blob/main/scientific-toolkit-skill/references/scientific-skills/literature-review/SKILL.md",
        "stars": 5377,
        "description": "系统检索、证据分级与综述撰写。",
        "asset": {
            "name": "文献综述",
            "description": "系统检索与证据分级",
            "content": "文献综述：明确检索数据库与时间窗；用 PRISMA 记录筛选流程；按主题而非按作者组织；每个结论标注支持/矛盾的研究；最后指出证据缺口。",
            "enabled": True,
        },
    },

    {
        "id": "skill-citation-management",
        "name": "引用管理",
        "kind": "skills",
        "aliases": ["引用", "citation", "bibtex"],
        "category": "科研",
        "source": _ACADEMIC,
        "url": f"{_ACADEMIC}/blob/main/scientific-toolkit-skill/references/scientific-skills/citation-management/SKILL.md",
        "stars": 5377,
        "description": "BibTeX 维护、去重与引用格式一致性。",
        "asset": {
            "name": "引用管理",
            "description": "BibTeX 维护与引用一致性",
            "content": "引用管理：每条文献必须有 DOI 或稳定 URL；正文引用与文献表双向核对；同一文献不同版本合并；提交前跑一次重复检测与格式校验。",
            "enabled": True,
        },
    },

    {
        "id": "skill-eda",
        "name": "探索性数据分析",
        "kind": "skills",
        "aliases": ["eda", "探索性", "数据分析"],
        "category": "科研",
        "source": _ACADEMIC,
        "url": f"{_ACADEMIC}/blob/main/scientific-toolkit-skill/references/scientific-skills/exploratory-data-analysis/SKILL.md",
        "stars": 5377,
        "description": "数据质量、分布、相关性与异常值的探索流程。",
        "asset": {
            "name": "探索性数据分析",
            "description": "EDA 标准流程",
            "content": "EDA：先看行列数与缺失率，再看单变量分布（直方图/箱线），然后双变量相关与分组比较，最后检查异常值与重复记录；每步记录发现与处理决定。",
            "enabled": True,
        },
    },

    {
        "id": "skill-matplotlib",
        "name": "科研绘图",
        "kind": "skills",
        "aliases": ["绘图", "matplotlib", "图表"],
        "category": "科研",
        "source": _ACADEMIC,
        "url": f"{_ACADEMIC}/blob/main/scientific-toolkit-skill/references/scientific-skills/matplotlib/SKILL.md",
        "stars": 5377,
        "description": "出版级图表：配色、坐标轴、误差线与可读性。",
        "asset": {
            "name": "科研绘图",
            "description": "出版级图表规范",
            "content": "科研绘图：一图只表达一个结论；坐标轴标注单位；误差线必须说明是标准差还是标准误；配色兼顾色盲；分辨率 ≥300dpi；图注自足（不看正文也能懂）。",
            "enabled": True,
        },
    },

    {
        "id": "skill-office-academic",
        "name": "学术 Office 输出",
        "kind": "skills",
        "aliases": ["学术ppt", "阅读报告", "office"],
        "category": "科研",
        "source": _ACADEMIC,
        "url": f"{_ACADEMIC}/blob/main/office-academic-skill/SKILL.md",
        "stars": 5377,
        "description": "论文阅读报告与学术 PPT 的生成规范。",
        "asset": {
            "name": "学术 Office 输出",
            "description": "阅读报告与学术 PPT",
            "content": "学术 PPT：每页一个论点，标题写结论而不是主题；图表占 60% 以上版面；参考文献放在末页；阅读报告用「问题-方法-结果-局限-启示」五段式。",
            "enabled": True,
        },
    },

    {
        "id": "skill-scientific-toolkit",
        "name": "科学计算工具箱",
        "kind": "skills",
        "aliases": ["科学计算", "scientific", "数值"],
        "category": "科研",
        "source": _ACADEMIC,
        "url": f"{_ACADEMIC}/blob/main/scientific-toolkit-skill/SKILL.md",
        "stars": 5377,
        "description": "数值计算、仿真与结果校验的通用做法。",
        "asset": {
            "name": "科学计算工具箱",
            "description": "数值计算与结果校验",
            "content": "科学计算：固定随机种子；报告软件与版本；对关键结果做量纲与边界检查；数值方法说明收敛准则；结果保留有效数字而不是盲目多位小数。",
            "enabled": True,
        },
    },
)
