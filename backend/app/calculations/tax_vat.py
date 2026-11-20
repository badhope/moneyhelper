"""增值税及附加：一般计税 13/9/6、简易 5/3/1，城建 7/5/1 + 教育 3 + 地方教育 2。"""

from __future__ import annotations

from typing import Any

from .tax_common import _round

VAT_GENERAL_RATES = (0.13, 0.09, 0.06, 0.0)

VAT_SIMPLE_RATES = (0.05, 0.03, 0.01)

SURCHARGE_RATES = {"city": 0.07, "county": 0.05, "other": 0.01}

EDU_SURCHARGE = 0.03

LOCAL_EDU_SURCHARGE = 0.02

def vat(
    *,
    sales: float,
    purchases: float = 0.0,
    rate: float = 0.13,
    simple: bool = False,
    simple_rate: float = 0.03,
    location: str = "city",
    exempt_threshold: float = 0.0,
) -> dict[str, Any]:
    """增值税及附加。

    一般计税：销项 = 销售额（不含税）× 税率；进项 = 采购额（不含税）× 税率；
    应纳 = 销项 - 进项（负数按 0 计，留抵下期，这里不虚拟抵扣）。
    简易计税：应纳 = 销售额（不含税）× 征收率，进项不得抵扣。

    exempt_threshold：小规模纳税人月销售额未超阈值免征（默认 0=不启用）。
    """
    if sales < 0 or purchases < 0:
        raise ValueError("销售额与采购额不能为负")
    if location not in SURCHARGE_RATES:
        raise ValueError(f"location 只能是 {'/'.join(SURCHARGE_RATES)}")

    if exempt_threshold and sales <= exempt_threshold:
        return {
            "method": "exempt",
            "output_vat": 0.0,
            "input_vat": 0.0,
            "vat_payable": 0.0,
            # 结构与计税分支保持一致：消费方（MCP / 报表导出 / 前端明细行）
            # 不必为"免征"单独写一条分支，少一处 KeyError 的来源。
            "surcharge_detail": {
                "city_construction": 0.0,
                "education": 0.0,
                "local_education": 0.0,
            },
            "surcharge": 0.0,
            "total": 0.0,
            "note": f"销售额 {sales:.2f} 未超过免征阈值 {exempt_threshold:.2f}",
        }

    if simple:
        if simple_rate not in VAT_SIMPLE_RATES:
            raise ValueError(f"简易计税征收率只能是 {VAT_SIMPLE_RATES}")
        output_vat = _round(sales * simple_rate, 2)
        input_vat = 0.0
        payable = output_vat
        method = f"simple@{simple_rate:.0%}"
    else:
        if rate not in VAT_GENERAL_RATES:
            raise ValueError(f"一般计税税率只能是 {VAT_GENERAL_RATES}")
        output_vat = _round(sales * rate, 2)
        input_vat = _round(purchases * rate, 2)
        payable = max(0.0, _round(output_vat - input_vat, 2))
        method = f"general@{rate:.0%}"

    city_rate = SURCHARGE_RATES[location]
    surcharge = _round(payable * (city_rate + EDU_SURCHARGE + LOCAL_EDU_SURCHARGE), 2)
    return {
        "method": method,
        "output_vat": output_vat,
        "input_vat": input_vat,
        "vat_payable": payable,
        "surcharge_detail": {
            "city_construction": _round(payable * city_rate, 2),
            "education": _round(payable * EDU_SURCHARGE, 2),
            "local_education": _round(payable * LOCAL_EDU_SURCHARGE, 2),
        },
        "surcharge": surcharge,
        "total": _round(payable + surcharge, 2),
        "note": "进项大于销项时留抵下期，本次按 0 申报"
        if (not simple and output_vat < input_vat)
        else "",
    }
