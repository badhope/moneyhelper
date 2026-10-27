"""Route modules: each subpackage registers CRUD + query routes on the main app's router.

Keeps main.py focused on middleware / core endpoints (ask, confirm, bootstrap, dashboard).
"""

# Re-export each sub-router for inclusion in the main app.
from .budgets import router as budgets_router
from .calculations import router as calculations_router
from .debts_subs import router as debts_subs_router
from .evaluation import router as evaluation_router
from .family import router as family_router
from .goals import router as goals_router
from .import_routes import router as import_router
from .ledger import router as ledger_router
from .market import router as market_router
from .members import router as members_router
from .paper import router as paper_router
from .provenance import router as provenance_router
from .qa import router as qa_router
from .research import router as research_router
from .settings import router as settings_router
from .statements import router as statements_router
from .strategy import router as strategy_router
from .studio import router as studio_router
from .system import router as system_router

__all__ = [
    "budgets_router",
    "calculations_router",
    "debts_subs_router",
    "evaluation_router",
    "family_router",
    "goals_router",
    "import_router",
    "ledger_router",
    "market_router",
    "members_router",
    "paper_router",
    "provenance_router",
    "qa_router",
    "research_router",
    "settings_router",
    "statements_router",
    "strategy_router",
    "studio_router",
    "system_router",
]
