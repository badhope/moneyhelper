"""默认账套：一套够用的最小科目表。

定位是"全托管财务"，所以不给用户一张空的科目表让他自己填。这里收录小企业会计准则里
最常用的一层科目（家庭场景同样能用：银行存款/日常支出/工资收入都能落到科目上），
首次建账时一次性铺好，之后缺什么再按需补。

编号规则保持不变（4 位码），便于与外部账套、税务报表对接；不要为"家庭版"另起一套编号，
否则两套账无法合并，反而增加长期成本。
"""

from __future__ import annotations

# (code, name, type)
# type 与 gl_accounts.type 一致：asset / liability / equity / income / expense
DEFAULT_CHART: tuple[tuple[str, str, str], ...] = (
    # 资产
    ("1001", "银行存款", "asset"),
    ("1002", "库存现金", "asset"),
    ("1122", "应收账款", "asset"),
    ("1405", "库存商品", "asset"),
    ("1601", "固定资产", "asset"),
    # 负债
    ("2202", "应付账款", "liability"),
    ("2203", "应交税费", "liability"),
    ("2211", "应付职工薪酬", "liability"),
    ("2501", "长期借款", "liability"),
    # 权益
    ("3001", "实收资本", "equity"),
    ("3103", "本年利润", "equity"),
    ("3104", "利润分配", "equity"),
    # 收入
    ("6001", "主营业务收入", "income"),
    ("6051", "其他业务收入", "income"),
    # 费用
    ("6401", "主营业务成本", "expense"),
    ("6601", "销售费用", "expense"),
    ("6602", "管理费用", "expense"),
    ("6603", "财务费用", "expense"),
)

# 银行流水 → 对方科目。流水只有摘要和对方户名，没有科目，所以用关键词规则兜底；
# 命中不了就用默认科目（支出记管理费用、收入记其他业务收入），宁可粗也不能不入账。
_OUT_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("房租", "租金", "物业", "水费", "电费", "燃气", "取暖"), "6602"),
    (("工资", "薪", "社保", "公积金", "劳务"), "6602"),
    (("利息", "手续费", "服务费", "年费"), "6603"),
    (("采购", "进货", "材料", "货款"), "6401"),
)
_IN_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("工资", "薪", "报酬"), "6001"),
    (("退款", "返还", "返利"), "6051"),
)


def pick_account_code(direction: str, memo: str = "", counterparty: str = "") -> str:
    """按方向与文本挑对方科目编码。命中不了返回默认科目。"""
    text = f"{memo} {counterparty}"
    rules = _OUT_RULES if direction == "out" else _IN_RULES
    for words, code in rules:
        if any(w in text for w in words):
            return code
    return "6602" if direction == "out" else "6051"
