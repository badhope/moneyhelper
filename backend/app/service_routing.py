"""问题路由：词表、意图判定、NL 记账入口与 LLM 兜底分类。

从 service.py 拆出。词表与阈值随之搬走，service 通过底部导入继续使用同一份；
GENERAL_* 提示属于叙述路径，仍留在 service。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from . import db, llm, nlparse
from .logging_utils import get_logger

log = get_logger(__name__)

Emit = Callable[[dict[str, Any]], Awaitable[None]]

MARKET_WORDS = (
    "股票",
    "基金",
    "持仓",
    "仓位",
    "组合",
    "收益",
    "亏",
    "涨",
    "跌",
    "etf",
    "市值",
    "资产",
    "集中度",
    "配置",
    "自选",
    "加自选",
    "走势",
    "k线",
    "股价",
    "现价",
    "行情",
)
LEDGER_WORDS = (
    "花",
    "消费",
    "支出",
    # 「开销 / 开支 / 花费」是最常见的口语说法；此前只收「支出」，
    # 导致「这个月的开销怎么样」被判成普通闲聊、不查账本。
    "开销",
    "开支",
    "花费",
    "记账",
    "账",
    "预算",
    "订阅",
    "会员",
    "还款",
    "负债",
    "房贷",
    "信用卡",
    "现金流",
    "存",
    "省",
    "应急金",
    "储蓄",
    "收入",
    "余额",
    "工资",
)
# 目标/体检专用词：命中即按「市场+账本」全量财务路由（体检与目标进度需要完整数据）。
# 刻意不用「目标」「进度」这类宽泛词，避免「人生目标」这类非财务问法被误伤（宁缺毋滥）。
GOAL_WORDS = (
    "体检",
    "健康检查",
    "存够",
    "攒够",
    "首付",
    "买房",
    "买车",
    "还差多少",
    "建议月存",
    "攒钱",
    "存款目标",
    "攒首付",
)
# 企业域词：总账/采购应付/组织/长任务。这些问句通常不含个人理财词
# （「公司有哪些部门」没有「花/收入/持仓」），此前直接落 general 分支——那里只有
# web_search/get_now，模型看不到企业数据，只能凭常识硬答或说没有数据。
# 词选具体业务名词，避免「公司」这类泛词把「帮我写个公司简介」误判成查数据。
#
# 分强弱两档，是为了解决「总账」被 LEDGER_WORDS 的宽泛「账」字抢走：
# 强词（总账/凭证/供应商/部门…）只属于企业域，先行判定；
# 弱词（报销）与个人收支有交叉（「我这个月报销了多少」），放在账本之后再看。
ENTERPRISE_STRONG_WORDS = (
    "部门",
    "岗位",
    "组织架构",
    "长任务",
    "采购单",
    "采购",
    "供应商",
    "应付",
    "总账",
    "凭证",
    "科目",
    "试算",
)
ENTERPRISE_WEAK_WORDS = ("报销",)
# 只有「在问数据」才走企业域：纯写作/流程咨询（「帮我写个报销制度」「报销流程怎么走」）
# 仍归 general，宁可少管也不要答错方向。
DATA_QUESTION_MARKS = (
    "多少",
    "几",
    "哪些",
    "什么情况",
    "怎么样",
    "如何了",
    "概览",
    "汇总",
    "进度",
    "状态",
    "有没有",
    "列出",
    "查一下",
    "看看",
    "?",
    "？",
)
# 动作指令：命中即确定性执行工具（不依赖模型）。词选窄、选动作明确，避免误伤日常问法。
ACTION_WORDS = (
    "买入",
    "买进",
    "建仓",
    "加仓",
    "卖出",
    "卖掉",
    "清仓",
    "减仓",
    "抛售",
    "晨报",
    "备份",
    "默认首页",
    "涨跌颜色",
    "颜色主题",
    "换颜色",
    "切换语言",
)
# 记忆动词：短句 + 无问号 → 对话内「记住/记得 …」直接存长期记忆（规则级，无需模型）
MEMORY_VERBS = ("记住", "记得")

QUESTION_MARKS = ("吗", "呢", "怎", "哪", "多少", "是不是", "?", "？")
NL_MAX_LEN = 24


# 省略式追问：短句 + 指代词（「那上个月呢？」本身不含财务关键词，需承接上一轮）
FOLLOWUP_MARKS = ("那", "它", "这个", "上个月", "上月", "刚才", "刚刚", "其中", "前面")
FOLLOWUP_MAX_LEN = 12


def _has_finance_word(text: str) -> bool:
    q = text.lower()
    return any(w in q for w in MARKET_WORDS) or any(w in q for w in LEDGER_WORDS)


def _looks_like_enterprise_data_question(text: str, strong_only: bool = False) -> bool:
    """企业域名词 + 疑问/取数句式才判为查数据。

    单命中业务名词不成立：「帮我写个报销制度」含「报销」但不该去查库；
    「报销流程怎么走」是新用户咨询流程，也要留给通用分支。两者都带疑问词，
    所以再加一层「取数意图」——问数量/状态/清单/进度，或显式「看看/查一下」。

    strong_only=True 时只看强词（不含「报销」）。路由顺序依赖这一点：
    强词判定放在账本之前（否则「总账」会被 LEDGER_WORDS 的「账」抢走），
    弱词放在账本之后（否则「我这个月报销花了多少」会被误判成查企业数据）。
    """
    q = text.lower()
    words = ENTERPRISE_STRONG_WORDS if strong_only else (
        ENTERPRISE_STRONG_WORDS + ENTERPRISE_WEAK_WORDS
    )
    # 兜底组合：明确说「公司/组织/团队」+ 人数/编制类问法，也算企业域
    # （「公司一共有多少人」没有业务名词，只靠词表会漏）。
    # 必须同时有主体词，避免「我家一共有多少人」这类个人问题被抢走。
    org_subject = any(w in q for w in ("公司", "企业", "组织", "团队", "全公司"))
    headcount = any(w in q for w in ("多少人", "几个人", "人数", "编制", "人头"))
    if org_subject and headcount:
        return True
    if not any(w in q for w in words):
        return False
    return any(m in q for m in DATA_QUESTION_MARKS)


async def _is_finance_followup(question: str, thread_id: str | None) -> bool:
    """判断是否为承接上一轮财务提问的省略追问。

    四重约束同时成立才改判为财务路由：短句、含指代词、本会话上一轮是财务提问、已接入模型。
    未接入模型时不改判——确定性内核只算「本月」，让它回答「上个月」是误导。
    """
    q = question.strip()
    if not thread_id or len(q) > FOLLOWUP_MAX_LEN:
        return False
    if not any(m in q for m in FOLLOWUP_MARKS):
        return False
    if not await llm.llm_available():
        return False
    runs = await db.list_runs(thread_id, 1)
    if not runs:
        return False
    prev = runs[0]
    if _has_finance_word(str(prev.get("question") or "")):
        return True
    # 词表之外：上一轮本身就是财务路由（记账/动作/分析）也算承接上下文
    return str(prev.get("route") or "") in (
        "nl_add",
        "bookkeeping",
        "record",
        "action",
        "market",
        "ledger",
        "goal",
        "both",
    )


def _looks_like_record(question: str) -> bool:
    """短句 + 无疑问词 + 能解析出金额 → 视为一句话记账指令。"""
    q = question.strip()
    if not q or len(q) > NL_MAX_LEN:
        return False
    return not any(m in q for m in QUESTION_MARKS)


# 大额审批回执短语：仅「去空白/标点后精确命中词表」才算审批回复，防止普通短聊被误判。
# 词表保持显式（不含「好/是/对」等日常用语），降低 pending 上下文中的误触面。
_CONFIRM_REPLIES = {
    "确认",
    "确认入账",
    "确认记账",
    "确定",
    "记吧",
    "入账",
    "ok",
    "yes",
    "confirm",
}
_CANCEL_REPLIES = {
    "取消",
    "不记了",
    "不用了",
    "不记账",
    "算了",
    "no",
    "cancel",
}


def _confirm_decision(text: str) -> str | None:
    """把短回复归类为大额审批回执：「confirm」/「cancel」；不匹配返回 None。"""
    t = re.sub(r"[\s。.!！~～,，、;；]+", "", (text or "").strip().lower())
    if not t or len(t) > 8:
        return None
    if t in _CONFIRM_REPLIES:
        return "confirm"
    if t in _CANCEL_REPLIES:
        return "cancel"
    return None


def _nl_segments(question: str) -> list[dict[str, Any]]:
    """一句话记账的统一切段解析口径：按标点/连词切段、逐段解析。

    _try_nl_add 入账与「大额审批」门槛判定共用本函数，保证两者看到完全相同的分段，
    避免整句解析只取到第一段金额绕过审批（如「奶茶 20，房租 6000」）。
    """
    if not _looks_like_record(question):
        return []
    parts = [p.strip() for p in re.split(r"[，,。;；、和及]", question) if p.strip()]
    return [p for p in (nlparse.parse(part) for part in parts) if p is not None]


async def _try_nl_add(
    question: str, reason: str, emit: Emit, lang: str = "zh"
) -> dict[str, Any] | None:
    """对话内一句话记账：规则解析（无需模型）→ 入账 → 回执（含撤销路径）。

    支持一句多笔（用逗号/顿号/分号/和/及 分隔），逐段独立解析；全部可解析才入账（原子）。
    """
    parsed_all = _nl_segments(question)
    if not parsed_all:
        return None

    for parsed in parsed_all:
        await emit(
            {
                "type": "step",
                "id": "nl",
                "label": "识别记账" if lang == "zh" else "Recording",
                "detail": (
                    f"{parsed['item']} {abs(parsed['amount']):.2f} 元（{parsed['category']}）"
                    if lang == "zh"
                    else f"{parsed['item']} {abs(parsed['amount']):.2f} CNY ({parsed['category']})"
                ),
                "phase": "start",
            }
        )
    # 原子批量入账：任一条失败整体回滚（承诺"全部可解析才入账"的真实实现）
    inserted = await db.add_transactions_batch(
        [
            {
                "date": p["date"],
                "item": p["item"],
                "category": p["category"],
                "amount": p["amount"],
            }
            for p in parsed_all
        ]
    )
    # 对话路径写入后必须让仪表盘缓存失效：否则用户在同一页面问完"记一笔"
    # 切到总览仍看到旧流水（缓存 10 秒，但这 10 秒足够让人以为没记上）。
    from . import analysis as _analysis

    _analysis.invalidate_dashboard_cache()
    if lang == "zh":
        lines = [
            f"{p['date']} {p['item']} {abs(p['amount']):,.2f} 元"
            f"（{p['category']} · {'收入' if p['amount'] > 0 else '支出'}）"
            for p in parsed_all
        ]
        if len(lines) == 1:
            answer = (
                "已记一笔：" + lines[0] + "。\n\n记错了可以在「记账」页删掉这一条。"
            )
        else:
            answer = (
                "已记 "
                + str(len(lines))
                + " 笔：\n"
                + "\n".join("· " + line for line in lines)
                + "\n\n记错了可以在「记账」页删掉。"
            )
    else:
        lines = [
            f"{p['date']} {p['item']} {abs(p['amount']):,.2f} CNY"
            f" ({p['category']} · {'income' if p['amount'] > 0 else 'expense'})"
            for p in parsed_all
        ]
        if len(lines) == 1:
            answer = (
                "Recorded: "
                + lines[0]
                + ".\n\nMade a mistake? Delete it on the Ledger page."
            )
        else:
            answer = (
                "Recorded "
                + str(len(lines))
                + " entries:\n"
                + "\n".join("· " + line for line in lines)
                + "\n\nDelete on the Ledger page if wrong."
            )
    for p in parsed_all:
        await emit(
            {
                "type": "step",
                "id": "nl",
                "label": "已入账",
                "detail": f"{p['category']} {abs(p['amount']):,.2f} 元",
                "phase": "done",
            }
        )
    return {
        "answer": answer,
        "level": "已记账",
        "route": "nl_add",
        "route_reason": (
            f"识别为一句话记账：{reason}"
            if lang == "zh"
            else f"Recognized as one-sentence bookkeeping: {reason}"
        ),
        "metrics": {},
        "flags": [],
        "llm": "template",
        "tx_id": inserted[0]["id"],
    }


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


def _looks_like_memory(question: str) -> bool:
    """短句 + 记忆动词 + 无疑问词 → 视为「记住/记得 …」记忆指令。

    与一句话记账同一套保守判定：疑问句（「你还记得吗」）绝不当记忆指令。
    """
    q = question.strip()
    if not q or len(q) > NL_MAX_LEN:
        return False
    if any(m in q for m in QUESTION_MARKS):
        return False
    return any(v in q for v in MEMORY_VERBS)


def _looks_like_watchlist(question: str) -> bool:
    """含「自选」字样（加自选 / 移除自选 / 看自选）→ 归持仓-行情域，绝不进记账解析。

    「把 600519 加入自选」里的 6 位代码会被 nlparse 当成金额（实测 600519 → 走 60 万大额审批），
    必须在记账检测之前拦截。
    """
    return "自选" in question


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


async def _try_save_memory(
    question: str, emit: Emit, lang: str = "zh"
) -> dict[str, Any] | None:
    """对话内记忆指令：规则提取内容 → 存长期记忆 → 回执（无需模型）。

    提取「记住/记得」之后的内容；提取不到有效内容（如单独一个「记住」）返回 None。
    技能「长期记忆」在设置中关闭时：不写入，并明确回执（不静默、不冒充已记住）。
    """
    if not _looks_like_memory(question):
        return None
    from . import agent_config

    if not await agent_config.is_skill_enabled("long_memory"):
        return {
            "answer": (
                "长期记忆已在「设置 → Agent 与技能」中关闭，这条我没有记。"
                "需要我记住的话，打开开关后再告诉我一次。"
                if lang == "zh"
                else "Long-term memory is turned off in Settings → Agents & skills, so I didn't save this. "
                "Turn it on and tell me again if you want me to remember it."
            ),
            "level": "",
            "route": "memory",
            "route_reason": (
                "识别为记忆指令，但「长期记忆」技能已关闭"
                if lang == "zh"
                else "Memory instruction, but the long-term memory skill is disabled"
            ),
            "metrics": {},
            "flags": [],
            "llm": "template",
            "memory_deduped": False,
        }
    content = re.sub(
        rf"^(?:帮我|请|麻烦|要|我想)*?(?:{'|'.join(MEMORY_VERBS)})[:：]?",
        "",
        question.strip(),
    ).strip("，。！、 ")
    if len(content) < 2:
        return None

    out = await db.add_memory(content)
    await emit(
        {
            "type": "step",
            "id": "memory",
            "label": "已记住" if lang == "zh" else "Remembered",
            "detail": content[:30] + ("…" if len(content) > 30 else ""),
            "phase": "done",
        }
    )
    if lang == "zh":
        answer = (
            f"好，我记住了：{content}。\n\n"
            "以后涉及相关问题时我会参考它；可在「设置 → 长期记忆」查看或删除。"
        )
        route_reason = "识别为「记住/记得 …」记忆指令，直接存长期记忆"
    else:
        answer = (
            f"Got it — I've remembered: {content}.\n\n"
            "I'll reference it for related questions; view or delete it in Settings → Long-term memory."
        )
        route_reason = (
            "Recognized as a memory instruction — saved directly to long-term memory"
        )
    return {
        "answer": answer,
        "level": "已记住",
        "route": "memory",
        "route_reason": route_reason,
        "metrics": {},
        "flags": [],
        "llm": "template",
        "memory_deduped": out.get("deduped", False),
    }
