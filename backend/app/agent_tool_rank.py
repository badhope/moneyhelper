"""按问题相关度裁剪工具表（纯函数，无 IO）。

为什么需要：小模型端到端跑不动全量工具面。实测 MiniCPM5-2B 在 40 个工具的
schema（约 7.4k token）下**一个工具都不调**，直接凭上下文编答案；把工具压到
6 个后立刻正确调用。这不是"模型不会用工具"，而是工具太多导致选择困难 +
prompt 过长（prefill 3 分钟）。

因此提供 `LLM_TOOL_LIMIT` 开关：默认 0（不裁剪，行为完全不变），设置后按问题
相关度保留前 N 个。打分只看"问题与工具名/描述的字面重叠"，不引入向量模型——
工具只有几十个，字面重叠已经够用，且结果可解释、可测试。

重叠按 IDF 加权而不是简单计数：40 个工具描述里"适合回答""查询""用户"这类词
几乎每个都出现，简单计数会变成"谁描述长谁占便宜"，真正有区分度的"持仓"
"供应商""报销"反被稀释。IDF 让常见词自动降权、稀有词主导排序。

但字面重叠只对"用户照抄工具描述"的情况有效。真实问句大量走口语转述——"你还
记得我家里什么情况吗"里没有"记忆""家庭"任何一个原词，切出来的二字碎片全落在
"记得/什么/情况"这种无区分度成分上，纯重叠必然失灵。所以再叠一层人工维护的
口语别名表：一个工具三五个别名，命中即加分（长别名权重更高，避免"钱"这种单字
把预算、账本、流水全部拉平）。别名表只增不改，靠回归测试守着。
"""

from __future__ import annotations

import math
import re
from typing import Any

_PUNCT = re.compile(r"[^\w\u4e00-\u9fff]+")

# 口语别名 → 工具。只收"描述里没有、但用户真会这么说"的词。
ALIASES: dict[str, tuple[str, ...]] = {
    "get_market_view": ("持仓", "仓位", "套牢", "赚了", "亏了", "市值", "身家"),
    "get_ledger_view": ("花了", "开销", "流水", "账本", "生活费", "月光", "结余"),
    "get_risk_flags": ("风险", "踩雷", "暴雷", "隐患"),
    "get_budget": ("预算", "超支", "还能花", "额度"),
    "get_trend": ("越来越多", "越花越", "趋势", "对比上月", "环比"),
    "get_kline": ("走势", "K线", "曲线上"),
    "get_goals": ("目标", "存够", "还差多少", "攒钱"),
    "get_user_memory": ("记得", "记忆", "家里", "家庭", "背景", "我以前说"),
    "get_lessons": ("踩坑", "教训", "经验库"),
    "get_health_check": ("体检", "健康状况", "全面看看"),
    "search_symbol": ("代码", "叫什么", "哪只"),
    "get_quote": ("多少钱一股", "现价", "股价", "涨了吗", "price", "报价", "行情怎样"),
    "get_watchlist": ("自选", "关注的票"),
    "get_portfolio_risk": ("波动", "回撤", "夏普", "跑赢大盘"),
    "get_rebalance_plan": ("调仓", "再平衡", "加减仓"),
    "get_valuation": ("贵不贵", "高位", "分位", "低估"),
    "get_dca_plans": ("定投", "扣款", "成本线"),
    "get_fire_plan": ("财务自由", "FIRE", "躺平"),
    "research_analyze": ("技术面", "指标", "均线", "金叉"),
    "research_backtest": ("回测", "双均线", "策略表现"),
    "statements_analyze": ("财报", "三表", "杜邦"),
    "research_forecast": ("预测", "未来走势", "价格区间"),
    "paper_overview": ("模拟盘", "战队", "排行"),
    "connect_catalog": ("连", "接入", "数据源", "支付宝"),
    "connect_fund_nav": ("净值", "场外基金"),
    "tax_calc": ("交税", "个税", "税后", "五险一金"),
    "debt_payoff_plan": ("先还", "还清", "还款", "利息"),
    "cashflow_forecast": ("不够花", "现金流", "撑到"),
    "scan_subscriptions": ("订阅", "会员", "自动续费", "涨价"),
    "scan_anomalies": ("异常", "大额", "不对劲"),
    "pretrade_check": ("能不能买", "下单", "委托"),
    "market_breadth": ("大盘", "涨跌家数", "情绪", "温度"),
    "stock_profile": ("市盈率", "估值多少", "换手"),
    "broker_status": ("自动下单", "券商", "QMT"),
    "invoice_vision_status": ("发票", "OCR", "识别"),
    "get_gl_summary": ("总账", "账平", "试算"),
    "get_payables_summary": ("供应商", "应付", "欠款"),
    "get_expense_queue": ("报销", "审批"),
    "get_org_overview": ("部门", "组织架构", "多少人"),
    "list_longtasks": ("长任务", "跑到哪", "进度"),
}


