import os
import sys
import tempfile
from pathlib import Path

import pytest

# xdist worker 级数据目录隔离（必须在导入 app 之前设置）：
# agent_graph 的 checkpoint/pending 库路径在模块导入期由 db.data_dir() 解析，
# 若多个 worker 共享 backend/data，Windows 上"最后关闭连接的进程会删 -wal/-shm"，
# 其余 worker 随机抛 "attempt to write a readonly database"，且测试会污染真实数据目录。
# 主库 DB_PATH 由 temp_db fixture 指向 tmp_path，不受此影响；这里只为 checkpoint/pending
# 提供每 worker 独立目录（带 PID，避免同机并行多个 pytest 会话互踩）。
os.environ.setdefault(
    "MONEYHELPER_DATA_DIR",
    str(
        Path(tempfile.gettempdir())
        / f"xman-test-{os.environ.get('PYTEST_XDIST_WORKER') or 'single'}-{os.getpid()}"
    ),
)

# 测试默认关闭限流，避免高频接口测例触发 429；限流本身由 test_rate_limit.py 显式测
os.environ.setdefault("MONEYHELPER_DISABLE_RATE_LIMIT", "1")
os.environ.setdefault("VAULT_PASSPHRASE", "test-passphrase-for-unit-tests-12345")
# 固定 JWT 密钥：否则 auth 模块每次导入生成随机 secret，
# 同一测试里签发与校验可能跨模块实例而不一致（多租户 HTTP 测试会 401）。
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests-32bytes")

# 在导入 app 前初始化 vault（test_api.py 使用 ASGITransport 不触发 lifespan → vault 需手动激活）
from app import vault as _vault

_vault.init_master_passphrase("test-passphrase-for-unit-tests-12345")
_vault.activate()

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# 分层门面包 moneyhelper.* 在仓库根目录（与 backend/ 平级），测试从 backend/ 运行
_REPO_ROOT = _BACKEND.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
async def temp_db(tmp_path, monkeypatch):
    """临时内存库（test_api.py 自带同语义本地 fixture，此处供其余测试文件复用）。
    生产首启为空账本（不种示例），测试业务需要示例数据，故显式种入。"""
    from app import db

    monkeypatch.setattr(db._core, "DB_PATH", tmp_path / "wealth.db")
    # 连接缓存陷阱：db._db 为模块级单连接，若上一个测试遗留了真实库连接，
    # init_db 会直接复用导致本测试写进真实库——先强制关闭再按临时路径重开
    await db.close_db()
    # 活跃成员是**进程级全局状态**（_active_member_id）。上一个用例设置后未清理，
    # 会让本用例新写的流水挂到"别的库里的成员 id"上，触发外键失败
    # （并行跑时表现为随机 IntegrityError）。每个用例开始前清零。
    db._active_member_id.clear()
    await db.init_db()
    await db.reset_to_seed()
    yield
    await db.close_db()


@pytest.fixture(autouse=True)
async def _close_agent_checkpoints(tmp_path, monkeypatch):
    """每个测试独占 checkpoint/pending 文件，并在结束释放 LangGraph 磁盘连接。

    agent_graph 按 event loop 缓存 AsyncSqliteSaver 连接；pytest-asyncio 每个测试
    新建并关闭 loop，若连接不及时关闭，aiosqlite worker 线程会在 loop 关闭后残留，
    导致 pytest 进程退出挂住。teardown 时统一关闭以释放文件锁与线程。

    除此之外还要把两个库路径指到本测试独占的 tmp 文件：checkpoint 库被上一个
    测试的连接以 WAL 打开又关闭后，Windows 上「最后关闭者删 -wal/-shm」会让
    下一个连接随机抛 "attempt to write a readonly database"（xdist 下更频繁，
    曾 4 轮出现 2 轮）。每测试一个全新文件从根上消除跨测试的 WAL 生命周期竞争。
    """
    from app import agent_graph

    monkeypatch.setattr(agent_graph, "_CHECKPOINT_DB", tmp_path / "agent_checkpoints.db")
    monkeypatch.setattr(agent_graph, "_PENDING_DB", tmp_path / "agent_pending.db")
    yield
    try:
        await agent_graph.close_checkpoints()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """默认不触达真实模型：把 llm 配置缓存置为「未配置」，让未显式 mock 的测试走确定性路径。

    开发机 .env 若配了可用模型，llm._config() 会读到真实端点并触网（慢/超时/依赖外网）。
    这里把 _cfg 置为 {}（_config() 返回 None = 未配置），使每个测试默认按「未接入模型」
    运行，只测确定性内核；需要验证 LLM 路径的测试自行 monkeypatch llm_available /
    stream_narrate / run_agent（仍会覆盖本默认）。
    """
    from app import llm

    monkeypatch.setattr(llm, "_cfg", {})
    monkeypatch.setattr(llm, "_client_singleton", None)
