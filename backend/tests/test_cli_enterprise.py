"""CLI 企业域子命令（切片 11）：gl / procure / longtask。

判据：命令真的能列出库里的数据，不是空壳；输出对得上刚写入的行。
"""

from __future__ import annotations

import pytest

from moneyhelper import cli


class _Args:
    def __init__(self, **kw):
        self.url = ""
        self.token = ""
        self.json = False
        self.period = 0
        self.limit = 50
        self.id = ""
        self.__dict__.update(kw)


async def _seed(temp_db):
    from app import db

    await db.gl_create_account(0, "1001", "库存现金", "asset")
    await db.gl_create_account(0, "4001", "营业收入", "income")
    period = await db.gl_create_period(0, 2026, 11)
    v = await db.vendor_create(0, "V001", "CLI供应商")
    po = await db.po_create(0, int(v["id"]), "2026-11-05", "", 2000, "CLI测试采购")
    return period, v, po


async def test_cli_gl_accounts(temp_db, capsys) -> None:
    await _seed(temp_db)
    code = await cli.cmd_gl(_Args(action="accounts"))
    out = capsys.readouterr().out
    assert code == 0
    assert "1001" in out and "库存现金" in out


async def test_cli_gl_periods(temp_db, capsys) -> None:
    await _seed(temp_db)
    code = await cli.cmd_gl(_Args(action="periods"))
    out = capsys.readouterr().out
    assert code == 0
    assert "2026-11" in out and "open" in out


async def test_cli_gl_trial_requires_balanced(temp_db, capsys) -> None:
    period, _v, _po = await _seed(temp_db)
    from app import db

    cash = next(a for a in await db.gl_list_accounts(0) if a["code"] == "1001")
    rev = next(a for a in await db.gl_list_accounts(0) if a["code"] == "4001")
    entry = await db.gl_create_entry(
        0,
        "2026-11-10",
        "销售",
        [
            {"account_id": cash["id"], "debit": 100, "credit": 0},
            {"account_id": rev["id"], "debit": 0, "credit": 100},
        ],
        0,
    )
    await db.gl_post_entry(0, int(entry["id"]))

    code = await cli.cmd_gl(_Args(action="trial", period=period["id"]))
    out = capsys.readouterr().out
    assert code == 0
    assert "平衡" in out and "不平衡" not in out


async def test_cli_procure_vendors_and_orders(temp_db, capsys) -> None:
    await _seed(temp_db)
    assert await cli.cmd_procure(_Args(action="vendors")) == 0
    out = capsys.readouterr().out
    assert "V001" in out and "CLI供应商" in out

    assert await cli.cmd_procure(_Args(action="orders")) == 0
    out = capsys.readouterr().out
    assert "PO-" in out and "CLI测试采购" in out


async def test_cli_longtask_templates(temp_db, capsys) -> None:
    assert await cli.cmd_longtask(_Args(action="templates")) == 0
    out = capsys.readouterr().out
    for kind in ("novel", "webapp", "docx", "paper", "program"):
        assert kind in out


async def test_cli_longtask_list_shows_created(temp_db, capsys) -> None:
    from app import longtask

    task = await longtask.create_task("program", "CLI任务", "目标", stages=["a"])
    assert await cli.cmd_longtask(_Args(action="list")) == 0
    out = capsys.readouterr().out
    assert task["id"] in out and "CLI任务" in out


async def test_cli_gl_trial_without_period_exits() -> None:
    with pytest.raises(SystemExit):
        await cli.cmd_gl(_Args(action="trial", period=0))
