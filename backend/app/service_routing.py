"""问题路由门面：词表、意图判定、NL 记账/记忆在子模块，本文件保留规则路由与 LLM 兜底。

service.py 与测试仍从本模块取全部同名符号。
"""

from __future__ import annotations

from typing import Any  # noqa: F401

from . import llm
from .routing_intent import (  # noqa: F401,E402
    _confirm_decision,
    _has_finance_word,
    _is_finance_followup,
    _looks_like_enterprise_data_question,
    _looks_like_memory,
    _looks_like_record,
    _looks_like_watchlist,
)
from .routing_nl import (  # noqa: F401,E402
    _nl_segments,
    _try_nl_add,
    _try_save_memory,
)
from .routing_vocab import (  # noqa: F401,E402
    _CANCEL_REPLIES,
    _CONFIRM_REPLIES,
    ACTION_WORDS,
    DATA_QUESTION_MARKS,
    ENTERPRISE_STRONG_WORDS,
    ENTERPRISE_WEAK_WORDS,
    FOLLOWUP_MARKS,
    FOLLOWUP_MAX_LEN,
    GOAL_WORDS,
    LEDGER_WORDS,
    MARKET_WORDS,
    MEMORY_VERBS,
    NL_MAX_LEN,
    QUESTION_MARKS,
)


def route_question(question: str, lang: str = "zh") -> tuple[str, str]:
    """规则分类（不调模型）：命中目标/体检词 → goal（全量财务路由），命中投资词 → market，
    命中收支词 → ledger，都命中 → both，都不命中 → general。

    宁缺毋滥：不确定是否问财务时一律 general，绝不做「猜测式财务综合分析」。
    reason 为推理轨迹展示文本（route_reason），前端「Moneyhelper 的理解」直接亮给用户看，
    因此用用户能听懂的理财心智语言，而非「命中关键词」的技术说明（差异化「懂钱」）。
    按 lang 本地化。
    """
    en = lang != "zh"
    q = question.lower()
    hit_a = [w for w in ACTION_WORDS if w in q]
    if hit_a:
        if en:
            return "action", "A quick action you asked for — I'll run it directly"
        return "action", f"你想让我直接做的操作（{hit_a[0]}）"
    hit_g = [w for w in GOAL_WORDS if w in q]
    if hit_g:
        if en:
            return (
                "goal",
                "You want a financial health check or to see how a goal is tracking",
            )
        return "goal", f"你想看看财务体检 / 目标进度（{hit_g[0]}）"
    hit_m = [w for w in MARKET_WORDS if w in q]
    hit_l = [w for w in LEDGER_WORDS if w in q]
    # 企业强词先于个人账本/持仓：「我的总账怎么样」含「账」（LEDGER_WORDS），
    # 若按后者判定会走个人账本、答成「本月支出多少」，与用户问的公司总账无关。
    if _looks_like_enterprise_data_question(q, strong_only=True):
        if en:
            return (
                "enterprise",
                "You're asking about the company books, procurement or the org",
            )
        return "enterprise", "你想查公司的账务 / 采购应付 / 组织数据"
    if hit_m and hit_l:
        if en:
            return (
                "both",
                "You want both your holdings and your money flows in one picture",
            )
        return "both", f"你想同时看持仓和收支（{hit_m[0]} / {hit_l[0]}）"
    if hit_m:
        if en:
            return (
                "market",
                "You want the current state of your holdings and market quotes",
            )
        return "market", f"你想看持仓盈亏和行情（{hit_m[0]}）"
    if hit_l:
        if en:
            return "ledger", "You want to see income, spending and debt"
        return "ledger", f"你想看这个月的收支和负债（{hit_l[0]}）"
    # 企业弱词（报销）：个人理财词全都不命中时才考虑，
    # 避免「我这个月报销花了多少」被抢走（它确实该走账本）。
    if not (hit_m or hit_l) and _looks_like_enterprise_data_question(q):
        if en:
            return (
                "enterprise",
                "You're asking about company books, procurement, expenses or the org",
            )
        return "enterprise", "你想查公司的账务 / 采购应付 / 报销 / 组织数据"
    if en:
        return "general", "Not a finance question — answering in general"
    return "general", "这句不是理财问题，按通用问答回复"


_FINANCE_HINTS = (
    "钱", "账", "预算", "支出", "收入", "负债", "持仓", "股票", "基金", "行情", "理财",
    "税", "报销", "发票", "工资", "消费", "房贷", "信用卡", "订阅", "现金流", "报表",
    "资产", "投资", "分红", "利息", "还款", "存款", "余额", "花费", "开销",
)

_NON_FINANCE_HINTS = (
    "你好", "您好", "谢谢", "你是谁", "你能做什么", "你能帮我做什么", "介绍一下你",
    "自我介绍", "怎么用", "帮我写", "写一段", "写个", "翻译", "润色", "改写",
    "代码", "报错", "python", "sql", "作文", "文案", "笑话", "天气", "几点",
    # 时事/资讯类：不应被模型误判成持仓行情（实测「人工智能 今日新闻」被答成
    # 「你想看持仓盈亏和行情（股价）」并追加投资免责声明）。含财务词的新闻
    # （如「股票新闻」）仍被上面的 _FINANCE_HINTS 拦下，继续走财务分支。
    "新闻", "资讯", "最新消息", "新消息", "今日要闻", "今日热点", "发生了什么", "头条",
)


def looks_like_non_finance(question: str) -> bool:
    """明显的闲聊/写作/编程：不需要模型再判一次「这是不是理财问题」。

    判定必须“双确认”：命中非理财特征，且完全不含财务词。宁可漏判走模型兜底，
    也不能把「写一份预算方案」这类财务写作误判成闲聊。
    """
    q = question.replace("［联网搜索］", "").strip().lower()
    if not q or len(q) > 60:
        return False
    if any(h in q for h in _FINANCE_HINTS):
        return False
    return any(h in q for h in _NON_FINANCE_HINTS)


async def classify_question_llm(question: str, lang: str = "zh") -> str | None:
    """规则未命中时的模型兜底分类：market / ledger / both / goal / enterprise / general。

    只管「是否理财问题及其域」，宁缺毋滥；模型不可用 / 输出非法一律返回 None（调用方保持 general）。
    """
    system = (
        '你是意图分类器。只输出 JSON：{"route": "market|ledger|both|goal|enterprise|general"}。'
        "market=股票/基金/持仓/行情/走势/某个标的价格；ledger=收支/记账/预算/负债；"
        "both=同时涉及持仓与收支；goal=财务体检/储蓄目标进度；"
        "enterprise=公司总账/凭证/科目/采购/供应商/应付/报销审批/部门岗位/长任务等企业数据查询；"
        "general=其它（写作/闲聊/编程等，含制度编写、流程咨询这类不查数据的问法）。"
    )
    out = await llm.json_complete(system, question, timeout=12.0)
    if not isinstance(out, dict):
        return None
    route = str(out.get("route") or "").strip().lower()
    return route if route in (
        "market", "ledger", "both", "goal", "enterprise", "general"
    ) else None
