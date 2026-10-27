"""CLI 测试：分层门面是否真的可用（moneyhelper.core / server / cli）。

这一层的价值在于"换成 CLI 调用，core 逻辑还成立"。所以测试重点不是解析细节，
而是：入口能跑通、直连本地库、离线不发网络请求。
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def cli_db(temp_db, monkeypatch):
    """CLI 需要一个真实的库；temp_db 已把 DB_PATH 指到临时文件并建好表。"""
    from app import db

    monkeypatch.setenv("MONEYHELPER_DB_PATH", str(db.DB_PATH))
    return db


def _run(argv: list[str]) -> int:
    from moneyhelper.cli import main

    return main(argv)


def test_cli_add_parses_and_writes(temp_db, capsys):
    rc = _run(["add", "午饭 35 元"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "已记账" in out and "35.00" in out

    import asyncio

    from app import db

    rows = asyncio.run(db.list_transactions())
    assert any(r["item"] == "午饭" for r in rows)


def test_cli_add_unparsable_returns_exit_2(temp_db, capsys):
    # _die 用 SystemExit(2) 表达"解析失败"，命令行下等价于退出码 2
    with pytest.raises(SystemExit) as exc:
        _run(["add", "今天天气不错"])
    assert exc.value.code == 2
    assert "无法" in capsys.readouterr().err


def test_cli_ls_json_output(temp_db, capsys):
    _run(["add", "早饭 8 元"])
    capsys.readouterr()
    rc = _run(["--json", "ls"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list) and payload
    assert "amount" in payload[0]


def test_cli_balance_works_offline(temp_db, capsys):
    """balance 默认走快照价：没有任何网络也不能挂（CLI 的核心定位）。"""
    rc = _run(["balance"])
    assert rc == 0
    assert "组合总市值" in capsys.readouterr().out


def test_cli_report_uses_cashflow_fields(temp_db, capsys):
    _run(["add", "午饭 35 元"])
    capsys.readouterr()
    rc = _run(["report"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "本月收入" in out and "支出" in out and "结余" in out


def test_snapshot_only_context_blocks_network(monkeypatch):
    """quotes.snapshot_only()：期间不发网络请求，直接回快照价。"""
    import asyncio

    from app import quotes

    async def _boom(*a, **kw):
        raise AssertionError("离网模式下不允许发起网络请求")

    monkeypatch.setattr(quotes, "_eastmoney_quotes", _boom)
    monkeypatch.setattr(quotes, "_sina_quotes", _boom)

    positions = [{"symbol": "600519", "kind": "股票", "last": 1500.0}]

    async def _go():
        with quotes.snapshot_only():
            return await quotes.live_quotes(positions)

    got = asyncio.run(_go())
    assert got == {"600519": 1500.0}
    assert quotes.last_source() == "snapshot"


def test_server_facade_exposes_same_app():
    """moneyhelper.server.app 与 app.main.app 必须是同一个对象（不是两份实例）。"""
    from app.main import app as legacy

    from moneyhelper.server import app as facade

    assert facade is legacy


def test_facade_importable_from_any_cwd(tmp_path, monkeypatch):
    """门面层必须在任意工作目录下可用（安装成命令后 cwd 不是仓库）。

    moneyhelper 包通过 re-export 暴露 app.* 的实现，所以导入前必须能定位 backend/。
    此前只在仓库内可导入：`pip install -e .` 后在 /tmp 下执行 moneyhelper CLI 会
    直接 ModuleNotFoundError: No module named 'app'。
    """
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    code = "import moneyhelper, moneyhelper.core, moneyhelper.server; print(moneyhelper.__version__)"
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(repo)},
        timeout=120,
    )
    assert out.returncode == 0, out.stderr[-800:]
    # 版本号来自单一真源（app/version.py），测试不硬编码具体版本
    from app.version import __version__

    assert out.stdout.strip() == __version__
