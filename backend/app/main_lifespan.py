"""应用 lifespan 与前端静态目录解析：db/vault/scheduler/studio 的启动与收尾。

从 main.py 拆出（`_mcp_state` 与 MCP 子应用实例也在此维护，挂载逻辑留在 main）。
"""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from . import agent_config, auth, db, llm, scheduler, vault
from .logging_utils import get_logger

log = get_logger(__name__)

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


def _local_vault_passphrase() -> str:
    """本机自动口令：生成一次、落在数据目录（0600），重启后仍能解开旧密文。

    仍然不降级明文：口令只是从"部署者手填"变成"本机自管"。想换口令/搬机器，
    显式设 VAULT_PASSPHRASE 即可，旧密文会按新口令解不开（预期行为）。
    """
    try:
        from .db.db_paths import data_dir

        path = data_dir() / ".vault_key"
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if len(value) >= 8:
                return value
        value = secrets.token_hex(24)
        path.write_text(value, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        log.info("vault: 未设 VAULT_PASSPHRASE，已生成本机口令 %s（0600）", path.name)
        return value
    except Exception as e:  # noqa: BLE001 — 生成失败就退回旧的"拒绝保存"行为
        log.warning("vault: 本机口令生成失败：%s", e)
        return ""


@asynccontextmanager
async def lifespan(app_ref: FastAPI):
    log.info("moneyhelper backend starting up")
    await db.init_db()
    # vault 初始化：优先环境变量；没设时用本机自动生成并持久化的口令，
    # 否则单机用户连 API Key 都存不进去（fail-closed 会把"能存"直接变成"不能存"）。
    vault_pass = os.getenv("VAULT_PASSPHRASE", "").strip()
    if not vault_pass:
        vault_pass = _local_vault_passphrase()
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
        domain = await studio_installer.seed_domain_pack()
        if domain.get("assets"):
            log.info("studio.domain_pack assets=%s", domain["assets"])
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