# 问句里的泛词：几乎每个问题都带，命中哪条描述纯属巧合。留着会盖过真信号
# （"这个月我花了多少钱"里"这个/个月/多少"能把 tax_calc 顶到第一）。
_NOISE = {
    "这个", "个月", "多少", "少钱", "什么", "么情", "情况", "怎么", "么样", "怎样",
    "现在", "今天", "最近", "主要", "哪些", "哪里", "还有", "是否", "几个", "一下",
    "能否", "可以", "需要", "应该", "我的", "我在", "我是", "我这", "帮我", "你帮",
    "看看", "有没有", "是不", "不是", "一个", "一笔", "这笔", "那只", "这只", "那个",
    "请问", "告诉", "知道", "觉得",
}


def _alias_score(question: str, name: str) -> float:
    """别名命中累加；别名越长权重越高（避免单字词把所有工具拉平）。"""
    q = question.lower()
    return sum(len(a) * 2.0 for a in ALIASES.get(name, ()) if a.lower() in q)



def _bigrams(text: str) -> set[str]:
    """中文按二字切片，英文按整词；都做小写归一。"""
    clean = _PUNCT.sub(" ", text.lower())
    grams: set[str] = set()
    for chunk in clean.split():
        if chunk.isascii():
            if len(chunk) >= 2:
                grams.add(chunk)
            continue
        for i in range(len(chunk) - 1):
            grams.add(chunk[i : i + 2])
    return grams


def _tool_text(schema: dict[str, Any]) -> str:
    fn = schema.get("function") or {}
    return f"{fn.get('name') or ''} {fn.get('description') or ''}"


def rank_tools(
    question: str, schemas: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """按与问题的字面相关度排序，返回前 limit 个（limit<=0 时原样返回）。

    显式点名的工具（问题里出现工具名）一律优先，避免"用户说了工具名却被裁掉"。
    同分保持原有顺序，保证结果稳定、可断言。
    """
    if limit <= 0 or len(schemas) <= limit:
        return list(schemas)

    docs = [_bigrams(_tool_text(s)) for s in schemas]
    n = len(docs)
    df: dict[str, int] = {}
    for grams in docs:
        for g in grams:
            df[g] = df.get(g, 0) + 1
    # 平滑 IDF：几乎每个工具都有的词权重趋近 1，只在少数工具出现的词权重高
    idf = {g: math.log((n + 1) / (c + 1)) + 1.0 for g, c in df.items()}

    q_grams = _bigrams(question) - _NOISE
    scored: list[tuple[int, float, int, dict[str, Any]]] = []
    for idx, (schema, grams) in enumerate(zip(schemas, docs, strict=True)):
        name = str((schema.get("function") or {}).get("name") or "")
        explicit = bool(name) and name.lower() in question.lower()
        score = sum(idf.get(g, 0.0) for g in q_grams & grams) + _alias_score(question, name)
        scored.append((0 if explicit else 1, -score, idx, schema))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [item[3] for item in scored[:limit]]
