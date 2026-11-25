# ruff: noqa: F401, I001, RUF022 — 聚合重导出层，导入/导出顺序按循环依赖手工排列
"""Route modules: each subpackage registers CRUD + query routes on the main app's router.

Keeps main.py focused on middleware / core endpoints (ask, confirm, bootstrap, dashboard).
"""

# Re-export each sub-router for inclusion in the main app.
from .authz import router as authz_router
from .autopilot import router as autopilot_router
from .banking import router as banking_router
from .budgets import router as budgets_router
from .calculations import router as calculations_router
from .connect import router as connect_router
from .connect_deep import router as connect_deep_router
from .consolidation import router as consolidation_router
from .debt_payoff import router as debt_payoff_router
from .debts_subs import router as debts_subs_router
from .demo import router as demo_router
from .ecommerce import router as ecommerce_router
from .evaluation import router as evaluation_router
from .execute import router as execute_router
from .expenses import router as expenses_router
from .family import router as family_router
from .external import router as external_router
from .finance_tax import router as finance_tax_router
from .gl import router as gl_router
from .goals import router as goals_router
from .import_routes import router as import_router
from .ledger import router as ledger_router
from .longtask import router as longtask_router
from .market import router as market_router
from .members import router as members_router
from .org import router as org_router
from .paper import router as paper_router
from .plan import router as plan_router
from .procurement import router as procurement_router
from .provenance import router as provenance_router
from .qa import router as qa_router
from .remote import router as remote_router
from .research import router as research_router
from .thread_context import projects_router, router as thread_context_router
from .share import router as share_router
from .review import router as review_router
from .settings import router as settings_router
from .statements import router as statements_router
from .strategy import router as strategy_router
from .studio import router as studio_router
from .system import router as system_router

__all__ = [
    "authz_router",
    "banking_router",
    "budgets_router",
    "calculations_router",
    "connect_deep_router",
    "connect_router",
    "consolidation_router",
    "debt_payoff_router",
    "debts_subs_router",
    "demo_router",
    "evaluation_router",
    "execute_router",
    "expenses_router",
    "family_router",
    "external_router",
    "finance_tax_router",
    "gl_router",
    "goals_router",
    "import_router",
    "ledger_router",
    "longtask_router",
    "market_router",
    "members_router",
    "org_router",
    "paper_router",
    "plan_router",
    "procurement_router",
    "provenance_router",
    "qa_router",
    "remote_router",
    "research_router",
    "thread_context_router",
    "projects_router",
    "share_router",
    "review_router",
    "settings_router",
    "statements_router",
    "strategy_router",
    "studio_router",
    "system_router",
]
