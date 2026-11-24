"""FastAPI 应用装配：异常兜底、中间件、路由注册、MCP 挂载与静态前端。

lifespan（含 MCP 子应用嵌套）与前端目录解析在 `main_lifespan.py`，此处导入并
re-export，保持 `app.main.lifespan` 等历史引用可见。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .logging_utils import get_logger as _get_logger
from .main_lifespan import (  # noqa: F401 — 兼容旧引用
    APP_DIR,
    FRONTEND_DIST,
    PROJECT_DIR,
    _combined_lifespan,
    _frontend_dist,
    _maybe_create_admin,
    _mcp_enabled,
    _mcp_state,
    lifespan,
)
from .middleware import setup as setup_middleware
from .routes import (
    authz_router,
    banking_router,
    budgets_router,
    calculations_router,
    connect_deep_router,
    connect_router,
    consolidation_router,
    debt_payoff_router,
    debts_subs_router,
    demo_router,
    evaluation_router,
    execute_router,
    expenses_router,
    family_router,
    finance_tax_router,
    gl_router,
    goals_router,
    import_router,
    ledger_router,
    longtask_router,
    market_router,
    members_router,
    org_router,
    paper_router,
    plan_router,
    procurement_router,
    provenance_router,
    qa_router,
    remote_router,
    research_router,
    projects_router,
    thread_context_router,
    share_router,
    review_router,
    settings_router,
    statements_router,
    strategy_router,
    studio_router,
    system_router,
)
from .version import __version__

log = _get_logger(__name__)

app = FastAPI(title="Moneyhelper API", version=__version__, lifespan=_combined_lifespan)


@app.exception_handler(ValueError)
async def _value_error_handler(request: Request, exc: ValueError):
    """把业务校验的 ValueError 统一转成 400，而不是漏成 500。

    背景：db 层用 ValueError 表达「输入非法」（代码不能为空 / 金额为负 …），
    但路由要逐个 try/except 才能转成 4xx。漏掉的路径（如 POST /api/watchlist
    传空 symbol）就会冒到兜底处理器变成 500——用户看到"内部错误"，
    实际只是他少填了一个字段，也没法从提示里知道该改什么。

    约定：ValueError 的 message 视为**可展示给用户的文案**（现有 db 层的
    报错文案都是这种），因此直接回传；技术细节（堆栈）仍只进日志。
    """
    detail = str(exc) or "请求参数不合法"
    log.warning("bad request in %s %s: %s", request.method, request.url.path, detail)
    return JSONResponse({"error": detail}, status_code=400)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("unhandled exception in %s %s", request.method, request.url.path)
    # 不回吐异常细节（避免泄露 SQL/路径/内部模块），细节只进日志
    return JSONResponse({"error": "内部错误，请查看服务日志"}, status_code=500)


setup_middleware(app)

# ---------------------------------------------------------------------------
# 路由装配（顺序保持拆分前语义：既有 router 先注册，M1.4 新拆 router 后注册，
# 保证 /api/import/csv 的遮蔽关系与拆分前一致）
# ---------------------------------------------------------------------------

app.include_router(budgets_router)
app.include_router(banking_router)
app.include_router(settings_router)
app.include_router(goals_router)
app.include_router(debts_subs_router)
app.include_router(demo_router)
app.include_router(debt_payoff_router)
app.include_router(market_router)
app.include_router(calculations_router)
app.include_router(connect_router)
app.include_router(connect_deep_router)
app.include_router(consolidation_router)
app.include_router(plan_router)
app.include_router(finance_tax_router)
app.include_router(gl_router)
app.include_router(execute_router)
app.include_router(expenses_router)
app.include_router(procurement_router)
app.include_router(longtask_router)
app.include_router(strategy_router)
app.include_router(studio_router)
app.include_router(evaluation_router)
app.include_router(import_router)
app.include_router(paper_router)
app.include_router(provenance_router)
app.include_router(remote_router)
app.include_router(members_router)
app.include_router(org_router)
app.include_router(authz_router)
app.include_router(family_router)
app.include_router(qa_router)
app.include_router(ledger_router)
app.include_router(system_router)
app.include_router(research_router)
app.include_router(thread_context_router)
app.include_router(projects_router)
app.include_router(share_router)
app.include_router(review_router)
app.include_router(statements_router)


# ---------------------------------------------------------------------------
# M3 财务部门模式：一句话 → 工单分解 → 四部门并行 → 秘书呈批
# ---------------------------------------------------------------------------


@app.post("/api/department/run")
async def department_run(payload: dict) -> dict:
    """部门模式入口（JSON 版；SSE 实况看板事件流为下一迭代）。"""
    from .department import run_department_mode

    q = str((payload or {}).get("question", "")).strip()
    if not q:
        return JSONResponse({"error": "question 必填"}, status_code=400)
    events: list[dict] = []

    async def emit(e: dict) -> None:
        events.append(e)

    report = await run_department_mode(q, emit)
    # 与 SSE 路径一致：落库后才能跨请求审批（M3.5）
    try:
        report_id = await db.dept_report_save(q, report)
        report = {**report, "report_id": report_id, "status": "pending"}
    except Exception:  # noqa: BLE001 — 落库失败不阻断交付
        log.exception("dept_report save failed")
    return {"report": report, "events": events}


# ---------------------------------------------------------------------------
# MCP Server：Moneyhelper 财务工具 → MCP 协议（Claude Code / Cursor / 任何 MCP Client 接入）
# ---------------------------------------------------------------------------

if _mcp_enabled:
    from .mcp_server import mount_to_app

    # 挂载用的子应用与 lifespan 里的必须是同一个实例，否则 session manager
    # 不会启动（Streamable HTTP 会 405）。这里构建一次供挂载，lifespan 里
    # 复用同一实例并在退出时不重建 —— 见 _combined_lifespan 的实现。
    mount_to_app(app, _mcp_state)


# ---------------------------------------------------------------------------
# 静态前端托管（同域单端口）
# ---------------------------------------------------------------------------

if FRONTEND_DIST.is_dir():

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(
            FRONTEND_DIST / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="web")
else:

    @app.get("/", include_in_schema=False)
    async def placeholder() -> dict:
        return {"message": "前端未构建：cd frontend && npm install && npm run build"}


# ---------------------------------------------------------------------------
# 兼容别名（过渡期）：测试与潜在外部调用方仍经 app.main 访问这些符号；
# M1.1 core/server 包拆分时统一清理。
# ---------------------------------------------------------------------------

# 限流符号（test_rate_limit / test_m0_fixes 直接引用）
from .middleware import (  # noqa: E402,F401
    _RATE_LIMIT_ENABLED,
    _RATE_LIMIT_MAX,
    _RATE_LIMIT_WINDOW,
    _rate_buckets,
    _rate_limit_check,
)

# SSE 基建（历史符号，供内部/测试引用）
from .routes.qa import _LoopSafeEventSourceResponse  # noqa: E402,F401

# 系统域处理函数（test_summary_models / test_skill_actions 直接调用）
from .routes.system import (  # noqa: E402,F401
    bootstrap,
    clear_reflections,
    create_reflection,
    reflections,
    scheduled_outputs,
    update_agent_config,
)
