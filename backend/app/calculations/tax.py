"""中国大陆税负与薪酬核算引擎门面（确定性，纯函数）。

覆盖四类真实场景，参数全部显式传入，不猜政策：

1. **增值税及附加**：见 `tax_vat.py`（一般 13/9/6、简易 5/3/1，附加按实缴增值税计）。
2. **企业所得税**：见 `tax_cit.py`（25%/15%高新/20%小微减半/5%，支持亏损结转）。
3. **个人所得税**：见 `tax_iit.py`（7 级超额累进 + 5000 起征 + 专项附加扣除）。
4. **工资核算**：见 `tax_payroll.py`（五险一金两侧 + 基数钳制 + 企业总成本）。

报表口径（月末结账清单、税负汇总）在 `tax_reports.py`，共用数值口径在 `tax_common.py`。

边界与免责：
- 社保比例按「通用城镇职工」口径给默认值，各地差异极大，因此**所有比例都作为参数**；
- 税收优惠需用户确认自身资质，本模块只做算术，不做资格判定；
- 输出带 `disclaimer`，不构成正式税务意见。
"""

from __future__ import annotations

from .tax_cit import corporate_income_tax  # noqa: F401,E402
from .tax_iit import individual_income_tax  # noqa: F401,E402
from .tax_payroll import PayrollResult, payroll  # noqa: F401,E402
from .tax_reports import month_end_checklist, tax_summary  # noqa: F401,E402
from .tax_vat import vat  # noqa: F401,E402
