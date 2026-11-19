"""从「试算平衡表」还原三表 —— 让用户不必手填 JSON。

## 为什么要这个

财报页原本要求用户粘一段标准化三表 JSON（`statements_analyze` 的入参）。对企业
财务人员这是可接受的输入方式；但本产品的定位是「零门槛、全托管的财务部门」——
用户已经在总账里记了账（报销、采购、银行流水都会自动生成凭证），再让他手抄一份
资产负债表是没有道理的，而且抄错一个字段，勾稽检查就会报一堆假警报。

这里只做**报表口径还原**：把已过账凭证按科目类型汇总成三表字段，再交回
`analyze_statements` 做指标与预警。不审计、不调整、不编造。

## 口径约定（重要）

1. 借贷方向：资产、费用为借方正常；负债、权益、收入为贷方正常。
   试算表的 `balance` 是「借 − 贷」，所以负债/权益/收入取负号才是余额。
2. 所有者权益按**结转后口径**：`equity_balance + 当期净利润`。
   期末损益还没结转到本年利润时，资产 = 负债 + 权益 + 当期损益；
   若不把损益并入权益，等式永远差一个净利润，勾稽检查会一直报错。
   报表上因此不会出现"凭空多出来的权益"——注释里写清楚来源即可。
3. 现金流量表**不由余额表推导**：余额表没有期间发生额的方向信息，
   硬凑一个现金流会让「现金流质量」指标变成假数字。缺就缺，分析引擎会标注「—」。
"""

from __future__ import annotations

from typing import Any

CASH_NAMES = ("货币资金", "现金", "银行存款")
AR_NAMES = ("应收账款", "应收票据")
INVENTORY_NAMES = ("存货", "库存商品", "原材料")
GOODWILL_NAMES = ("商誉",)
INTEREST_NAMES = ("利息", "财务费用")


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _match(name: str, keywords: tuple[str, ...]) -> bool:
    return any(k in name for k in keywords)


def _is_current(code: str, *, limit: int) -> bool:
    """按科目代码前两位判流动/非流动：1xxx 里 14 以内为流动，2xxx 里 24 以内为流动。

    这是中国会计准则的常见分段（1501 起为长期资产、2501 起为长期负债）。
    科目表是用户可改的，所以这里只做**默认分段**，判断不出来就按流动处理，
    宁可高估流动比率也不要把流动资产漏成 0。
    """
    head = code[:2]
    if not head.isdigit():
        return True
    return int(head) <= limit


def statements_from_trial_balance(
    items: list[dict[str, Any]],
    *,
    company: str = "本企业",
    currency: str = "CNY",
    period: str = "",
) -> dict[str, Any]:
    """把试算平衡表 items 还原成一期三表 JSON（结构与 statements_analyze 入参一致）。"""
    asset = liability = equity = income = expense = 0.0
    current_assets = current_liabilities = 0.0
    cash = ar = inventory = goodwill = 0.0
    interest = 0.0
    revenue = cost_of_sales = 0.0

    for it in items:
        raw_code = str(it.get("code") or "")
        code = raw_code.zfill(4) if raw_code.isdigit() else raw_code
        name = str(it.get("name") or "")
        kind = str(it.get("type") or "")
        balance = _f(it.get("balance"))
        if not kind:
            continue

        if kind == "asset":
            asset += balance
            if _is_current(code, limit=14):
                current_assets += balance
            if _match(name, CASH_NAMES):
                cash += balance
            if _match(name, AR_NAMES):
                ar += balance
            if _match(name, INVENTORY_NAMES):
                inventory += balance
            if _match(name, GOODWILL_NAMES):
                goodwill += balance
        elif kind == "liability":
            liability += -balance
            if _is_current(code, limit=24):
                current_liabilities += -balance
        elif kind == "equity":
            equity += -balance
        elif kind == "income":
            income += -balance
            if code.startswith("60"):
                revenue += -balance
        elif kind == "expense":
            expense += balance
            if code.startswith("64"):
                cost_of_sales += balance
            if _match(name, INTEREST_NAMES):
                interest += balance

    gross_profit = revenue - cost_of_sales
    net_profit = income - expense

    def r(x: float) -> float:
        return round(x, 2)

    return {
        "company": company,
        "currency": currency,
        "periods": [
            {
                "period": period,
                "balance_sheet": {
                    "total_assets": r(asset),
                    "total_liabilities": r(liability),
                    # 见模块注释第 2 条：结转后口径
                    "total_equity": r(equity + net_profit),
                    "current_assets": r(current_assets),
                    "current_liabilities": r(current_liabilities),
                    "cash_and_equivalents": r(cash),
                    "inventory": r(inventory),
                    "accounts_receivable": r(ar),
                    "goodwill": r(goodwill),
                },
                "income_statement": {
                    "revenue": r(revenue),
                    "gross_profit": r(gross_profit),
                    "operating_profit": r(net_profit),
                    "net_profit": r(net_profit),
                    "ebit": r(net_profit + interest),
                    "interest_expense": r(interest),
                },
                # 余额表推不出期间现金流，留空由分析引擎标注「—」
            }
        ],
    }
