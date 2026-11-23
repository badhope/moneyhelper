"""任务模板：把“用户想要的东西”翻译成可执行阶段与交付契约。

阶段契约只写最低标准，不写“作文要求”：最少字数、必须出现的小节、
是否允许占位符、是否允许调用只读工具。执行器用同一份契约校验产物。
"""

from __future__ import annotations

from typing import Any

from .logging_utils import get_logger

log = get_logger(__name__)


def _c(
    *,
    min_chars: int = 0,
    max_chars: int = 12000,
    sections: list[str] | None = None,
    no_placeholder: bool = False,
    tools: bool = False,
    route: str = "",
) -> dict[str, Any]:
    return {
        "min_chars": min_chars,
        "max_chars": max_chars,
        "required_sections": sections or [],
        "forbid_placeholders": no_placeholder,
        "use_tools": tools,
        "route": route,
    }


TEMPLATES: dict[str, dict[str, Any]] = {
    "novel": {
        "label": "长篇小说",
        "stages": [
            (
                "世界观与人物",
                "写出故事的世界观设定、主要人物小传（每人 150 字内）、核心冲突。",
                _c(min_chars=300, max_chars=5000, sections=["世界观", "人物", "核心冲突"], no_placeholder=True),
            ),
            (
                "分卷大纲",
                "把故事拆成 5 卷，每卷写清开端、转折、高潮、结尾与字数配比。",
                _c(min_chars=500, max_chars=8000, no_placeholder=True),
            ),
            ("第一章", "按大纲写第一章正文，2500 字以上，有场景、对话与钩子。", _c(min_chars=1500, no_placeholder=True)),
            ("第二章", "承接第一章写第二章正文，2500 字以上，推进主线冲突。", _c(min_chars=1500, no_placeholder=True)),
            ("第三章", "写第三章正文，2500 字以上，制造一次反转。", _c(min_chars=1500, no_placeholder=True)),
            (
                "连续性检查",
                "检查前三章的人物、时间线、设定一致性，列出冲突并给出修订建议。",
                _c(min_chars=300, sections=["冲突", "修订"], no_placeholder=True),
            ),
        ],
    },
    "webapp": {
        "label": "网页程序",
        "stages": [
            (
                "需求与信息架构",
                "写清目标用户、核心任务、页面清单与导航结构。",
                _c(min_chars=250, sections=["目标用户", "核心任务", "页面清单"], no_placeholder=True),
            ),
            (
                "数据模型与接口",
                "定义数据表/字段、API 契约（方法、路径、请求、响应、错误码）。",
                _c(min_chars=400, sections=["API", "错误码"], no_placeholder=True),
            ),
            ("页面骨架", "给出每个页面的 HTML 结构与关键组件拆分（可直接落地）。", _c(min_chars=250, no_placeholder=True)),
            ("核心逻辑", "实现核心业务逻辑代码（含输入校验、错误处理），说明运行方式。", _c(min_chars=400, no_placeholder=True)),
            ("样式与响应式", "给出 CSS（含移动端断点）与可访问性要点。", _c(min_chars=250)),
            ("自测清单", "列出可执行的验收步骤与边界用例，标注未实现项。", _c(min_chars=250, sections=["验收", "边界"])),
        ],
    },
    "docx": {
        "label": "Word 文档",
        "stages": [
            ("文档大纲", "给出标题、章节层级、每节要点与目标读者。", _c(min_chars=200, sections=["章节", "要点"])),
            ("正文初稿", "按大纲写完整正文，段落清晰，术语一致。", _c(min_chars=600, no_placeholder=True)),
            ("表格与附件", "设计需要插入的表格（列名、示例行）与附录清单。", _c(min_chars=200)),
            ("修订说明", "列出需要人工确认的事实、数据与引用。", _c(min_chars=200)),
        ],
    },
    "paper": {
        "label": "学术论文",
        "stages": [
            ("研究问题与贡献", "界定研究问题、研究缺口、本文贡献（不超过 3 条）。", _c(min_chars=300, sections=["研究问题", "贡献"])),
            ("文献综述", "按主题组织相关研究，指出分歧与缺口；不得编造文献。", _c(min_chars=400, no_placeholder=True)),
            ("研究方法", "写清样本、变量、模型/实验设计、可复现步骤。", _c(min_chars=300, sections=["样本", "变量", "步骤"])),
            ("结果", "给出结果呈现结构（表格/图）与解读要点；无数据时明确标注为待填。", _c(min_chars=250)),
            ("讨论与结论", "讨论结果含义、局限与未来研究方向。", _c(min_chars=300)),
            ("摘要与投稿检查", "写 250 字摘要与关键词，并给出格式/引用自查清单。", _c(min_chars=250, sections=["摘要", "关键词"])),
        ],
    },
    "program": {
        "label": "程序开发",
        "stages": [
            (
                "需求与边界",
                "写清功能、非功能需求、不做什么、验收标准。",
                _c(min_chars=200, sections=["功能需求", "非功能需求", "验收标准"], no_placeholder=True),
            ),
            ("设计与接口", "模块划分、关键数据结构、对外接口与错误语义。", _c(min_chars=300, sections=["模块", "接口", "错误"])),
            ("核心实现", "写出可运行的核心代码，含输入校验与错误处理。", _c(min_chars=400, no_placeholder=True)),
            ("测试", "给出单元测试与边界用例，说明如何运行。", _c(min_chars=250, no_placeholder=True)),
            ("交付说明", "写 README：安装、运行、配置、已知限制。", _c(min_chars=250, sections=["安装", "运行", "限制"])),
        ],
    },
    "research": {
        "label": "投研报告",
        "stages": [
            (
                "数据与口径",
                "先调用只读财务工具取账本、净资产、月度收支或财务画像；写清数据来源、时间口径与缺失项。",
                _c(min_chars=250, sections=["数据", "口径"], tools=True, route="ledger"),
            ),
            (
                "市场与持仓",
                "调用只读行情工具取持仓、行情或估值；把关键数字、计算口径与风险暴露写清楚。",
                _c(min_chars=300, sections=["持仓", "风险"], tools=True, route="market"),
            ),
            (
                "结论与风险",
                "给出结论、依据、风险与不确定性、后续观察点；每条结论都要能对应前两阶段的数据。",
                _c(min_chars=350, sections=["结论", "依据", "风险", "后续观察"], no_placeholder=True),
            ),
            ("执行清单", "把结论拆成可执行动作：何时做、触发条件与退出条件。", _c(min_chars=200, sections=["动作", "触发", "退出"])),
        ],
    },
}


def list_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": key,
            "label": value["label"],
            "stages": [s[0] for s in value["stages"]],
            "contracts": [dict(s[2]) if len(s) > 2 else {} for s in value["stages"]],
        }
        for key, value in TEMPLATES.items()
    ]
