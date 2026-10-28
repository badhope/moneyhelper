"""FastAPI 入口（薄装配层，M1.4 拆分后）：中间件注册 + 路由装配 + lifespan + 静态托管。

鉴权：设置 API_TOKEN 后，所有 /api/* 需带 `Authorization: Bearer <口令>`
或查询参数 `?token=<口令>`；未设置则仅限本机/内网使用。

各域端点实现见：
- backend/app/middleware.py     全局中间件（限流/鉴权/Host 防护/安全头/观测/审计）
- backend/app/routes/qa.py      问答 SSE / HITL 确认 / 历史 / 会话
- backend/app/routes/ledger.py  仪表盘 / 持仓 / 流水 / 一句话记账 / CSV / 撤回 / 体检
- backend/app/routes/system.py  认证 / 健康 / 指标 / 记忆 / 反思 / 审计 / 附件 /
                                导出导入 / 晨报 / 调度 / 日志 / Agent 配置
- backend/app/routes/*.py       预算 / 目标 / 负债 / 行情 / 家庭 / 设置等（M1.4 前已拆）
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import agent_config, auth, db, llm, scheduler, vault
from .logging_utils import get_logger as _get_logger
from .middleware import setup as setup_middleware
from .routes import (
    budgets_router,
    calculations_router,
    debts_subs_router,
    evaluation_router,
    family_router,
    goals_router,
    import_router,
    ledger_router,
    market_router,
    members_router,
    paper_router,
    provenance_router,
    qa_router,
    research_router,
    settings_router,
    statements_router,
    strategy_router,
    studio_router,
    system_router,
)
from .version import __version__

log = _get_logger(__name__)

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent.parent  # 仓库根目录


def _frontend_dist() -> Path:
    """前端静态目录。

    - 源码运行：仓库根的 frontend/dist
    - PyInstaller 单文件：解压目录下的 static/（见 moneyhelper.spec 的 datas）
    """
    import sys

    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "static"
    return PROJECT_DIR / "frontend" / "dist"


FRONTEND_DIST = _frontend_dist()


async def _maybe_create_admin() -> None:
    """首次启动（零用户时）从环境变量创建管理员账号。
    变量：ADMIN_USERNAME / ADMIN_PASSWORD（同时设置才生效）。"""
    if await db.user_count() > 0:
        return
    username = os.getenv("ADMIN_USERNAME", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "").strip()
    if username and password:
        try:
            uid = await db.user_create(
                username, password, display_name=username, role="admin"
            )
            log.info("Initial admin created: id=%d username=%s", uid, username)
        except Exception as e:
            log.warning("Admin creation failed: %s", e)


@asynccontextmanager
async def lifespan(app_ref: FastAPI):
    log.info("moneyhelper backend starting up")
    await db.init_db()
    # vault 初始化：从环境变量取主口令（可选；未设则 ai_api_key 将拒绝加密存储）
    vault_pass = os.getenv("VAULT_PASSPHRASE", "").strip()
    if vault_pass:
        try:
            vault.init_master_passphrase(vault_pass)
            vault.activate()
            log.info("vault initialized")
        except Exception as e:
            log.warning("vault init failed: %s — ai_api_key 将拒绝加密存储", e)
    # JWT secret 弱默认值告警
    auth.check_jwt_secret()
    # 首次启动无用户时，从环境变量创建管理员（可选）
    await _maybe_create_admin()
    await scheduler.start()
    # Langfuse 观测：懒初始化（没配 env 就 no-op）
    from . import observability

    observability._init()
    # Agent 配置：初始化默认角色/skills/工具配置
    await agent_config.init_default_config()
    # Studio 默认包：提示词 / 约束 / Hook / 内置工具（非空起步）
    from .studio import store as studio_store
    from .studio import watchdog as studio_watchdog

    await studio_store.get_config()
    # 出厂预装：非 MCP 的市场资产默认装好并启用（用户可删可关，不会重启复活）
    from .studio import installer as studio_installer

    try:
        await studio_installer.seed_default_bundle()
        # 修复 MCP 配置漂移（mcp.json 在 data/ 下，与 DB 里的 seeded 标记不同生命周期）
        repaired = await studio_installer.repair_mcp_config()
        if repaired.get("repaired"):
            log.info("studio.mcp_repaired %s", repaired["repaired"])
    except Exception as exc:  # noqa: BLE001 — 预装失败不阻断启动
        log.warning("studio.seed_default_bundle failed: %s", exc)
    await studio_watchdog.start()
    log.info("database initialised, scheduler started")
    yield
    log.info("moneyhelper backend shutting down")
    from .studio import watchdog as studio_watchdog

    await studio_watchdog.stop()
    await scheduler.stop()
    await llm.aclose()
    vault.reset_cache()
    await db.close_db()
    # Langfuse flush：把缓存的 trace 刷出去
    observability.flush()
    log.info("moneyhelper backend shutdown complete")
    # 关闭 agent HITL 进程内注册表持有的磁盘连接（同步 sqlite3，需在 loop 关闭前清理）
    from .agent_graph import close_checkpoints

    await close_checkpoints()


# ---------------------------------------------------------------------------
# FastAPI 实例 + 全局异常兜底 + 中间件（注册顺序见 middleware.setup）
# ---------------------------------------------------------------------------
# MCP 子应用必须先构建，才能把它的 lifespan 接进父 app（见下方 _combined_lifespan）。
# Streamable HTTP 的 session manager 在 lifespan 里启动 task group；不接就报
# "Task group is not initialized"，MCP 端点会 405/500（M2.2 实测）。
#
# 注意：StreamableHTTPSessionManager.run() 每个实例只能调一次。若在模块导入时
# 构建一次、却在多个 app 实例/多次 lifespan 里复用，第二次启动会抛
# "can only be called once per instance"（TestClient 每次进入都会跑 lifespan，
# 测试里必然踩到；生产里热重载同理）。所以按 lifespan 次数重建：
# 在 _combined_lifespan 进入时构建，退出时丢弃。
_mcp_enabled = os.getenv("MCP_ENABLE", "1") == "1"

# MCP 子应用的"当前实例"：挂载时注册的 ASGI 路由在进程生命周期内固定，
# 而 session manager 每个实例只能 run 一次。两者要指向同一个对象，
# 所以用可变容器：lifespan 每次进入时把新实例写进 _mcp_state，
# 挂载的路由通过动态转发读取当前实例（见 mcp_server.mount_to_app 的 built 参数约定）。
_mcp_state: dict[str, object] = {"built": None}


@asynccontextmanager
async def _combined_lifespan(app_ref: FastAPI):
    """Moneyhelper 自身 lifespan + MCP 子应用 lifespan。

    子应用的 lifespan 由 Starlette 在 mount 时**不会**自动转发，必须在这里
    显式嵌套进入，否则 MCP 的 session manager 永远不会启动。

    每次进入都构建新实例：session manager 的 run() 只能调一次，
    复用会在第二次启动时报 "can only be called once per instance"。
    """
    built = None
    if _mcp_enabled:
        try:
            from .mcp_server import build_asgi

            built = build_asgi()
            _mcp_state["built"] = built
        except Exception as exc:  # noqa: BLE001 — MCP 构建失败不该拖垮主服务
            log.warning("mcp.build_failed: %s — MCP 端点不可用", exc)

    streamable_lifespan = getattr(built[0], "lifespan", None) if built else None
    if streamable_lifespan is None:
        async with lifespan(app_ref):
            yield
        return

    async with streamable_lifespan(app_ref), lifespan(app_ref):
        yield


app = FastAPI(title="Moneyhelper API", version=__version__, lifespan=_combined_lifespan)


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
app.include_router(settings_router)
app.include_router(goals_router)
app.include_router(debts_subs_router)
app.include_router(market_router)
app.include_router(calculations_router)
app.include_router(strategy_router)
app.include_router(studio_router)
app.include_router(evaluation_router)
app.include_router(import_router)
app.include_router(paper_router)
app.include_router(provenance_router)
app.include_router(members_router)
app.include_router(family_router)
app.include_router(qa_router)
app.include_router(ledger_router)
app.include_router(system_router)
app.include_router(research_router)
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
