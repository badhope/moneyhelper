"""企业域：总账/采购应付/报销/长任务（含 MCP 专用的创建类入参）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .schemas_base import _In


class GetGlSummaryIn(_In):
    """查企业总账概览：无参数。"""

class GetPayablesSummaryIn(_In):
    """查采购应付概览：无参数。"""

class GetExpenseQueueIn(_In):
    """查报销队列：无参数。"""

class GetOrgOverviewIn(_In):
    """查组织架构概览：无参数。"""

class ListLongtasksIn(_In):
    """查长任务列表：无参数。"""

class GlAccountsIn(_In):
    """查科目表：无参数。"""

class GlPeriodsIn(_In):
    """查会计期间：无参数。"""

class GlEntriesIn(_In):
    """查凭证列表。"""

    period_id: int = Field(default=0, description="会计期间 id；省略或 0 = 全部期间")
    limit: int = Field(default=50, ge=1, le=200, description="最多返回条数，默认 50")

class GlTrialBalanceIn(_In):
    """查某期间试算平衡表。"""

    period_id: int = Field(description="会计期间 id（先用 gl_periods 查）")

class GlCreateEntryIn(_In):
    """新建总账凭证。"""

    entry_date: str = Field(description="凭证日期 YYYY-MM-DD")
    description: str = Field(description="凭证摘要")
    lines: list[dict[str, Any]] = Field(
        description="分录数组，每项 {account_id, debit, credit, memo}；借贷必须平衡，金额单位为元"
    )
    post_now: bool = Field(default=False, description="true = 立即过账；默认只建草稿")

class VendorsIn(_In):
    """查供应商：无参数。"""

class PurchaseOrdersIn(_In):
    """查采购单：无参数。"""

class PayablesIn(_In):
    """查应付单：无参数。"""

class ExpenseClaimsIn(_In):
    """查报销单。"""

    status: str = Field(default="", description="draft/submitted/approved/rejected；省略=全部")

class CreatePurchaseOrderIn(_In):
    """新建采购单（草稿）。"""

    vendor_id: int = Field(description="供应商 id（先用 vendors 查）")
    order_date: str = Field(description="采购日期 YYYY-MM-DD")
    amount: float = Field(gt=0, description="采购金额（元）")
    expected_date: str = Field(default="", description="预计到货日期 YYYY-MM-DD，可省略")
    description: str = Field(default="", description="采购说明")

class CreatePayableIn(_In):
    """新建应付单（草稿）。"""

    vendor_id: int = Field(description="供应商 id")
    invoice_date: str = Field(description="发票日期 YYYY-MM-DD")
    amount: float = Field(gt=0, description="价税合计（元）")
    expense_account_id: int = Field(description="借方科目 id（资产或费用类）")
    payable_account_id: int = Field(description="贷方应付科目 id（负债类）")
    po_id: int = Field(default=0, description="关联采购单 id；0 = 不关联")
    invoice_no: str = Field(default="", description="发票号")
    due_date: str = Field(default="", description="到期日 YYYY-MM-DD")
    tax: float = Field(default=0, description="税额（元）")

class LongtaskTemplatesIn(_In):
    """查长任务模板：无参数。"""

class LongtasksIn(_In):
    """查长任务列表：无参数。"""

class RunLongtaskIn(_In):
    """执行长任务。"""

    task_id: str = Field(description="任务 id（先用 longtasks 查）")
    max_stages: int = Field(default=0, ge=0, le=40, description="本次最多跑几个阶段；0 = 全部")


MODELS: dict[str, type[BaseModel]] = {
    "get_gl_summary": GetGlSummaryIn,
    "get_payables_summary": GetPayablesSummaryIn,
    "get_expense_queue": GetExpenseQueueIn,
    "get_org_overview": GetOrgOverviewIn,
    "list_longtasks": ListLongtasksIn,
    "gl_accounts": GlAccountsIn,
    "gl_periods": GlPeriodsIn,
    "gl_entries": GlEntriesIn,
    "gl_trial_balance": GlTrialBalanceIn,
    "gl_create_entry": GlCreateEntryIn,
    "vendors": VendorsIn,
    "purchase_orders": PurchaseOrdersIn,
    "payables": PayablesIn,
    "expense_claims": ExpenseClaimsIn,
    "create_purchase_order": CreatePurchaseOrderIn,
    "create_payable": CreatePayableIn,
    "longtask_templates": LongtaskTemplatesIn,
    "longtasks": LongtasksIn,
    "run_longtask": RunLongtaskIn,
}
